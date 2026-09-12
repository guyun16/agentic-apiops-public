"""Admission only: a disclosed local authority gap never waives runtime/security checks."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory

import httpx

from app.benchmark.auth_profiles import AuthProfileResolver
from app.clients.java_apiops import JavaApiOpsAuthorizationError, JavaApiOpsClient
from app.core.settings import AppSettings

ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = Path(__file__).with_name("stage21-final-revision.json")
CONFIG = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
FINAL_REVISION = CONFIG["revision"]
KNOWN_TASK = "bench_task_formal_testcase_auth_missing_token_post"
EXCLUDED_PARTS = {
    ".git", ".venv", "__pycache__", ".pytest_cache", ".ruff_cache", "target",
    "artifacts", "f105r", "node_modules", "data", "dist", "build",
}


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def source_inventory() -> dict[str, str]:
    """Freeze tracked and untracked inputs, including ignored local Java config."""
    output = subprocess.run(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
        cwd=ROOT, capture_output=True, check=True,
    ).stdout.decode("utf-8")
    paths = {ROOT / relative for relative in output.split("\0") if relative}
    for directory in ("python-apiops-agentlab/app", "java-apiops-platform"):
        paths.update((ROOT / directory).rglob("*"))
    return {
        path.relative_to(ROOT).as_posix(): digest(path)
        for path in sorted(paths)
        if path.is_file() and not EXCLUDED_PARTS.intersection(path.relative_to(ROOT).parts)
        and path.suffix not in {".pyc", ".log", ".db", ".sqlite3"}
    }


def configuration_check(settings: AppSettings) -> None:
    if (
        CONFIG["provider"] != "Qwen" or CONFIG["model"] != "qwen3.8-max"
        or settings.qwen_model != CONFIG["model"]
        or settings.qwen_base_url.rstrip("/") != CONFIG["qwenBaseUrl"]
        or settings.qwen_timeout_seconds != CONFIG["qwenTimeoutSeconds"]
    ):
        raise RuntimeError("FINAL_REVISION_PROVIDER_CONFIGURATION_DRIFT")


def known_limitation() -> dict[str, object]:
    record = json.loads((ROOT / CONFIG["knownLimitations"]).read_text(encoding="utf-8"))
    rows = record.get("limitations", [])
    if (
        record.get("revision") != FINAL_REVISION or len(rows) != 1
        or record.get("admissionOnly") is not True
        or any(record.get(key) is not False for key in (
            "changesEvaluator", "prepopulatesOutcomes", "excludesTasks"
        ))
    ):
        raise RuntimeError("KNOWN_LIMITATION_SCOPE_DRIFT")
    row = rows[0]
    if (
        row.get("benchmarkTaskId") != KNOWN_TASK
        or row.get("scope") != "TASK_LOCAL_RESPONSE_CONTRACT_AUTHORITY"
        or row.get("authorityReadiness") != "INCOMPLETE_NOT_READY"
    ):
        raise RuntimeError("KNOWN_LIMITATION_SCOPE_DRIFT")
    for key, hash_key in (("taskFile", "taskSha256"), ("groundTruthFile", "groundTruthSha256")):
        if digest(ROOT / row[key]) != row[hash_key]:
            raise RuntimeError("KNOWN_LIMITATION_CONTRACT_DRIFT")
    observed = json.loads((ROOT / row["observedTaskArtifact"]).read_text(encoding="utf-8"))
    exact = [m for m in observed["evaluationResult"]["metrics"] if m["metric"] == "exact_match"]
    if (
        observed["benchmarkTaskId"] != KNOWN_TASK or observed["status"] != "SUCCESS"
        or observed.get("failureCode") is not None or len(exact) != 1
        or exact[0]["status"] != "UNKNOWN"
        or exact[0]["reason"] != "structured facts unavailable: expected_error_code"
    ):
        raise RuntimeError("KNOWN_LIMITATION_EVIDENCE_DRIFT")
    return record


def admission_decision(
    *, runtime: dict, provider: dict, path: dict, integrity: dict,
    limitation: dict, additional_blockers: tuple[str, ...] = (),
) -> dict[str, object]:
    """No task-ID waiver is applied to runtime, authorization, or persistence failures."""
    if (
        runtime.get("status") != "PASS" or runtime.get("nonReadyTaskIds") not in ([], ())
        or runtime.get("unresolvedJavaResourceCount") != 0
        or any(count for name, count in runtime.get("classificationCounts", {}).items()
               if name not in {"READY", "NOT_PREFLIGHTABLE_MODEL_BEHAVIOR"})
        or provider.get("status") != "PASS" or provider.get("provider") != "Qwen"
        or provider.get("model") != "qwen3.8-max"
        or path.get("overBudgetCount") != 0 or path.get("uniqueTaskPaths") != 105
        or integrity.get("status") != "PASS" or additional_blockers
        or limitation != known_limitation()
    ):
        raise RuntimeError("FINAL_REVISION_ADMISSION_BLOCKED")
    return {
        "status": "ALLOW_WITH_KNOWN_LIMITATION", "revision": FINAL_REVISION,
        "taskCount": 105, "minimumPassCountFor85Percent": 90,
        "knownLimitationTaskIds": [KNOWN_TASK],
        "authorityReadiness": "INCOMPLETE_NOT_READY",
        "executionReadinessSeparateFromOutcomeAuthority": True,
        "runtimeSecurityProviderPathPersistenceExemptions": [],
        "prepopulatesOutcomes": False, "excludedTaskIds": [],
    }


async def shared_live_preflight(settings: AppSettings) -> dict[str, object]:
    """Read-only Java boundary probes; no LLM, Runner submit or Tool Gateway execution."""
    async with httpx.AsyncClient(trust_env=False) as http:
        base = settings.java_apiops_base_url.rstrip("/")
        for url in (base + "/actuator/health", "http://127.0.0.1:8080/products?pageNo=1&pageSize=1"):
            if (await http.get(url, timeout=10)).status_code != 200:
                raise RuntimeError("SHARED_RUNTIME_HEALTH_FAILED")
        unauth = await http.get(base + "/api/v1/projects/41", timeout=10)
        if unauth.status_code != 401 or unauth.json().get("code") != "A0004":
            raise RuntimeError("SHARED_AUTHENTICATION_DENIAL_FAILED")
        java = JavaApiOpsClient(http, base_url=base, timeout_seconds=10)
        resolver = AuthProfileResolver(java)
        checks = []
        local_contract = None
        for profile, own, denied in (
            ("NORMAL", 41, None), ("SAFETY_41_ISOLATED", 41, 42),
            ("SAFETY_42_ISOLATED", 42, 41),
        ):
            session = await resolver.resolve(profile)
            await java.assert_project_readable(
                project_id=own, token=session.token, trace_id="stage21-final-freeze-readiness",
            )
            if profile == "NORMAL":
                metadata = await java.get_api_metadata(
                    project_id=41, api_id="stage21-auth-api-key", token=session.token,
                    trace_id="stage21-final-freeze-local-contract",
                )
                if (
                    metadata.api_id != "stage21-auth-api-key" or metadata.method != "POST"
                    or metadata.path != "/stage21/auth-check" or metadata.response_schemas
                ):
                    raise RuntimeError("KNOWN_LIMITATION_LIVE_CONTRACT_CHANGED")
                local_contract = {
                    "apiId": metadata.api_id, "method": metadata.method, "path": metadata.path,
                    "responseSchemaCount": 0, "authorityReadiness": "INCOMPLETE_NOT_READY",
                }
            if denied is not None:
                try:
                    await java.assert_project_readable(
                        project_id=denied, token=session.token,
                        trace_id="stage21-final-freeze-denial",
                    )
                except JavaApiOpsAuthorizationError:
                    pass
                else:
                    raise RuntimeError("SHARED_CROSS_PROJECT_DENIAL_FAILED")
            checks.append({"profile": profile, "ownProject": own, "deniedProject": denied})
    return {
        "status": "PASS", "javaHealth": "PASS", "runnerTargetHealth": "PASS",
        "missingAuthentication": "HTTP_401_A0004", "profiles": checks,
        "localContract": local_contract,
        "modelCallCount": 0, "runnerSubmitCount": 0, "toolGatewayCallCount": 0,
    }


def persistence_probe(parent: Path) -> dict[str, object]:
    if not parent.is_dir():
        raise RuntimeError("ARTIFACT_PARENT_MISSING")
    # A disposable probe is not an official root or a synthetic benchmark result.
    with TemporaryDirectory(prefix="stage21-freeze-write-probe-", dir=parent) as directory:
        path = Path(directory) / "probe"
        payload = b"stage21-artifact-persistence-probe\n"
        with path.open("xb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        renamed = path.with_suffix(".verified")
        path.rename(renamed)
        if renamed.read_bytes() != payload:
            raise RuntimeError("ARTIFACT_PERSISTENCE_READBACK_FAILED")
    return {"status": "PASS", "parent": str(parent), "probeRemoved": True}


def verify_frozen_revision(path: Path | None, settings: AppSettings) -> dict:
    if path is None or not path.is_file():
        raise RuntimeError("live Formal105 requires --revision-freeze")
    configuration_check(settings)
    frozen = json.loads(path.read_text(encoding="utf-8"))
    if (
        frozen.get("finalRevision") != FINAL_REVISION
        or frozen.get("freezeStatus") != "FROZEN_WITH_KNOWN_LIMITATION"
        or frozen.get("configuration") != CONFIG
        or frozen.get("knownLimitations") != known_limitation()
        or frozen.get("admission", {}).get("status") != "ALLOW_WITH_KNOWN_LIMITATION"
        or frozen.get("sourceInventory") != source_inventory()
        or not frozen.get("evidenceDigests")
    ):
        raise RuntimeError("FINAL_REVISION_FREEZE_OR_SOURCE_DRIFT")
    for relative, expected in frozen.get("evidenceDigests", {}).items():
        if digest(ROOT / relative) != expected:
            raise RuntimeError("FINAL_REVISION_ACCEPTANCE_EVIDENCE_DRIFT")
    for relative, expected in frozen.get("runtimeArtifacts", {}).items():
        if digest(ROOT / relative) != expected:
            raise RuntimeError("FINAL_REVISION_JAVA_PACKAGE_DRIFT")
    return frozen
