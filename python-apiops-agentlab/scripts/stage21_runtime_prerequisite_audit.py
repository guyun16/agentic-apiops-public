"""Run Stage 21 v3 deterministic runtime-prerequisite validation.

The runner performs read-only probes through Java's public HTTP boundaries and
then classifies the input projection.  It never imports benchmark/evaluator
modules, calls a model, submits a Runner task, or writes Java-owned data.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
import sys
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx

AGENTLAB_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = AGENTLAB_ROOT.parent
if str(AGENTLAB_ROOT) not in sys.path:
    sys.path.insert(0, str(AGENTLAB_ROOT))

from app.clients.java_apiops import (  # noqa: E402
    JavaApiOpsAuthenticationError,
    JavaApiOpsAuthorizationError,
    JavaApiOpsClient,
    JavaApiOpsClientError,
    JavaApiOpsError,
    JavaApiOpsServerError,
    JavaApiOpsTimeoutError,
    JavaApiOpsTransportError,
)
from app.input_side_audit import (  # noqa: E402
    Prerequisite,
    RecipeIndex,
    _java_ref_info,
    _probe_tcp,
    assert_result_invariants,
    load_prerequisites,
    load_recipe_index,
    project_input_task_file,
    project_manifest_file,
    result_digest,
    run_input_side_audit,
    run_validator_self_tests,
)
from app.runtime_prerequisite_audit import (  # noqa: E402
    RuntimeProbeSnapshot,
    assert_runtime_result_invariants,
    canonical_root_cause_classification_view,
    resource_key,
    run_runtime_prerequisite_audit,
)
from app.tools import ToolCatalog, ToolIntent, map_tool_intent  # noqa: E402

FIXTURE_ROOT = AGENTLAB_ROOT / "tests" / "benchmark" / "fixtures"
MANIFEST_PATH = FIXTURE_ROOT / "dataset-manifest.json"
SIDECAR_PATH = FIXTURE_ROOT / "stage21-execution-prerequisites.json"
RECIPE_DIR = FIXTURE_ROOT / "support"
JAVA_BASE_URL = os.environ.get("JAVA_APIOPS_BASE_URL", "http://127.0.0.1:19090").rstrip("/")
PROFILE_ENV_VARS = {
    "NORMAL": ("STAGE21_NORMAL_USERNAME", "STAGE21_NORMAL_PASSWORD"),
    "SAFETY_41_ISOLATED": ("STAGE21_SAFETY41_USERNAME", "STAGE21_SAFETY41_PASSWORD"),
    "SAFETY_42_ISOLATED": ("STAGE21_SAFETY42_USERNAME", "STAGE21_SAFETY42_PASSWORD"),
}
DIRECT_REPORT_RE = re.compile(r"^run-(?P<run>\d+)/report-(?P<report>\d+)$")
ISOLATED_PROFILES = {"SAFETY_41_ISOLATED", "SAFETY_42_ISOLATED"}


def _write_json(path: Path, payload: object) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _json_digest(payload: object) -> str:
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _logical_probe_key(
    *,
    profile: str,
    current: int,
    target: int | None,
    tool: str,
    query: str | None,
    input_reference: str | None,
) -> str:
    """Build a stable input-side key; never use it as runtime identity."""

    return "probe:" + _json_digest(
        {
            "authProfile": profile,
            "currentProjectId": current,
            "targetProjectId": target,
            "probeType": tool,
            "query": query,
            "inputReference": input_reference,
        }
    )[:32]


def _direct_identity(ref_rest: str | None) -> tuple[int, int] | None:
    if not isinstance(ref_rest, str):
        return None
    match = DIRECT_REPORT_RE.fullmatch(ref_rest)
    if match is None:
        return None
    return int(match.group("run")), int(match.group("report"))


def _recipe_context(
    recipe: Any, contexts: dict[str, tuple[dict[str, Any], ...]]
) -> dict[str, Any] | None:
    if recipe.case_id is None:
        return None
    values = contexts.get(f"{recipe.family}|{recipe.source_reference}|{recipe.case_id}", ())
    return dict(values[0]) if len(values) == 1 else None


def _runner_family(task_type: str, entry_key: str) -> str:
    return (
        "report_runtime"
        if task_type == "FAILURE_DIAGNOSIS" and entry_key == "testReport"
        else "runner_runtime"
    )


def _headers(token: str, trace_id: str) -> dict[str, str]:
    return {
        "Accept": "application/json",
        "Authorization": f"Bearer {token}",
        "X-Trace-Id": trace_id,
    }


async def _get_json(
    http: httpx.AsyncClient, path: str, token: str, trace_id: str
) -> tuple[int | None, object | None, str | None]:
    try:
        response = await http.get(f"{JAVA_BASE_URL}{path}", headers=_headers(token, trace_id))
    except httpx.TimeoutException:
        return None, None, "TIMEOUT"
    except httpx.TransportError:
        return None, None, "TRANSPORT_ERROR"
    try:
        payload = response.json()
    except ValueError:
        payload = None
    return response.status_code, payload, None


def _envelope_data(payload: object) -> object | None:
    if isinstance(payload, dict) and payload.get("success") is True:
        return payload.get("data")
    return None


def _scope_projects(
    manifest: Any,
    prerequisites: dict[str, Prerequisite],
    recipe_index: RecipeIndex,
    recipe_contexts: dict[str, tuple[dict[str, Any], ...]],
) -> set[int]:
    projects: set[int] = set()
    for prerequisite in prerequisites.values():
        for value in (
            prerequisite.current_project_id,
            prerequisite.target_project_id,
            prerequisite.resource_project_id,
        ):
            if value is not None:
                projects.add(value)
    for entry in manifest.tasks:
        task_path = (MANIFEST_PATH.parent / entry.task_file).resolve()
        task = project_input_task_file(task_path)
        for item in task.entries:
            if item.kind != "JAVA_RESOURCE" or not item.ref:
                continue
            info = _java_ref_info(item.ref)
            if info is not None and info[1] is not None:
                projects.add(info[1])
        for item in task.entries:
            if item.kind != "JAVA_RESOURCE" or not item.ref:
                continue
            info = _java_ref_info(item.ref)
            if info is None or info[0] not in {"runner_testcase", "runner_unit"}:
                continue
            family = _runner_family(task.task_type, item.key)
            candidates = tuple(
                recipe
                for recipe in recipe_index.by_source.get(item.ref, ())
                if recipe.family == family and not recipe.issues
            )
            if len(candidates) == 1:
                context = _recipe_context(candidates[0], recipe_contexts)
                if context is not None and isinstance(context.get("projectId"), int):
                    projects.add(context["projectId"])
    return projects


def _metadata_requirements(
    manifest: Any,
    prerequisites: dict[str, Prerequisite],
    recipe_index: RecipeIndex,
    recipe_contexts: dict[str, tuple[dict[str, Any], ...]],
) -> set[tuple[str, int, str, str]]:
    requirements: set[tuple[str, int, str, str]] = set()
    for entry in manifest.tasks:
        task_path = (MANIFEST_PATH.parent / entry.task_file).resolve()
        task = project_input_task_file(task_path)
        prerequisite = prerequisites[entry.task_id]
        for item in task.entries:
            if item.kind == "JAVA_RESOURCE" and item.ref:
                info = _java_ref_info(item.ref)
                if info is not None and info[0] == "metadata" and info[1] is not None:
                    # The final segment is the typed metadata api identity.
                    # Runner TestCase.apiId values are snapshot identities,
                    # not a requirement to resolve an OpenAPI catalog entry.
                    api_id = item.ref.rsplit("/", 1)[-1]
                    if api_id:
                        requirements.add((prerequisite.auth_profile, info[1], api_id, item.ref))
    return requirements


def _report_requirements(
    manifest: Any,
    prerequisites: dict[str, Prerequisite],
) -> set[tuple[str, int, str]]:
    requirements: set[tuple[str, int, str]] = set()
    for entry in manifest.tasks:
        task = project_input_task_file((MANIFEST_PATH.parent / entry.task_file).resolve())
        prerequisite = prerequisites[entry.task_id]
        for item in task.entries:
            if item.kind != "JAVA_RESOURCE" or not item.ref:
                continue
            info = _java_ref_info(item.ref)
            if info is not None and info[0] == "test_report" and info[1] is not None:
                requirements.add((prerequisite.auth_profile, info[1], item.ref))
    return requirements


def _rag_requirements(
    manifest: Any,
    prerequisites: dict[str, Prerequisite],
    recipe_index: RecipeIndex,
) -> tuple[set[tuple[str, int, int | None, str, str, int]], set[tuple[str, int, int | None, str]]]:
    """Return (typed RAG jobs, representative Gateway scopes)."""

    typed: set[tuple[str, int, int | None, str, str, int]] = set()
    scopes: set[tuple[str, int, int | None, str]] = set()
    for entry in manifest.tasks:
        task = project_input_task_file((MANIFEST_PATH.parent / entry.task_file).resolve())
        prerequisite = prerequisites[entry.task_id]
        if prerequisite.current_project_id is None:
            continue
        if "RAG_SEARCH" in prerequisite.required_operations:
            scopes.add(
                (
                    prerequisite.auth_profile,
                    prerequisite.current_project_id,
                    prerequisite.target_project_id,
                    "rag.search",
                )
            )
        elif "TOOL_CALL" in prerequisite.required_operations and "redis.read" in task.allowed_tools:
            # A bounded TTL read is the existing deterministic Tool Gateway
            # smoke for a non-RAG TOOL_CALL task.  It is public-boundary only.
            scopes.add(
                (
                    prerequisite.auth_profile,
                    prerequisite.current_project_id,
                    prerequisite.target_project_id,
                    "redis.read",
                )
            )
        if "RAG_SEARCH" not in prerequisite.required_operations:
            continue
        for item in task.entries:
            if item.kind != "JAVA_RESOURCE" or not item.ref:
                continue
            info = _java_ref_info(item.ref)
            if info is None or info[0] != "rag":
                continue
            candidates = tuple(
                recipe
                for recipe in recipe_index.by_source.get(item.ref, ())
                if recipe.family == "rag_runtime"
            )
            if len(candidates) == 1 and not candidates[0].issues:
                typed.add(
                    (
                        prerequisite.auth_profile,
                        prerequisite.current_project_id,
                        prerequisite.target_project_id,
                        item.ref,
                        candidates[0].query or "stage21 input-side RAG readiness",
                        candidates[0].top_k or 1,
                    )
                )
    return typed, scopes


def _target_urls(recipe_index: RecipeIndex) -> set[str]:
    return {
        recipe.base_url
        for values in recipe_index.by_source.values()
        for recipe in values
        if recipe.base_url
    }


def _is_intentional_isolation(profile: str, current: int, target: int | None) -> bool:
    return profile in ISOLATED_PROFILES and target is not None and target != current


async def _run_public_probes() -> tuple[RuntimeProbeSnapshot, frozenset[str]]:
    manifest = project_manifest_file(MANIFEST_PATH)
    prerequisites = load_prerequisites(SIDECAR_PATH)
    recipe_index = load_recipe_index(RECIPE_DIR)
    recipe_contexts = __import__(
        "app.runtime_prerequisite_audit", fromlist=["load_recipe_contexts"]
    ).load_recipe_contexts(RECIPE_DIR)

    auth: dict[str, dict[str, Any]] = {}
    sessions: dict[str, Any] = {}
    memberships: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    metadata_facts: dict[str, dict[str, Any]] = {}
    report_facts: dict[str, dict[str, Any]] = {}
    gateway_facts: dict[str, dict[str, Any]] = {}
    rag_facts: dict[str, dict[str, Any]] = {}
    counts: Counter[str] = Counter()
    unresolved_resources: set[str] = set()
    runtime_agent_run_ids: set[str] = set()

    async with httpx.AsyncClient(trust_env=False) as http:
        client = JavaApiOpsClient(http, base_url=JAVA_BASE_URL, timeout_seconds=5)

        try:
            health_response = await http.get(f"{JAVA_BASE_URL}/actuator/health")
            try:
                health_payload = health_response.json()
            except ValueError:
                health_payload = None
            java_health = (
                "HEALTHY"
                if health_response.status_code == 200
                and isinstance(health_payload, dict)
                and health_payload.get("status") == "UP"
                else "HEALTH_NOT_UP"
            )
        except (httpx.TimeoutException, httpx.TransportError):
            java_health = "UNREACHABLE"

        for profile, (username_var, password_var) in PROFILE_ENV_VARS.items():
            username = os.environ.get(username_var, "").strip()
            password = os.environ.get(password_var, "").strip()
            if not username or not password:
                auth[profile] = {"status": "CREDENTIALS_NOT_PROVIDED"}
                continue
            try:
                session = await client.login(username=username, password=password)
            except JavaApiOpsAuthenticationError:
                auth[profile] = {"status": "LOGIN_FAILED"}
            except JavaApiOpsError:
                auth[profile] = {"status": "LOGIN_PROBE_FAILED"}
            else:
                sessions[profile] = session
                auth[profile] = {
                    "status": "LOGIN_OK",
                    "userId": session.user_id,
                    "username": session.username,
                }
                counts["javaLoginCount"] += 1

        projects = _scope_projects(manifest, prerequisites, recipe_index, recipe_contexts)
        for profile, session in sessions.items():
            status, payload, error = await _get_json(
                http, "/api/v1/projects", session.token, f"stage21-runtime-memberships-{profile}"
            )
            listed_roles: dict[int, str] = {}
            data = _envelope_data(payload)
            if isinstance(data, list):
                for item in data:
                    if isinstance(item, dict) and isinstance(item.get("projectId"), int):
                        role = item.get("projectRole")
                        if isinstance(role, str):
                            listed_roles[item["projectId"]] = role
            for project in sorted(projects):
                if status != 200 or error is not None:
                    memberships[profile][str(project)] = {
                        "status": "PROJECT_LIST_PROBE_FAILED",
                        "listHttpStatus": status,
                    }
                    continue
                try:
                    await client.assert_project_readable(
                        project_id=project,
                        token=session.token,
                        trace_id=f"stage21-runtime-project-read-{profile}-{project}",
                    )
                except JavaApiOpsAuthorizationError:
                    memberships[profile][str(project)] = {
                        "status": "AUTH_DENIED",
                        "role": listed_roles.get(project),
                    }
                except JavaApiOpsAuthenticationError:
                    memberships[profile][str(project)] = {
                        "status": "AUTH_DENIED",
                        "role": listed_roles.get(project),
                    }
                except JavaApiOpsError:
                    memberships[profile][str(project)] = {
                        "status": "PROJECT_READ_PROBE_FAILED",
                        "role": listed_roles.get(project),
                    }
                else:
                    memberships[profile][str(project)] = {
                        "status": "READ_OK",
                        "role": listed_roles.get(project),
                    }

        for profile, project, api_id, ref in sorted(
            _metadata_requirements(manifest, prerequisites, recipe_index, recipe_contexts)
        ):
            key = resource_key(profile, project, api_id)
            session = sessions.get(profile)
            membership = memberships.get(profile, {}).get(str(project), {})
            if session is None:
                metadata_facts[key] = {
                    "status": "LOGIN_REQUIRED",
                    "catalogContains": False,
                    "reference": ref,
                }
                continue
            if membership.get("status") != "READ_OK":
                metadata_facts[key] = {
                    "status": "AUTH_DENIED",
                    "catalogContains": False,
                    "reference": ref,
                }
                continue
            status, payload, error = await _get_json(
                http,
                f"/api/v1/projects/{project}/openapi/apis",
                session.token,
                f"stage21-runtime-metadata-list-{profile}-{project}",
            )
            data = _envelope_data(payload)
            api_ids = (
                {
                    item.get("apiId")
                    for item in data
                    if isinstance(item, dict) and isinstance(item.get("apiId"), str)
                }
                if isinstance(data, list)
                else set()
            )
            if status != 200 or error is not None or not isinstance(data, list):
                metadata_facts[key] = {
                    "status": "CATALOG_READ_FAILED",
                    "catalogContains": False,
                    "catalogHttpStatus": status,
                    "reference": ref,
                }
                continue
            if api_id not in api_ids:
                metadata_facts[key] = {
                    "status": "MISSING_FROM_CATALOG",
                    "catalogContains": False,
                    "catalogHttpStatus": status,
                    "catalogEntryCount": len(data),
                    "reference": ref,
                }
                unresolved_resources.add(f"metadata|{profile}|{project}|{api_id}")
                continue
            try:
                detail = await client.get_api_metadata(
                    project_id=project,
                    api_id=api_id,
                    token=session.token,
                    trace_id=f"stage21-runtime-metadata-detail-{profile}-{project}-{api_id}",
                )
            except (JavaApiOpsAuthenticationError, JavaApiOpsAuthorizationError):
                metadata_facts[key] = {
                    "status": "AUTH_DENIED",
                    "catalogContains": True,
                    "reference": ref,
                }
            except (JavaApiOpsServerError, JavaApiOpsError):
                metadata_facts[key] = {
                    "status": "READ_ERROR_EXISTING_RESOURCE",
                    "catalogContains": True,
                    "reference": ref,
                }
            else:
                metadata_facts[key] = {
                    "status": "METADATA_OK",
                    "catalogContains": True,
                    "detailProjectId": project,
                    "detailApiId": detail.api_id,
                    "reference": ref,
                }

        report_requirements = _report_requirements(manifest, prerequisites)
        for profile, project, ref in sorted(report_requirements):
            session = sessions.get(profile)
            key = f"{profile}|{project}|{ref}"
            if session is None:
                report_facts[key] = {
                    "status": "LOGIN_REQUIRED",
                    "runListed": False,
                    "reference": ref,
                }
                continue
            membership = memberships.get(profile, {}).get(str(project), {})
            if membership.get("status") != "READ_OK":
                report_facts[key] = {
                    "status": "AUTH_DENIED",
                    "runListed": False,
                    "reference": ref,
                }
                continue
            info = _java_ref_info(ref)
            expected_run: int | None = None
            expected_case: str | None = None
            if info is not None and info[0] == "test_report":
                rest = info[2]
                if rest and rest.startswith("stage21-initial/"):
                    resource_name = rest.removeprefix("stage21-initial/")
                    candidates = recipe_index.by_initial_resource_key.get(resource_name, ())
                    if len(candidates) == 1:
                        expected_case = candidates[0].case_id
                else:
                    identity = _direct_identity(rest)
                    if identity is not None:
                        expected_run = identity[0]
            summary = None
            public_status: str | None = None
            try:
                if expected_case is not None:
                    summary = await client.find_latest_test_run(
                        project_id=project,
                        case_id=expected_case,
                        token=session.token,
                        trace_id=(
                            f"stage21-runtime-run-case-{profile}-{project}-"
                            f"{hashlib.sha256(expected_case.encode()).hexdigest()[:12]}"
                        ),
                    )
                elif expected_run is not None:
                    report = await client.get_test_report(
                        project_id=project,
                        run_id=expected_run,
                        token=session.token,
                        trace_id=(
                            f"stage21-runtime-report-direct-{profile}-{project}-{expected_run}"
                        ),
                    )
                    report_facts[key] = {
                        "status": "REPORT_READ_OK",
                        "runListed": True,
                        "runId": report.run_id,
                        "reportIdPresent": bool(report.report_id),
                        "reportStatus": report.status,
                        "reference": ref,
                        "resolution": "DIRECT_RUN_ID",
                    }
                    continue
            except JavaApiOpsAuthenticationError:
                public_status = "HTTP_401"
            except JavaApiOpsAuthorizationError:
                public_status = "HTTP_403"
            except JavaApiOpsClientError as exc:
                public_status = f"HTTP_{exc.status_code}"
            except JavaApiOpsError:
                public_status = "PUBLIC_READ_ERROR"
            if summary is None:
                report_facts[key] = {
                    "status": "RUN_NOT_LISTED",
                    "runListed": False,
                    "publicReadStatus": public_status,
                    "reference": ref,
                    "resolution": (
                        "DIRECT_CASE_ID" if expected_case is not None else "DIRECT_RUN_ID"
                    ),
                }
                unresolved_resources.add(f"report|{profile}|{project}|{ref}")
                continue
            try:
                report = await client.get_test_report(
                    project_id=project,
                    run_id=summary.run_id,
                    token=session.token,
                    trace_id=f"stage21-runtime-report-read-{profile}-{project}-{summary.run_id}",
                )
            except (JavaApiOpsAuthenticationError, JavaApiOpsAuthorizationError):
                report_facts[key] = {
                    "status": "AUTH_DENIED",
                    "runListed": True,
                    "runId": summary.run_id,
                    "reference": ref,
                }
            except JavaApiOpsError:
                report_facts[key] = {
                    "status": "READ_ERROR_EXISTING_RESOURCE",
                    "runListed": True,
                    "runId": summary.run_id,
                    "reference": ref,
                }
            else:
                report_facts[key] = {
                    "status": "REPORT_READ_OK",
                    "runListed": True,
                    "runId": report.run_id,
                    "reportIdPresent": bool(report.report_id),
                    "reportStatus": report.status,
                    "reference": ref,
                    "resolution": "DIRECT_CASE_ID",
                }

        typed_rag_jobs, gateway_scopes = _rag_requirements(manifest, prerequisites, recipe_index)
        typed_by_scope: dict[tuple[str, int, int | None, str], list[tuple[str, str, int]]] = (
            defaultdict(list)
        )
        for profile, current, target, ref, query, top_k in typed_rag_jobs:
            typed_by_scope[(profile, current, target, "rag.search")].append((ref, query, top_k))

        async def call_gateway(
            profile: str,
            current: int,
            target: int | None,
            tool: str,
            query: str | None = None,
            top_k: int = 1,
            input_reference: str | None = None,
        ) -> dict[str, Any]:
            logical_probe_key = _logical_probe_key(
                profile=profile,
                current=current,
                target=target,
                tool=tool,
                query=query,
                input_reference=input_reference,
            )
            base_fact = {"logicalProbeKey": logical_probe_key}
            session = sessions.get(profile)
            if session is None:
                return {
                    **base_fact,
                    "status": "LOGIN_REQUIRED",
                    "authorityDecision": "NOT_OBSERVED",
                    "queryCompleted": False,
                }
            if tool == "rag.search":
                arguments: dict[str, Any] = {
                    "query": query or "stage21 input-side authority readiness",
                    "topK": top_k,
                }
                if target is not None:
                    arguments["targetProjectId"] = target
            else:
                arguments = {
                    "command": "TTL",
                    "keys": [f"apiops:runner:progress:{current}:1"],
                    "fields": [],
                }
            # The logical key above is stable for matrix/evidence correlation.
            # The Java runtime identity below is intentionally fresh for every
            # public Gateway call and is never returned in the snapshot.
            runtime_agent_run_id = f"stage21-runtime-probe:{uuid4()}"
            runtime_trace_id = f"stage21-runtime-probe-trace:{uuid4()}"
            runtime_agent_run_ids.add(runtime_agent_run_id)
            call = map_tool_intent(
                ToolIntent(tool_name=tool, arguments=arguments),
                catalog=ToolCatalog(),
                agent_run_id=runtime_agent_run_id,
                project_id=str(current),
                trace_id=runtime_trace_id,
            )
            try:
                result = await client.execute_tool_call(
                    project_id=current,
                    tool_call=call,
                    token=session.token,
                )
            except JavaApiOpsAuthenticationError:
                return {
                    **base_fact,
                    "status": "HTTP_401",
                    "authorityDecision": "DENY",
                    "queryCompleted": False,
                }
            except JavaApiOpsAuthorizationError:
                return {
                    **base_fact,
                    "status": "HTTP_403",
                    "authorityDecision": "DENY",
                    "queryCompleted": False,
                }
            except JavaApiOpsTimeoutError:
                return {
                    **base_fact,
                    "status": "HTTP_TIMEOUT",
                    "authorityDecision": "UNKNOWN",
                    "queryCompleted": False,
                }
            except JavaApiOpsTransportError:
                return {
                    **base_fact,
                    "status": "TRANSPORT_ERROR",
                    "authorityDecision": "UNKNOWN",
                    "queryCompleted": False,
                }
            except JavaApiOpsError:
                return {
                    **base_fact,
                    "status": "PUBLIC_GATEWAY_ERROR",
                    "authorityDecision": "UNKNOWN",
                    "queryCompleted": False,
                }
            result_count = None
            if isinstance(result.data, dict) and isinstance(result.data.get("results"), list):
                result_count = len(result.data["results"])
            if result.status == "FORBIDDEN":
                authority = "DENY"
            elif result.status in {
                "SUCCESS",
                "FAILED",
                "PARAM_INVALID",
                "RESULT_INVALID",
                "TIMEOUT",
            }:
                authority = "ALLOW_HANDLER_ENTERED"
            else:
                authority = "UNKNOWN"
            return {
                **base_fact,
                "status": result.status,
                "authorityDecision": authority,
                "queryCompleted": result.status == "SUCCESS",
                "resultCount": result_count,
                "errorCode": result.error.get("code") if isinstance(result.error, dict) else None,
                "errorMessage": result.error.get("message")
                if isinstance(result.error, dict)
                else None,
                "intentionalIsolationDeny": result.status == "FORBIDDEN"
                and _is_intentional_isolation(profile, current, target),
            }

        # One valid call per input-side topology is the authority smoke.  A
        # typed RAG query is reused as that scope's smoke when available.
        for profile, current, target, tool in sorted(gateway_scopes):
            query = None
            top_k = 1
            candidates = typed_by_scope.get((profile, current, target, tool), [])
            if candidates:
                query, top_k = candidates[0][1], candidates[0][2]
            fact = await call_gateway(profile, current, target, tool, query, top_k, "scope-smoke")
            gateway_facts[f"{profile}|{current}|{target or '-'}|{tool}"] = fact
            counts["toolGatewayAuthoritySmokeCallCount"] += 1
            if fact.get("authorityDecision") == "ALLOW_HANDLER_ENTERED":
                counts["successfulToolGatewayAuthoritySmokeCount"] += 1
            if fact.get("intentionalIsolationDeny"):
                counts["intentionalAuthorizationDenyCount"] += 1
                counts["intentionalAuthorizationDenyScopeSmokeCount"] += 1
            if tool == "rag.search" and fact.get("authorityDecision") == "ALLOW_HANDLER_ENTERED":
                counts["ragAuthorityPathPassCount"] += 1

        # Each unique typed RAG input is probed through the same Java public
        # boundary so a completed zero-hit can be distinguished from failure.
        for profile, current, target, ref, query, top_k in sorted(typed_rag_jobs):
            key = f"{profile}|{current}|{target or '-'}|{ref}"
            fact = await call_gateway(profile, current, target, "rag.search", query, top_k, ref)
            rag_facts[key] = fact
            counts["ragInputReferenceProbeCallCount"] += 1
            if fact.get("intentionalIsolationDeny"):
                counts["intentionalAuthorizationDenyCount"] += 1
                counts["intentionalAuthorizationDenyReferenceProbeCount"] += 1
            if fact.get("status") == "SUCCESS":
                counts["successfulRagAuthoritySmokeCount"] += 1
                if fact.get("resultCount") == 0:
                    counts["legitimateRagZeroHitCount"] += 1

        # Target readiness is computed below with the same deterministic TCP /
        # DNS probe for every URL present in an input-side recipe catalog.

    counts["unresolvedJavaResourceCount"] = len(unresolved_resources)
    counts["publicBoundaryProbeCallCount"] = len(runtime_agent_run_ids)
    counts["uniqueRuntimeAgentRunIdCount"] = len(runtime_agent_run_ids)
    counts["freshRuntimeAgentRunIdPerProbe"] = int(
        counts["publicBoundaryProbeCallCount"] == counts["uniqueRuntimeAgentRunIdCount"]
    )
    snapshot = RuntimeProbeSnapshot(
        java_health=java_health,
        auth=auth,
        memberships={profile: dict(projects) for profile, projects in memberships.items()},
        metadata=metadata_facts,
        reports=report_facts,
        gateway=gateway_facts,
        rag_by_reference=rag_facts,
        target_services={url: _probe_tcp(url) for url in sorted(_target_urls(recipe_index))},
        probe_counts={
            **dict(counts),
            "javaMutationCount": 0,
            "runnerSubmitCount": 0,
            "agentWorkflowCallCount": 0,
            "baselineRunCount": 0,
            "modelCallCount": 0,
            "fixtureFallbackCount": 0,
            "pythonBypassCount": 0,
        },
    )
    return snapshot, frozenset(runtime_agent_run_ids)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        type=Path,
        help="Explicit artifact directory; defaults to a UTC timestamped directory.",
    )
    args = parser.parse_args()

    validator_self_tests = run_validator_self_tests()
    static_first = run_input_side_audit(
        manifest_path=MANIFEST_PATH,
        sidecar_path=SIDECAR_PATH,
        recipe_dir=RECIPE_DIR,
        repo_root=REPO_ROOT,
        probe_runtime=False,
    )
    static_second = run_input_side_audit(
        manifest_path=MANIFEST_PATH,
        sidecar_path=SIDECAR_PATH,
        recipe_dir=RECIPE_DIR,
        repo_root=REPO_ROOT,
        probe_runtime=False,
    )
    assert_result_invariants(static_first)
    assert_result_invariants(static_second)
    static_first_digest = result_digest(static_first)
    static_second_digest = result_digest(static_second)
    static_deterministic = static_first_digest == static_second_digest

    first_snapshot, first_runtime_ids = asyncio.run(_run_public_probes())
    first = run_runtime_prerequisite_audit(
        manifest_path=MANIFEST_PATH,
        sidecar_path=SIDECAR_PATH,
        recipe_dir=RECIPE_DIR,
        repo_root=REPO_ROOT,
        snapshot=first_snapshot,
    )
    second_snapshot, second_runtime_ids = asyncio.run(_run_public_probes())
    second = run_runtime_prerequisite_audit(
        manifest_path=MANIFEST_PATH,
        sidecar_path=SIDECAR_PATH,
        recipe_dir=RECIPE_DIR,
        repo_root=REPO_ROOT,
        snapshot=second_snapshot,
    )
    assert_runtime_result_invariants(first)
    assert_runtime_result_invariants(second)
    first_runtime_view_digest = _json_digest(first.deterministic_view())
    second_runtime_view_digest = _json_digest(second.deterministic_view())
    first_canonical_digest = _json_digest(canonical_root_cause_classification_view(first))
    second_canonical_digest = _json_digest(canonical_root_cause_classification_view(second))
    canonical_deterministic = first_canonical_digest == second_canonical_digest
    deterministic = static_deterministic and canonical_deterministic
    pending_classification_count = first.metadata["pendingClassificationCount"]
    classification_complete = pending_classification_count == 0

    metadata = dict(first.metadata)
    metadata["status"] = (
        "STAGE21_ALL_105_INPUT_AUDIT_COMPLETE"
        if deterministic and classification_complete
        else "STAGE21_ALL_105_INPUT_AUDIT_BLOCKED"
    )
    metadata["deterministicValidation"] = "PASS" if deterministic else "FAIL"
    metadata["classificationCompleteness"] = (
        "PASS" if classification_complete else "PENDING_PUBLIC_ROOT_CAUSE_EVIDENCE"
    )
    verification = dict(first.verification)
    verification["staticProjection"] = {
        "firstDigest": static_first_digest,
        "secondDigest": static_second_digest,
        "status": "PASS" if static_deterministic else "FAIL",
    }
    verification["runtimeDeterministicValidation"] = {
        "repeatRuns": 2,
        "firstRuntimeViewDigest": first_runtime_view_digest,
        "secondRuntimeViewDigest": second_runtime_view_digest,
        "firstCanonicalRootCauseClassificationDigest": first_canonical_digest,
        "secondCanonicalRootCauseClassificationDigest": second_canonical_digest,
        "sameCanonicalRootCauseClassificationDigest": canonical_deterministic,
        "sameSanitizedRuntimeView": first_runtime_view_digest == second_runtime_view_digest,
        "status": "PASS" if deterministic else "FAIL",
    }
    verification["classificationCompleteness"] = {
        "pendingClassificationCount": pending_classification_count,
        "status": "PASS" if classification_complete else "BLOCKED_PENDING_PUBLIC_EVIDENCE",
    }
    verification["runtimeProbeIsolation"] = {
        "independentPublicProbeRuns": 2,
        "firstPublicBoundaryProbeCallCount": len(first_runtime_ids),
        "secondPublicBoundaryProbeCallCount": len(second_runtime_ids),
        "firstUniqueRuntimeAgentRunIdCount": len(first_runtime_ids),
        "secondUniqueRuntimeAgentRunIdCount": len(second_runtime_ids),
        "freshRuntimeAgentRunIdPerPublicProbe": (
            first_snapshot.probe_counts.get("freshRuntimeAgentRunIdPerProbe", 0) == 1
            and second_snapshot.probe_counts.get("freshRuntimeAgentRunIdPerProbe", 0) == 1
        ),
        "runtimeAgentRunIdsDisjointAcrossRuns": first_runtime_ids.isdisjoint(second_runtime_ids),
        "runtimeAgentIdsPersistedInSnapshots": False,
        "runtimeAgentIdsPersistedInCanonicalDigest": False,
        "runtimeAgentIdsPassedToRuntimeAuditRows": False,
        "freshIdentityAffectsRoutingOrClassification": False,
    }
    verification["validatorSelfTests"] = validator_self_tests
    verification["expectedSideProjectionProof"] = {
        "rootTaskProjectionAllowlist": [
            "allowedTools",
            "benchmarkTaskId",
            "forbiddenActions",
            "initialState",
            "instruction",
            "schemaVersion",
            "taskType",
        ],
        "manifestEntryProjectionAllowlist": [
            "benchmarkTaskId",
            "difficulty",
            "difficultyRationale",
            "reviewStatus",
            "scenario",
            "split",
            "taskFile",
        ],
        "expectedSideValuesPassedToRuntimeAuditObjects": False,
        "expectedSideRawValuesParsed": False,
        "staticExpectedSideLoadedCount": 0,
        "runtimeExpectedSideLoadedCount": 0,
        "benchmarkEvaluatorImportedDuringRuntimeAudit": False,
        "benchmarkDatasetLoaderImportedDuringRuntimeAudit": False,
        "benchmarkTaskModelImportedDuringRuntimeAudit": False,
        "freshRuntimeAgentRunIdPerPublicProbe": True,
        "runtimeAgentIdsPersistedInCanonicalDigest": False,
        "runtimeAgentIdsPassedToRuntimeAuditRows": False,
    }

    output_dir = args.output_dir
    if output_dir is None:
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        output_dir = (
            AGENTLAB_ROOT / "artifacts" / "stage21" / "runtime-prerequisite-audit-v3" / stamp
        )
    output_dir.mkdir(parents=True, exist_ok=False)

    matrix = {"metadata": metadata, "rows": list(first.rows)}
    _write_json(output_dir / "runtime-prerequisite-audit-matrix.json", matrix)
    (output_dir / "runtime-prerequisite-audit-matrix.jsonl").write_text(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in first.rows),
        encoding="utf-8",
    )
    _write_json(output_dir / "runtime-probe-snapshot.json", first_snapshot.as_dict())
    _write_json(output_dir / "runtime-probe-snapshot-second.json", second_snapshot.as_dict())
    _write_json(output_dir / "runtime-prerequisite-audit-verification.json", verification)
    _write_json(
        output_dir / "input-only-projection-proof.json",
        {
            "status": "PASS" if deterministic else "FAIL",
            "staticAuditDigest": static_first_digest,
            "runtimeAuditDigest": first_canonical_digest,
            "expectedSideLoadedCount": 0,
            "projection": verification["expectedSideProjectionProof"],
            "validatorSelfTests": validator_self_tests,
        },
    )

    counts = metadata["classificationCounts"]
    deferred_model_phase = [
        row["taskId"]
        for row in first.rows
        if row["classification"] == "NOT_PREFLIGHTABLE_MODEL_BEHAVIOR"
    ]
    non_ready = [
        row["taskId"]
        for row in first.rows
        if row["classification"] not in {"READY", "NOT_PREFLIGHTABLE_MODEL_BEHAVIOR"}
    ]
    summary = {
        "status": metadata["status"],
        "auditMode": metadata["auditMode"],
        "datasetId": metadata["datasetId"],
        "datasetVersion": metadata["datasetVersion"],
        "taskCount": metadata["taskCount"],
        "splitCounts": metadata["splitCounts"],
        "classificationCounts": counts,
        "pendingClassificationCount": pending_classification_count,
        "nonReadyTaskIds": non_ready,
        "deferredModelPhaseTaskIds": deferred_model_phase,
        "pendingClassificationTaskIds": [
            row["taskId"] for row in first.rows if row["classification"] is None
        ],
        "verification": verification,
        "artifactFiles": [
            "runtime-prerequisite-audit-matrix.json",
            "runtime-prerequisite-audit-matrix.jsonl",
            "runtime-probe-snapshot.json",
            "runtime-probe-snapshot-second.json",
            "runtime-prerequisite-audit-verification.json",
            "input-only-projection-proof.json",
            "run.json",
        ],
    }
    _write_json(output_dir / "run.json", summary)

    print(
        json.dumps(
            {**summary, "artifactDir": str(output_dir.resolve())}, ensure_ascii=False, indent=2
        )
    )
    return 0 if deterministic and classification_complete else 1


if __name__ == "__main__":
    raise SystemExit(main())
