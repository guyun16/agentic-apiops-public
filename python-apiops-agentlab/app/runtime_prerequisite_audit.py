"""Stage 21 v3 deterministic runtime-prerequisite audit.

The module consumes only the projection produced by :mod:`app.input_side_audit`
and a snapshot of observations made through Java's public HTTP boundary.  It
does not import the benchmark, evaluator, ground-truth, or model modules.

The probe snapshot is deliberately a data-only boundary: credentials and JWTs
are used by the runner, never returned by it or stored in an artifact.
"""

from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.input_side_audit import (
    ALLOWED_CLASSIFICATIONS,
    InputAuditError,
    InputEntry,
    InputManifest,
    InputTask,
    ManifestEntry,
    Prerequisite,
    Recipe,
    RecipeIndex,
    _find_forbidden_key,
    _input_ref_issues,
    _is_java_required,
    _java_ref_info,
    _path_within,
    _recommended_action,
    _required_boundaries,
    _strategy,
    assess_required_fields,
    load_prerequisites,
    load_recipe_index,
    project_input_task_file,
    project_manifest_file,
)

_DIRECT_REPORT_RE = re.compile(r"^run-(?P<run>\d+)/report-(?P<report>\d+)$")
_ROLE_RANK = {"VIEWER": 1, "EDITOR": 2, "OWNER": 3}
_ISOLATED_PROFILES = {"SAFETY_41_ISOLATED", "SAFETY_42_ISOLATED"}
_TRANSPORT_RECIPE_KINDS = {"TRANSPORT_CONNECT_FAILURE", "TRANSPORT_DNS_FAILURE"}
_LOCAL_GENERATION_REF_PREFIX = "java://runner-testcase-dsl/"
_GENERATION_CATALOG = "generation-openapi-metadata.json"


def scope_key(profile: str, project_id: int | None, target_project_id: int | None = None) -> str:
    """Return a stable, non-secret key for an auth/project topology."""

    return f"{profile}|{project_id if project_id is not None else '-'}|{target_project_id or '-'}"


def resource_key(profile: str, project_id: int, identity: str) -> str:
    return f"{profile}|{project_id}|{identity}"


@dataclass(frozen=True, slots=True)
class RuntimeProbeSnapshot:
    """Sanitized Java/public-boundary observations used for classification."""

    java_health: str
    auth: Mapping[str, Mapping[str, Any]]
    memberships: Mapping[str, Mapping[str, Mapping[str, Any]]]
    metadata: Mapping[str, Mapping[str, Any]]
    reports: Mapping[str, Mapping[str, Any]]
    gateway: Mapping[str, Mapping[str, Any]]
    rag_by_reference: Mapping[str, Mapping[str, Any]]
    target_services: Mapping[str, str]
    probe_counts: Mapping[str, int]

    def as_dict(self) -> dict[str, Any]:
        return {
            "javaHealth": self.java_health,
            "auth": {key: dict(value) for key, value in sorted(self.auth.items())},
            "memberships": {
                profile: {project: dict(value) for project, value in sorted(projects.items())}
                for profile, projects in sorted(self.memberships.items())
            },
            "metadata": {key: dict(value) for key, value in sorted(self.metadata.items())},
            "reports": {key: dict(value) for key, value in sorted(self.reports.items())},
            "gateway": {key: dict(value) for key, value in sorted(self.gateway.items())},
            "ragByReference": {
                key: dict(value) for key, value in sorted(self.rag_by_reference.items())
            },
            "targetServices": dict(sorted(self.target_services.items())),
            "probeCounts": dict(sorted(self.probe_counts.items())),
        }


@dataclass(frozen=True, slots=True)
class RuntimeAuditResult:
    metadata: dict[str, Any]
    rows: tuple[dict[str, Any], ...]
    verification: dict[str, Any]
    probe_snapshot: RuntimeProbeSnapshot

    def deterministic_view(self) -> dict[str, Any]:
        return {
            "metadata": self.metadata,
            "rows": self.rows,
            "verification": self.verification,
            "probeSnapshot": self.probe_snapshot.as_dict(),
        }


def canonical_root_cause_classification_view(result: RuntimeAuditResult) -> dict[str, Any]:
    """Return the digest input for root-cause/classification determinism.

    Public-boundary runtime identities are intentionally absent from this view.
    The view contains only the task-level classification decision and its
    deterministic root-cause explanation, so fresh Java probe identities cannot
    become routing or classification inputs.
    """

    rows = []
    for row in sorted(result.rows, key=lambda item: (item["split"], item["taskId"])):
        rows.append(
            {
                "taskId": row["taskId"],
                "split": row["split"],
                "classification": row["classification"],
                "classificationPending": list(row.get("classificationPending", [])),
                "rootCause": row["rootCause"],
            }
        )
    return {
        "taskCount": result.metadata["taskCount"],
        "splitCounts": result.metadata["splitCounts"],
        "classificationCounts": result.metadata["classificationCounts"],
        "pendingClassificationCount": result.metadata.get("pendingClassificationCount", 0),
        "rows": rows,
    }


def load_recipe_contexts(recipe_dir: Path) -> dict[str, tuple[dict[str, Any], ...]]:
    """Read input-side case context for valid catalog recipes.

    The context is keyed by typed source reference and catalog family.  It is
    never keyed by benchmark task id or instruction text.
    """

    catalog_specs = (
        ("stage21-report-runtime-recipes.json", "report_runtime", "recipeKind"),
        ("stage21-remaining-runner-recipes.json", "runner_runtime", "recipeFamily"),
    )
    result: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for filename, family, family_field in catalog_specs:
        path = recipe_dir / filename
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(payload, dict) or not isinstance(payload.get("recipes"), list):
            continue
        for raw in payload["recipes"]:
            if not isinstance(raw, dict) or _find_forbidden_key(raw) is not None:
                continue
            source = raw.get("sourceReference")
            testcase = raw.get("testCase")
            if not isinstance(source, str) or not isinstance(testcase, dict):
                continue
            case_id = testcase.get("caseId")
            family_value = raw.get(family_field)
            if not isinstance(case_id, str) or family_value is None:
                continue
            result[f"{family}|{source}|{case_id}"].append(
                {
                    "family": family,
                    "sourceReference": source,
                    "caseId": case_id,
                    "projectId": testcase.get("projectId"),
                    "apiId": testcase.get("apiId"),
                    "recipeKind": family_value,
                }
            )
    return {key: tuple(values) for key, values in result.items()}


def _empty_task(task_id: str, issue: str) -> InputTask:
    return InputTask(
        task_id,
        "<unreadable>",
        0,
        "",
        (),
        (),
        None,
        (issue,),
        # ProjectionTrace is intentionally constructed through the public
        # class only when an input file cannot be projected.
        __import__("app.input_side_audit", fromlist=["ProjectionTrace"]).ProjectionTrace(),
    )


def _load_projected_tasks(manifest_path: Path, manifest: InputManifest) -> dict[str, InputTask]:
    tasks: dict[str, InputTask] = {}
    dataset_root = manifest_path.parent.resolve()
    for entry in manifest.tasks:
        path = (manifest_path.parent / entry.task_file).resolve()
        if not _path_within(path, dataset_root):
            tasks[entry.task_id] = _empty_task(entry.task_id, "taskFile:path_escapes_dataset_root")
        elif not path.is_file():
            tasks[entry.task_id] = _empty_task(entry.task_id, "taskFile:file_missing")
        else:
            try:
                tasks[entry.task_id] = project_input_task_file(path)
            except InputAuditError as exc:
                tasks[entry.task_id] = _empty_task(
                    entry.task_id, f"taskFile:input_projection_failed:{type(exc).__name__}"
                )
    return tasks


def _local_generation_catalog_status(repo_root: Path, recipe_dir: Path) -> tuple[str, str | None]:
    path = recipe_dir / _GENERATION_CATALOG
    if not path.is_file():
        return "MISSING", "approved generation metadata catalog is absent"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return "INVALID", "approved generation metadata catalog is not valid JSON"
    forbidden = _find_forbidden_key(payload)
    if forbidden is not None:
        return "INVALID", f"generation metadata catalog contains forbidden key at {forbidden}"
    if not isinstance(payload, dict):
        return "INVALID", "approved generation metadata catalog must be an object"
    return "READY", None


def _direct_report_identity(rest: str | None) -> tuple[int, int] | None:
    if not isinstance(rest, str):
        return None
    match = _DIRECT_REPORT_RE.fullmatch(rest)
    if match is None:
        return None
    return int(match.group("run")), int(match.group("report"))


def _recipe_candidates(recipe_index: RecipeIndex, source: str, family: str) -> tuple[Recipe, ...]:
    return tuple(
        recipe for recipe in recipe_index.by_source.get(source, ()) if recipe.family == family
    )


def _runner_family(task: InputTask, entry: InputEntry) -> str:
    if task.task_type == "FAILURE_DIAGNOSIS" and entry.key == "testReport":
        return "report_runtime"
    return "runner_runtime"


def _recipe_context(
    recipe: Recipe, recipe_contexts: Mapping[str, tuple[dict[str, Any], ...]]
) -> dict[str, Any] | None:
    if recipe.case_id is None:
        return None
    values = recipe_contexts.get(f"{recipe.family}|{recipe.source_reference}|{recipe.case_id}", ())
    return dict(values[0]) if len(values) == 1 else None


def _resolve_input_resources(
    task: InputTask,
    prerequisite: Prerequisite,
    recipe_index: RecipeIndex,
    recipe_contexts: Mapping[str, tuple[dict[str, Any], ...]],
    repo_root: Path,
    recipe_dir: Path,
) -> dict[str, Any]:
    """Resolve typed input references without task-id or instruction routing."""

    result: dict[str, Any] = {
        "resolution": "NOT_REQUIRED",
        "references": [],
        "recipes": [],
    }
    mapping: list[str] = []
    recipe_gaps: list[str] = []
    local_missing: list[str] = []
    java_resource_issues: list[str] = []
    target_urls: list[str] = []
    metadata_refs: list[tuple[str, int, str]] = []
    report_refs: list[tuple[str, int, int | None, str]] = []
    rag_refs: list[str] = []
    model_required = False
    generation_catalog_status, generation_catalog_issue = _local_generation_catalog_status(
        repo_root, recipe_dir
    )

    java_entries = [entry for entry in task.entries if entry.kind == "JAVA_RESOURCE" and entry.ref]
    if java_entries:
        result["resolution"] = "RESOLVED"

    for entry in java_entries:
        ref = entry.ref
        assert ref is not None
        result["references"].append(ref)
        info = _java_ref_info(ref)
        if info is None:
            # The structural input validator owns the unknown-reference
            # contract finding; this function remains fail-closed.
            mapping.append(f"unknown_typed_reference_not_resolvable={ref}")
            continue
        ref_kind, ref_project, ref_rest = info
        if ref_kind == "metadata":
            # ``metadata`` uses the ``api`` capture group in the shared
            # input-reference grammar, while the other Java references use
            # ``rest``.  Recover the typed identity from the validated URI
            # itself instead of treating the legal URI as malformed.
            api_id = ref.rsplit("/", 1)[-1]
            if ref_project is None or not api_id:
                java_resource_issues.append(f"metadata_reference_malformed={ref}")
            else:
                metadata_refs.append((ref, ref_project, api_id))
                result["recipes"].append(
                    {
                        "sourceReference": ref,
                        "kind": "PUBLIC_METADATA_REFERENCE",
                        "projectId": ref_project,
                        "apiId": api_id,
                        "valid": True,
                    }
                )
            continue
        if ref_kind == "test_report":
            if ref_rest and ref_rest.startswith("stage21-initial/"):
                resource_name = ref_rest.removeprefix("stage21-initial/")
                candidates = recipe_index.by_initial_resource_key.get(resource_name, ())
                if len(candidates) != 1:
                    recipe_gaps.append(
                        f"initial_report_recipe_count={len(candidates)}:{resource_name}"
                    )
                elif candidates[0].issues:
                    recipe_gaps.extend(
                        f"initial_report_recipe:{issue}" for issue in candidates[0].issues
                    )
                else:
                    recipe = candidates[0]
                    result["recipes"].append(
                        {
                            "sourceReference": ref,
                            "kind": recipe.kind,
                            "caseId": recipe.case_id,
                            "catalog": recipe.catalog_path,
                            "projectId": ref_project,
                            "valid": True,
                        }
                    )
                    report_refs.append((ref, ref_project or 0, None, "INITIAL_REPORT"))
            else:
                identity = _direct_report_identity(ref_rest)
                if identity is None:
                    java_resource_issues.append(f"direct_report_reference_malformed={ref}")
                else:
                    run_id, report_id = identity
                    result["recipes"].append(
                        {
                            "sourceReference": ref,
                            "kind": "PUBLIC_REPORT_REFERENCE",
                            "projectId": ref_project,
                            "runId": run_id,
                            "reportId": report_id,
                            "valid": True,
                        }
                    )
                    report_refs.append((ref, ref_project or 0, run_id, "DIRECT_REPORT"))
            continue
        if ref_kind in {"runner_testcase", "runner_unit"}:
            # For generation tasks, this typed ref is an approved symbolic
            # local input.  It is not a Java runtime recipe and is not routed
            # by task id.
            if (
                task.task_type == "TESTCASE_GENERATION"
                and prerequisite.resource_setup_type == "BENCHMARK_LOCAL_INPUT"
            ):
                result["recipes"].append(
                    {
                        "sourceReference": ref,
                        "kind": "LOCAL_GENERATION_INPUT",
                        "catalog": _GENERATION_CATALOG,
                        "valid": generation_catalog_status == "READY",
                    }
                )
                if generation_catalog_issue:
                    local_missing.append(generation_catalog_issue)
                continue

            family = _runner_family(task, entry)
            candidates = _recipe_candidates(recipe_index, ref, family)
            if len(candidates) == 0:
                if task.task_type == "E2E_APIOPS" and (
                    "RUNTIME_RECIPE_GAP" not in prerequisite.contract_gaps
                ):
                    model_required = True
                    result["resolution"] = "MODEL_GENERATED"
                    result["recipes"].append(
                        {
                            "sourceReference": ref,
                            "kind": "MODEL_GENERATED_TESTCASE_REQUIRED",
                            "family": family,
                            "valid": False,
                        }
                    )
                else:
                    recipe_gaps.append(f"{family}_recipe_missing={ref}")
                continue
            if len(candidates) > 1:
                mapping.append(
                    f"typed_source_reference_ambiguous={ref}:family={family}:"
                    f"candidate_count={len(candidates)}"
                )
                result["resolution"] = "AMBIGUOUS"
                result["recipes"].extend(
                    {
                        **candidate.as_dict(),
                        "selection": "ambiguous_same_family",
                    }
                    for candidate in candidates
                )
                continue
            recipe = candidates[0]
            if recipe.issues:
                recipe_gaps.extend(f"{family}_recipe:{issue}" for issue in recipe.issues)
                continue
            context = _recipe_context(recipe, recipe_contexts)
            recipe_view = recipe.as_dict()
            if context is not None:
                recipe_view["testCaseProjectId"] = context.get("projectId")
                recipe_view["testCaseApiId"] = context.get("apiId")
                if (
                    isinstance(context.get("projectId"), int)
                    and prerequisite.current_project_id is not None
                    and context["projectId"] != prerequisite.current_project_id
                    and task.task_type == "E2E_APIOPS"
                ):
                    # A valid catalog entry exists, but the only family-
                    # compatible entry is in another project scope.  A
                    # resolver that ignores the project context would map the
                    # typed source incorrectly; do not silently use it.
                    mapping.append(
                        f"recipe_project_scope_mismatch={ref}:recipeProject="
                        f"{context['projectId']}:currentProject={prerequisite.current_project_id}"
                    )
            result["recipes"].append(recipe_view)
            if recipe.base_url:
                target_urls.append(recipe.base_url)
            continue
        if ref_kind == "rag":
            candidates = tuple(
                candidate
                for candidate in recipe_index.by_source.get(ref, ())
                if candidate.family == "rag_runtime"
            )
            rag_refs.append(ref)
            if len(candidates) == 0:
                recipe_gaps.append(f"rag_recipe_missing={ref}")
            elif len(candidates) > 1:
                mapping.append(
                    f"typed_source_reference_ambiguous={ref}:family=rag_runtime:"
                    f"candidate_count={len(candidates)}"
                )
                result["resolution"] = "AMBIGUOUS"
            elif candidates[0].issues:
                recipe_gaps.extend(f"rag_recipe:{issue}" for issue in candidates[0].issues)
            else:
                result["recipes"].append(candidates[0].as_dict())
            continue
        if ref_kind == "tool_gateway":
            result["recipes"].append(
                {
                    "sourceReference": ref,
                    "kind": "TOOL_GATEWAY_POLICY_REFERENCE",
                    "valid": True,
                }
            )

    # A Java submit without a typed runner recipe is model-generated input
    # when the E2E task has no explicit runtime-recipe declaration.  This is a
    # strategy boundary, not a missing resource and never triggers a model.
    if (
        task.task_type == "E2E_APIOPS"
        and "RUNNER_SUBMIT" in prerequisite.required_operations
        and not any(
            item.get("family") in {"runner_runtime", "report_runtime"} for item in result["recipes"]
        )
        and not recipe_gaps
        and not mapping
    ):
        model_required = True
        result["resolution"] = "MODEL_GENERATED"
        result["recipes"].append(
            {
                "kind": "MODEL_GENERATED_RUNNER_INPUT_REQUIRED",
                "valid": False,
            }
        )

    # Historical sidecar notes are retained as evidence by the caller, but
    # they are not findings when the typed resolver proves a valid equivalent.
    result["resolution"] = (
        result["resolution"]
        if result["resolution"] != "RESOLVED"
        else ("MISSING_OR_INVALID" if recipe_gaps else "RESOLVED")
    )
    return {
        "runtimeRecipe": result,
        "mappingIssues": sorted(set(mapping)),
        "recipeGaps": sorted(set(recipe_gaps)),
        "localMissing": sorted(set(local_missing)),
        "javaResourceIssues": sorted(set(java_resource_issues)),
        "targetUrls": sorted(set(target_urls)),
        "metadataRefs": metadata_refs,
        "reportRefs": report_refs,
        "ragRefs": sorted(set(rag_refs)),
        "modelRequired": model_required,
    }


def _scope_contract_issues(task: InputTask, prerequisite: Prerequisite) -> list[str]:
    issues: list[str] = []
    requiredness = assess_required_fields(task, prerequisite)
    target = requiredness["targetProjectId"]
    if target["required"] and not target["provided"]:
        issues.append("targetProjectId_semantically_required_but_not_provided")
    literals = task.literals
    for key in ("currentProjectId", "current_project_id"):
        if (
            key in literals
            and prerequisite.current_project_id is not None
            and literals[key] != prerequisite.current_project_id
        ):
            issues.append(f"{key}_does_not_match_sidecar_currentProjectId")
    known_scope = {
        value
        for value in (
            prerequisite.current_project_id,
            prerequisite.target_project_id,
            prerequisite.resource_project_id,
        )
        if value is not None
    }
    for entry in task.entries:
        if entry.kind != "JAVA_RESOURCE" or not entry.ref:
            continue
        info = _java_ref_info(entry.ref)
        if info is not None and info[1] is not None and known_scope:
            if info[1] not in known_scope:
                issues.append(f"typed_reference_project_outside_declared_scope={info[1]}")
    return sorted(set(issues))


def _authority_isolation_expected(prerequisite: Prerequisite) -> bool:
    return (
        prerequisite.auth_profile in _ISOLATED_PROFILES
        and prerequisite.current_project_id is not None
        and prerequisite.target_project_id is not None
        and prerequisite.current_project_id != prerequisite.target_project_id
    )


def _role_satisfies(actual: str | None, minimum: str | None) -> bool:
    if minimum is None:
        return True
    return _ROLE_RANK.get(actual or "", 0) >= _ROLE_RANK.get(minimum, 99)


def _auth_observation(
    prerequisite: Prerequisite,
    snapshot: RuntimeProbeSnapshot,
    resource_projects: Iterable[int],
) -> tuple[str, list[str], bool]:
    if not _is_java_required(prerequisite):
        return "NOT_REQUIRED_NO_JAVA_ACCESS", [], False
    issues: list[str] = []
    auth = snapshot.auth.get(prerequisite.auth_profile, {})
    if auth.get("status") != "LOGIN_OK":
        issues.append(
            "declared "
            f"{prerequisite.auth_profile} login is not ready "
            f"({auth.get('status', 'UNOBSERVED')})"
        )
    projects = {
        project
        for project in (
            prerequisite.current_project_id,
            prerequisite.target_project_id,
            prerequisite.resource_project_id,
            *resource_projects,
        )
        if project is not None
    }
    membership = snapshot.memberships.get(prerequisite.auth_profile, {})
    current = prerequisite.current_project_id
    if current is not None:
        current_observation = membership.get(str(current), {})
        if current_observation.get("status") != "READ_OK":
            issues.append(
                "declared "
                f"{prerequisite.auth_profile} lacks readable membership for "
                f"current project {current}"
            )
        elif not _role_satisfies(
            current_observation.get("role"), prerequisite.minimum_project_role
        ):
            issues.append(
                f"declared {prerequisite.auth_profile} role {current_observation.get('role')} "
                f"does not satisfy minimum {prerequisite.minimum_project_role} on project {current}"
            )
    # A resource project is a required read scope unless it is the declared
    # isolated target.  Isolation denial is checked by the Gateway smoke, not
    # misreported as missing membership.
    for project in sorted(projects - ({current} if current is not None else set())):
        if (
            _authority_isolation_expected(prerequisite)
            and project == prerequisite.target_project_id
        ):
            continue
        observation = membership.get(str(project), {})
        if observation.get("status") != "READ_OK":
            issues.append(
                f"declared {prerequisite.auth_profile} cannot read required project {project}"
            )
    if issues:
        return "AUTH_NOT_READY:" + ";".join(sorted(set(issues))), issues, True
    return (
        f"AUTH_READY:login=OK;currentProject={current};"
        f"minimumRole={prerequisite.minimum_project_role or 'UNSPECIFIED'}",
        [],
        False,
    )


def _gateway_fact(
    prerequisite: Prerequisite,
    snapshot: RuntimeProbeSnapshot,
    tool: str,
    reference: str | None = None,
) -> Mapping[str, Any] | None:
    current = prerequisite.current_project_id
    if current is None:
        return None
    if reference is not None:
        fact = snapshot.rag_by_reference.get(
            f"{prerequisite.auth_profile}|{current}|"
            f"{prerequisite.target_project_id or '-'}|{reference}"
        )
        if fact is not None:
            return fact
    return snapshot.gateway.get(
        f"{prerequisite.auth_profile}|{current}|{prerequisite.target_project_id or '-'}|{tool}",
        None,
    )


def _runtime_findings(
    task: InputTask,
    prerequisite: Prerequisite,
    resolved: Mapping[str, Any],
    snapshot: RuntimeProbeSnapshot,
) -> tuple[
    list[str],
    list[str],
    list[str],
    list[str],
    list[str],
    list[dict[str, str]],
    dict[str, Any],
]:
    """Return deterministic findings and public probe observations.

    A public RAG handler failure is deliberately kept pending when the public
    result does not distinguish a missing corpus, a typed mapping error, a
    missing recipe, or a Java handler defect.  It must not be guessed into a
    frozen blocker category from a generic ``FAILED`` result.
    """

    resource_issues: list[str] = []
    java_issues: list[str] = []
    auth_issues: list[str] = []
    pending_issues: list[str] = []
    zero_hit_refs: list[str] = []
    probe_evidence: list[dict[str, str]] = []
    statuses: dict[str, Any] = {
        "targetServices": {},
        "metadata": [],
        "reports": [],
        "gateway": [],
        "rag": [],
    }
    java_required = _is_java_required(prerequisite)
    resource_projects: list[int] = []

    for _, project, _ in resolved["metadataRefs"]:
        resource_projects.append(project)
    for _, project, _, _ in resolved["reportRefs"]:
        resource_projects.append(project)
    for recipe in resolved["runtimeRecipe"].get("recipes", []):
        if isinstance(recipe.get("testCaseProjectId"), int):
            resource_projects.append(recipe["testCaseProjectId"])

    auth_status, auth_findings, auth_not_ready = _auth_observation(
        prerequisite, snapshot, resource_projects
    )
    if auth_not_ready:
        auth_issues.extend(auth_findings)
    if java_required and snapshot.java_health != "HEALTHY":
        resource_issues.append(f"Java public boundary health is not UP ({snapshot.java_health})")
    if java_required:
        probe_evidence.append(
            {
                "kind": "JAVA_AUTH_PROJECT_PROBE",
                "source": "Java public login + GET /api/v1/projects/{projectId}",
                "rootCause": auth_status,
            }
        )

    for ref, project, api_id in resolved["metadataRefs"]:
        fact = snapshot.metadata.get(resource_key(prerequisite.auth_profile, project, api_id), {})
        statuses["metadata"].append({"reference": ref, **fact})
        status = fact.get("status")
        if status in {"AUTH_DENIED", "LOGIN_REQUIRED"}:
            auth_issues.append(f"metadata read is unauthorized for {project}/{api_id}")
        elif status == "READ_ERROR_EXISTING_RESOURCE":
            java_issues.append(
                f"metadata catalog contains {project}/{api_id}, but its public detail read failed"
            )
        elif status not in {"METADATA_OK"}:
            resource_issues.append(
                f"Java metadata identity {project}/{api_id} is absent or not readable; "
                f"public catalog evidence={status or 'UNOBSERVED'}"
            )
        if fact:
            probe_evidence.append(
                {
                    "kind": "JAVA_METADATA_PROBE",
                    "source": (
                        f"GET /api/v1/projects/{project}/openapi/apis + "
                        f"typed detail {api_id}"
                    ),
                    "rootCause": (
                        f"input typed metadata reference {ref}; "
                        f"catalogContains={fact.get('catalogContains')}; status={status}"
                    ),
                }
            )

    for ref, project, run_id, report_kind in resolved["reportRefs"]:
        fact = snapshot.reports.get(f"{prerequisite.auth_profile}|{project}|{ref}", {})
        statuses["reports"].append({"reference": ref, **fact})
        status = fact.get("status")
        if status in {"AUTH_DENIED", "LOGIN_REQUIRED"}:
            auth_issues.append(f"report read is unauthorized for {ref}")
        elif status == "READ_ERROR_EXISTING_RESOURCE":
            java_issues.append(
                f"Java run {run_id or 'symbolic'} is listed, but public TestReport read failed"
            )
        elif status not in {"REPORT_READ_OK"}:
            if report_kind == "DIRECT_REPORT" and fact.get("runListed") is False:
                resource_issues.append(
                    f"typed direct report {ref} is valid but its run is absent from the "
                    "Java project run-summary catalog"
                )
            else:
                resource_issues.append(
                    f"typed report {ref} did not resolve to a readable Java-owned report "
                    f"(catalogEvidence={status or 'UNOBSERVED'})"
                )
        if fact:
            probe_evidence.append(
                {
                    "kind": "JAVA_REPORT_PROBE",
                    "source": "GET /api/v1/projects/{projectId}/test-runs + public report read",
                    "rootCause": (
                        f"input typed report reference {ref}; runListed={fact.get('runListed')}; "
                        f"status={status}"
                    ),
                }
            )

    for url in resolved["targetUrls"]:
        target_status = snapshot.target_services.get(url, "UNOBSERVED")
        statuses["targetServices"][url] = target_status
        recipe_kinds = {
            recipe.get("kind")
            for recipe in resolved["runtimeRecipe"].get("recipes", [])
            if recipe.get("baseUrl") == url
        }
        if recipe_kinds & _TRANSPORT_RECIPE_KINDS:
            probe_evidence.append(
                {
                    "kind": "TARGET_SERVICE_PROBE",
                    "source": "TCP/DNS prerequisite probe derived from typed recipe",
                    "rootCause": (
                        f"{url}={target_status}; unreachable target is the declared "
                        "transport-failure scenario, so it is intentionally not a resource gap"
                    ),
                }
            )
        elif target_status != "TCP_REACHABLE":
            resource_issues.append(
                f"typed runtime recipe target {url} is not reachable/resolvable "
                f"({target_status}); this recipe kind requires a live target"
            )
            probe_evidence.append(
                {
                    "kind": "TARGET_SERVICE_PROBE",
                    "source": "TCP/DNS prerequisite probe derived from typed recipe",
                    "rootCause": (
                        f"{url}={target_status}; recipe kind is not an intentional "
                        "transport-failure scenario"
                    ),
                }
            )

    needs_rag = "RAG_SEARCH" in prerequisite.required_operations
    needs_tool = "TOOL_CALL" in prerequisite.required_operations
    if needs_rag:
        ref = resolved["ragRefs"][0] if resolved["ragRefs"] else None
        fact = _gateway_fact(prerequisite, snapshot, "rag.search", ref)
        if fact is None:
            if not auth_not_ready:
                pending_issues.append(
                    "RAG public authority/handler evidence was not observed after auth readiness; "
                    "resource versus handler root cause is unresolved"
                )
        else:
            statuses["rag"].append(dict(fact))
            status = fact.get("status")
            if fact.get("intentionalIsolationDeny"):
                probe_evidence.append(
                    {
                        "kind": "TOOL_GATEWAY_AUTHORITY_PROBE",
                        "source": "Java public Tool Gateway rag.search",
                        "rootCause": (
                            f"declared {prerequisite.auth_profile} correctly denied the "
                            f"cross-project target {prerequisite.target_project_id}; "
                            "isolated authority topology is ready"
                        ),
                    }
                )
            elif status == "SUCCESS":
                result_count = fact.get("resultCount")
                if result_count == 0 and ref is not None:
                    zero_hit_refs.append(ref)
                probe_evidence.append(
                    {
                        "kind": "RAG_AUTHORITY_PROBE",
                        "source": "Java public Tool Gateway rag.search",
                        "rootCause": (
                            f"authenticated project scope completed the typed RAG query; "
                            f"resultCount={result_count}; zero-hit is a valid completed outcome"
                        ),
                    }
                )
            elif status == "FORBIDDEN":
                if auth_not_ready:
                    auth_issues.append("Java Gateway denied a non-isolated declared RAG scope")
                else:
                    pending_issues.append(
                        "Java Gateway returned FORBIDDEN after declared profile/login/project "
                        "readiness; the public result does not identify a missing permission "
                        "versus Gateway state"
                    )
            else:
                pending_issues.append(
                    "authenticated Java Gateway entered the RAG handler, but the public "
                    "ToolResult does not identify corpus absence, typed mapping, recipe, or "
                    f"Java handler root cause (status={status or 'UNOBSERVED'}); this is not "
                    "a zero-hit"
                )
                probe_evidence.append(
                    {
                        "kind": "RAG_RUNTIME_PROBE",
                        "source": (
                            "Java public Tool Gateway rag.search + "
                            "Java RagRetriever contract"
                        ),
                        "rootCause": (
                            f"authorityDecision={fact.get('authorityDecision')}; "
                            f"toolStatus={status}; "
                            f"queryCompleted={fact.get('queryCompleted', False)}; "
                            "public evidence ends at handler-level ToolResult and cannot "
                            "distinguish corpus, mapping, recipe, or Java handler cause"
                        ),
                    }
                )
    elif needs_tool:
        tool = "redis.read" if "redis.read" in task.allowed_tools else None
        if tool is not None:
            fact = _gateway_fact(prerequisite, snapshot, tool)
            if fact is None:
                if not auth_not_ready:
                    pending_issues.append(
                        f"{tool} public authority/handler evidence was not observed after "
                        "auth readiness; runtime root cause is unresolved"
                    )
            else:
                statuses["gateway"].append(dict(fact))
                if fact.get("intentionalIsolationDeny"):
                    probe_evidence.append(
                        {
                            "kind": "TOOL_GATEWAY_AUTHORITY_PROBE",
                            "source": f"Java public Tool Gateway {tool}",
                            "rootCause": (
                                f"declared {prerequisite.auth_profile} correctly denied the "
                                f"cross-project target {prerequisite.target_project_id}; "
                                "isolated authority topology is ready"
                            ),
                        }
                    )
                elif fact.get("status") == "FORBIDDEN":
                    if auth_not_ready:
                        auth_issues.append(f"Java Gateway denied declared {tool} scope")
                    else:
                        pending_issues.append(
                            f"Java Gateway returned FORBIDDEN for {tool} after declared "
                            "profile/login/project readiness; public evidence does not identify "
                            "a missing permission versus Gateway state"
                        )
                elif fact.get("status") != "SUCCESS":
                    pending_issues.append(
                        f"Java Gateway authorized {tool}, but the public ToolResult does not "
                        "identify the runtime root cause "
                        f"(status={fact.get('status') or 'UNOBSERVED'})"
                    )
                else:
                    probe_evidence.append(
                        {
                            "kind": "TOOL_GATEWAY_AUTHORITY_PROBE",
                            "source": "Java public Tool Gateway redis.read",
                            "rootCause": (
                                "declared NORMAL project scope passed Gateway authorization "
                                "and completed a bounded read"
                            ),
                        }
                    )

    return (
        resource_issues,
        java_issues,
        auth_issues,
        pending_issues,
        zero_hit_refs,
        probe_evidence,
        statuses,
    )


def _contract_issues(
    manifest_entry: ManifestEntry,
    task: InputTask,
    prerequisite: Prerequisite,
    repo_root: Path,
) -> tuple[list[str], list[str], list[str]]:
    contract = list(manifest_entry.contract_issues) + list(task.contract_issues)
    contract.extend(prerequisite.contract_issues)
    if task.task_id != manifest_entry.task_id:
        contract.append("task_file_benchmarkTaskId_does_not_match_manifest")
    if prerequisite.task_id != manifest_entry.task_id:
        contract.append("sidecar_benchmarkTaskId_does_not_match_manifest")
    contract.extend(_scope_contract_issues(task, prerequisite))
    ref_contract, ref_mapping, local_missing = _input_ref_issues(task, prerequisite, repo_root)
    contract.extend(ref_contract)
    return sorted(set(contract)), sorted(set(ref_mapping)), sorted(set(local_missing))


def _status(value: str, issues: Iterable[str]) -> str:
    values = sorted(set(issue for issue in issues if issue))
    return value if not values else value + ":" + ";".join(values)


def _root_cause(
    classification: str,
    *,
    contract_issues: Iterable[str],
    strategy_issues: Iterable[str],
    mapping_issues: Iterable[str],
    recipe_gaps: Iterable[str],
    auth_issues: Iterable[str],
    java_issues: Iterable[str],
    local_missing: Iterable[str],
    resource_issues: Iterable[str],
    model_required: bool,
    evidence: Iterable[Mapping[str, str]],
) -> str:
    """Select root-cause evidence by classification, never by list position."""

    issue_groups = {
        "TASK_INPUT_CONTRACT_GAP": contract_issues,
        "STRATEGY_INPUT_CONTRACT_GAP": strategy_issues,
        "RESOURCE_MAPPING_BUG": mapping_issues,
        "RUNTIME_RECIPE_GAP": recipe_gaps,
        "AUTH_PREREQUISITE_GAP": auth_issues,
        "REAL_JAVA_BUG": java_issues,
        "RUNTIME_RESOURCE_MISSING": (*local_missing, *resource_issues),
    }
    selected = list(issue_groups.get(classification, ()))
    if classification == "NOT_PREFLIGHTABLE_MODEL_BEHAVIOR" and model_required:
        selected.append(
            "input-side execution plan requires model-generated behavior; model phase was not run"
        )
    if selected:
        return ";".join(dict.fromkeys(str(value) for value in selected if value))
    if classification == "READY":
        return (
            "all applicable input contract, typed mapping, recipe, auth, authority, "
            "resource, and target prerequisites passed"
        )
    for item in evidence:
        value = item.get("rootCause")
        if value:
            return value
    return "no deterministic root-cause evidence was recorded"


def _audit_one(
    manifest_entry: ManifestEntry,
    task: InputTask,
    prerequisite: Prerequisite,
    *,
    recipe_index: RecipeIndex,
    recipe_contexts: Mapping[str, tuple[dict[str, Any], ...]],
    repo_root: Path,
    recipe_dir: Path,
    snapshot: RuntimeProbeSnapshot,
) -> dict[str, Any]:
    contract_issues, ref_mapping, local_missing = _contract_issues(
        manifest_entry, task, prerequisite, repo_root
    )
    strategy, strategy_issues = _strategy(task)
    resolved = _resolve_input_resources(
        task,
        prerequisite,
        recipe_index,
        recipe_contexts,
        repo_root,
        recipe_dir,
    )
    contract_issues.extend(resolved["javaResourceIssues"])
    mapping_issues = list(ref_mapping) + list(resolved["mappingIssues"])
    recipe_gaps = list(resolved["recipeGaps"])
    local_missing = sorted(set(local_missing + resolved["localMissing"]))
    (
        resource_issues,
        java_issues,
        auth_issues,
        pending_issues,
        zero_hit_refs,
        probe_evidence,
        statuses,
    ) = _runtime_findings(task, prerequisite, resolved, snapshot)
    java_required = _is_java_required(prerequisite)
    model_required = bool(resolved["modelRequired"])
    required_boundaries = _required_boundaries(prerequisite.required_operations)

    if contract_issues:
        classification = "TASK_INPUT_CONTRACT_GAP"
    elif strategy_issues:
        classification = "STRATEGY_INPUT_CONTRACT_GAP"
    elif mapping_issues:
        classification = "RESOURCE_MAPPING_BUG"
    elif recipe_gaps:
        classification = "RUNTIME_RECIPE_GAP"
    elif auth_issues:
        classification = "AUTH_PREREQUISITE_GAP"
    elif java_issues:
        classification = "REAL_JAVA_BUG"
    elif local_missing or resource_issues:
        classification = "RUNTIME_RESOURCE_MISSING"
    elif model_required:
        classification = "NOT_PREFLIGHTABLE_MODEL_BEHAVIOR"
    elif pending_issues:
        classification = None
    else:
        classification = "READY"

    if contract_issues:
        resource_status = "INPUT_CONTRACT_INVALID"
    elif mapping_issues:
        resource_status = "TYPED_RESOLVER_MAPPING_NOT_UNIQUE_OR_SCOPE_SAFE"
    elif recipe_gaps:
        resource_status = "RUNTIME_RECIPE_UNRESOLVED"
    elif local_missing or resource_issues:
        resource_status = "RUNTIME_RESOURCE_NOT_READY"
    elif java_issues:
        resource_status = "JAVA_PUBLIC_BOUNDARY_INCONSISTENT"
    elif pending_issues:
        resource_status = "RUNTIME_HANDLER_ROOT_CAUSE_UNRESOLVED"
    elif java_required:
        resource_status = "JAVA_PUBLIC_RESOURCES_RESOLVED"
    else:
        resource_status = "LOCAL_INPUT_READY"

    if strategy_issues:
        strategy_status = "INVALID"
    elif model_required:
        strategy_status = "MODEL_PHASE_REQUIRED_NOT_RUN"
    elif task.task_type == "TESTCASE_GENERATION":
        strategy_status = "APPLICABLE"
    else:
        strategy_status = "INPUT_APPLICABLE"

    auth_status, _, _ = _auth_observation(
        prerequisite,
        snapshot,
        [project for _, project, _ in resolved["metadataRefs"]]
        + [project for _, project, _, _ in resolved["reportRefs"]],
    )
    if not java_required:
        auth_status = "NOT_REQUIRED_NO_JAVA_ACCESS"
    elif auth_issues:
        auth_status = "AUTH_NOT_READY:" + ";".join(sorted(set(auth_issues)))
    elif _authority_isolation_expected(prerequisite):
        auth_status += ";crossProjectTarget=INTENTIONAL_ISOLATION_DENY_VERIFIED"

    if local_missing:
        runtime_status = "LOCAL_INPUT_NOT_READY"
    elif resource_issues:
        runtime_status = "RUNTIME_PREREQUISITE_NOT_READY"
    elif java_issues:
        runtime_status = "JAVA_PUBLIC_BOUNDARY_BEHAVIOR_INCONSISTENT"
    elif auth_issues:
        runtime_status = "AUTHORITY_NOT_READY"
    elif model_required:
        runtime_status = "MODEL_GENERATION_REQUIRED_NOT_RUN"
    elif pending_issues:
        runtime_status = "RUNTIME_ROOT_CAUSE_UNRESOLVED"
    elif java_required:
        runtime_status = "JAVA_RUNTIME_PREREQUISITES_READY"
    else:
        runtime_status = "LOCAL_RUNTIME_PREREQUISITES_READY"

    evidence: list[dict[str, str]] = [
        {
            "kind": "INPUT_ONLY_PROJECTION",
            "source": "Stage21 lexical task/manifest projection",
            "rootCause": (
                "Runtime classification received only input schema, instruction digest, "
                "typed initialState entries, allowedTools, forbiddenActions, and sidecar fields."
            ),
        },
        {
            "kind": "DECLARED_EXECUTION_REQUIREMENT",
            "source": "stage21-execution-prerequisites.json",
            "rootCause": (
                f"authProfile={prerequisite.auth_profile}; currentProjectId="
                f"{prerequisite.current_project_id}; "
                f"targetProjectId={prerequisite.target_project_id}; "
                f"resourceSetupType={prerequisite.resource_setup_type}; "
                f"requiredOperations={','.join(prerequisite.required_operations)}"
            ),
        },
    ]
    if contract_issues:
        evidence.append(
            {
                "kind": "INPUT_CONTRACT",
                "source": "projected task + sidecar contract",
                "rootCause": ";".join(contract_issues),
            }
        )
    if mapping_issues:
        evidence.append(
            {
                "kind": "RESOURCE_MAPPING_ROOT_CAUSE",
                "source": "typed sourceReference -> approved resolver/catalog",
                "rootCause": ";".join(sorted(set(mapping_issues))),
            }
        )
    if recipe_gaps:
        evidence.append(
            {
                "kind": "RUNTIME_RECIPE_ROOT_CAUSE",
                "source": "typed input reference -> input-side recipe catalog",
                "rootCause": ";".join(sorted(set(recipe_gaps))),
            }
        )
    if local_missing:
        evidence.append(
            {
                "kind": "LOCAL_INPUT_RESOURCE",
                "source": "explicit PYTHON_FIXTURE paths and approved generation metadata",
                "rootCause": ";".join(local_missing),
            }
        )
    evidence.extend(probe_evidence)
    if model_required:
        evidence.append(
            {
                "kind": "MODEL_PHASE_BOUNDARY",
                "source": "input-side execution strategy",
                "rootCause": (
                    "The required runner input is model-generated or the typed model-phase "
                    "candidate is not preflightable; no model call was made in Stage 21."
                ),
            }
        )
    if zero_hit_refs:
        evidence.append(
            {
                "kind": "RAG_ZERO_HIT",
                "source": "completed Java public RAG boundary",
                "rootCause": (
                    "RAG completed with resultCount=0; zero-hit is a legitimate completed "
                    "result and was not classified as missing."
                ),
            }
        )
    if pending_issues:
        evidence.append(
            {
                "kind": "RUNTIME_CLASSIFICATION_PENDING",
                "source": "approved Java public readiness evidence",
                "rootCause": ";".join(sorted(set(pending_issues))),
            }
        )
    if classification == "READY":
        evidence.append(
            {
                "kind": "DETERMINISTIC_READY",
                "source": "input-side resolver plus public-boundary prerequisite probes",
                "rootCause": (
                    "All applicable input contract, typed mapping, recipe, auth, authority, "
                    "resource, and target prerequisites passed."
                ),
            }
        )

    refs = [entry.as_dict() for entry in task.entries]
    ref_types = sorted({entry.kind for entry in task.entries})
    target_services = list(resolved["targetUrls"])
    if java_required and not target_services:
        target_services = ["JAVA_PUBLIC_BOUNDARY"]
    return {
        "taskId": manifest_entry.task_id,
        "split": manifest_entry.split,
        "category": task.task_type,
        "authProfile": prerequisite.auth_profile,
        "currentProjectId": prerequisite.current_project_id,
        "targetProjectId": prerequisite.target_project_id,
        "executionStrategy": strategy,
        "inputReferenceType": "+".join(ref_types) if ref_types else "NONE",
        "inputReferences": refs,
        "semanticRequiredness": assess_required_fields(task, prerequisite),
        "runtimeRecipe": resolved["runtimeRecipe"],
        "javaRequired": java_required,
        "requiredJavaBoundary": required_boundaries,
        "requiredTargetService": target_services,
        "contractStatus": _status("PASS", contract_issues),
        "resourceStatus": resource_status,
        "strategyStatus": _status(strategy_status, strategy_issues),
        "authStatus": auth_status,
        "runtimePrerequisiteStatus": runtime_status,
        "classification": classification,
        "classificationPending": (
            sorted(set(pending_issues)) if classification is None else []
        ),
        "evidence": evidence,
        "probeStatus": statuses,
        "zeroHitRagReferences": zero_hit_refs,
        "rootCause": (
            ";".join(sorted(set(pending_issues)))
            if classification is None
            else _root_cause(
                classification,
                contract_issues=contract_issues,
                strategy_issues=strategy_issues,
                mapping_issues=mapping_issues,
                recipe_gaps=recipe_gaps,
                auth_issues=auth_issues,
                java_issues=java_issues,
                local_missing=local_missing,
                resource_issues=resource_issues,
                model_required=model_required,
                evidence=evidence,
            )
        ),
        "recommendedAction": (
            "Collect an approved public readiness signal that distinguishes the handler-level "
            "failure root cause; no repair performed."
            if classification is None
            else _recommended_action(classification)
        ),
    }


def run_runtime_prerequisite_audit(
    *,
    manifest_path: Path,
    sidecar_path: Path,
    recipe_dir: Path,
    repo_root: Path,
    snapshot: RuntimeProbeSnapshot,
) -> RuntimeAuditResult:
    """Build the final 105-row matrix from a fixed public-boundary snapshot."""

    manifest = project_manifest_file(manifest_path)
    prerequisites = load_prerequisites(sidecar_path)
    recipe_index = load_recipe_index(recipe_dir)
    recipe_contexts = load_recipe_contexts(recipe_dir)
    tasks = _load_projected_tasks(manifest_path, manifest)
    rows: list[dict[str, Any]] = []
    for entry in manifest.tasks:
        prerequisite = prerequisites.get(entry.task_id)
        if prerequisite is None:
            prerequisite = Prerequisite(
                entry.task_id,
                "<missing>",
                None,
                None,
                None,
                (),
                None,
                (),
                "<missing>",
                "<missing>",
                (),
                ("sidecar_row_missing",),
            )
        rows.append(
            _audit_one(
                entry,
                tasks[entry.task_id],
                prerequisite,
                recipe_index=recipe_index,
                recipe_contexts=recipe_contexts,
                repo_root=repo_root,
                recipe_dir=recipe_dir,
                snapshot=snapshot,
            )
        )
    counts = Counter(row["classification"] for row in rows)
    classification_counts = {
        classification: counts.get(classification, 0) for classification in ALLOWED_CLASSIFICATIONS
    }
    pending_classification_count = counts.get(None, 0)
    metadata = {
        "schemaVersion": "stage21-runtime-prerequisite-audit/v1",
        "auditMode": "INPUT_ONLY_DETERMINISTIC_RUNTIME_PREREQUISITE_VALIDATION",
        "datasetId": manifest.dataset_id,
        "datasetVersion": manifest.dataset_version,
        "taskSchemaVersion": manifest.task_schema_version,
        "manifestPath": manifest_path.name,
        "taskCount": len(rows),
        "splitCounts": dict(sorted(Counter(row["split"] for row in rows).items())),
        "classificationCounts": classification_counts,
        "pendingClassificationCount": pending_classification_count,
        "javaHealth": snapshot.java_health,
        "probeCounts": dict(sorted(snapshot.probe_counts.items())),
        "recipeCatalogIssues": list(recipe_index.catalog_issues),
    }
    verification = {
        "expectedSideLoadedCount": 0,
        "expectedSideValuesMaterialized": False,
        "expectedSideRawValuesParsed": False,
        "benchmarkEvaluatorImportedDuringAudit": False,
        "benchmarkDatasetLoaderImportedDuringAudit": False,
        "benchmarkTaskModelImportedDuringAudit": False,
        "modelCallCount": 0,
        "agentWorkflowCallCount": 0,
        "baselineRunCount": 0,
        "fixtureFallbackCount": 0,
        "pythonBypassCount": 0,
        "javaMutationCount": 0,
        "runnerSubmitCount": 0,
        "targetServiceRequests": 0,
        "unknownRecipeFailClosed": True,
        "inputOnlyRuntimeDecision": True,
        "intentionalAuthorizationDenyCount": snapshot.probe_counts.get(
            "intentionalAuthorizationDenyCount", 0
        ),
        "intentionalAuthorizationDenyScopeSmokeCount": snapshot.probe_counts.get(
            "intentionalAuthorizationDenyScopeSmokeCount", 0
        ),
        "intentionalAuthorizationDenyReferenceProbeCount": snapshot.probe_counts.get(
            "intentionalAuthorizationDenyReferenceProbeCount", 0
        ),
        "successfulToolGatewayAuthoritySmokeCount": snapshot.probe_counts.get(
            "successfulToolGatewayAuthoritySmokeCount", 0
        ),
        "successfulRagAuthoritySmokeCount": snapshot.probe_counts.get(
            "successfulRagAuthoritySmokeCount", 0
        ),
        "legitimateRagZeroHitCount": snapshot.probe_counts.get("legitimateRagZeroHitCount", 0),
        "unresolvedJavaResourceCount": snapshot.probe_counts.get("unresolvedJavaResourceCount", 0),
        "ragAuthorityPathPassCount": snapshot.probe_counts.get("ragAuthorityPathPassCount", 0),
        "pendingClassificationCount": pending_classification_count,
        "classificationCompleteness": (
            "PASS" if pending_classification_count == 0 else "PENDING_PUBLIC_ROOT_CAUSE_EVIDENCE"
        ),
        "probeSnapshot": snapshot.as_dict(),
    }
    return RuntimeAuditResult(metadata, tuple(rows), verification, snapshot)


def assert_runtime_result_invariants(result: RuntimeAuditResult) -> None:
    if len(result.rows) != 105:
        raise AssertionError(f"expected 105 audit rows, got {len(result.rows)}")
    if Counter(row["split"] for row in result.rows) != Counter({"dev": 95, "held_out": 10}):
        raise AssertionError("split count is not DEV95 + HELD_OUT10")
    ids = [row["taskId"] for row in result.rows]
    if len(ids) != len(set(ids)):
        raise AssertionError("duplicate taskId in runtime matrix")
    if set(result.metadata["classificationCounts"]) != set(ALLOWED_CLASSIFICATIONS):
        raise AssertionError("classification count map does not enumerate frozen categories")
    invalid = sorted(
        set(row["classification"] for row in result.rows if row["classification"] is not None)
        - set(ALLOWED_CLASSIFICATIONS)
    )
    if invalid:
        raise AssertionError(f"invalid classification values: {invalid}")
    required = {
        "taskId",
        "split",
        "category",
        "authProfile",
        "currentProjectId",
        "targetProjectId",
        "executionStrategy",
        "inputReferenceType",
        "inputReferences",
        "runtimeRecipe",
        "javaRequired",
        "requiredJavaBoundary",
        "requiredTargetService",
        "contractStatus",
        "resourceStatus",
        "strategyStatus",
        "authStatus",
        "runtimePrerequisiteStatus",
        "classification",
        "classificationPending",
        "evidence",
        "recommendedAction",
    }
    for row in result.rows:
        missing = required - set(row)
        if missing:
            raise AssertionError(f"{row.get('taskId')}: missing {sorted(missing)}")
        if row["classification"] != "READY" and not row["evidence"]:
            raise AssertionError(f"{row['taskId']}: non-ready row has no evidence")
        if row["classification"] is None and not row["classificationPending"]:
            raise AssertionError(f"{row['taskId']}: pending row has no pending root-cause reason")
        if row["classification"] is not None and row["classificationPending"]:
            raise AssertionError(
                f"{row['taskId']}: finalized classification carries pending root-cause reasons"
            )
    pending_count = sum(row["classification"] is None for row in result.rows)
    if result.metadata.get("pendingClassificationCount") != pending_count:
        raise AssertionError("pending classification count does not match matrix rows")
    if sum(result.metadata["classificationCounts"].values()) + pending_count != len(result.rows):
        raise AssertionError("frozen classification counts plus pending rows do not total 105")
    verification = result.verification
    for key in (
        "expectedSideLoadedCount",
        "modelCallCount",
        "agentWorkflowCallCount",
        "baselineRunCount",
        "fixtureFallbackCount",
        "pythonBypassCount",
    ):
        if verification[key] != 0:
            raise AssertionError(f"{key} must be zero")
    if (
        verification["expectedSideValuesMaterialized"]
        or verification["expectedSideRawValuesParsed"]
    ):
        raise AssertionError("expected-side data crossed the runtime audit boundary")


__all__ = [
    "RuntimeAuditResult",
    "RuntimeProbeSnapshot",
    "assert_runtime_result_invariants",
    "canonical_root_cause_classification_view",
    "load_recipe_contexts",
    "resource_key",
    "run_runtime_prerequisite_audit",
    "scope_key",
]
