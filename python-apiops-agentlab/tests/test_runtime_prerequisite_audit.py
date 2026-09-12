from __future__ import annotations

import json
from pathlib import Path

from app.input_side_audit import InputEntry, InputTask, Prerequisite, ProjectionTrace
from app.runtime_prerequisite_audit import (
    RuntimeAuditResult,
    RuntimeProbeSnapshot,
    _resolve_input_resources,
    _runtime_findings,
    canonical_root_cause_classification_view,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_ROOT = Path(__file__).resolve().parent / "benchmark" / "fixtures"
RECIPE_DIR = FIXTURE_ROOT / "support"


def _task(*entries: InputEntry, task_type: str = "RAG_EVIDENCE_RETRIEVAL") -> InputTask:
    return InputTask(
        "synthetic-task",
        task_type,
        0,
        "",
        tuple(entries),
        ("rag.search",),
        (),
        "0.2.0",
        (),
        ProjectionTrace(),
    )


def _prerequisite(
    *,
    profile: str = "NORMAL",
    current: int = 41,
    target: int | None = None,
    operations: tuple[str, ...] = ("RAG_SEARCH",),
) -> Prerequisite:
    return Prerequisite(
        "synthetic-task",
        profile,
        current,
        target,
        target,
        operations,
        "VIEWER",
        (),
        "EXISTING_JAVA_RESOURCE",
        "PROJECT_SCOPED",
        (),
        (),
    )


def _snapshot(
    *,
    gateway: dict[str, dict] | None = None,
    rag: dict[str, dict] | None = None,
) -> RuntimeProbeSnapshot:
    return RuntimeProbeSnapshot(
        "HEALTHY",
        {"NORMAL": {"status": "LOGIN_OK"}, "SAFETY_41_ISOLATED": {"status": "LOGIN_OK"}},
        {
            "NORMAL": {"41": {"status": "READ_OK", "role": "VIEWER"}},
            "SAFETY_41_ISOLATED": {"41": {"status": "READ_OK", "role": "VIEWER"}},
        },
        {},
        {},
        gateway or {},
        rag or {},
        {},
        {},
    )


def _resolved_rag(ref: str) -> dict:
    return {
        "runtimeRecipe": {"recipes": []},
        "metadataRefs": [],
        "reportRefs": [],
        "targetUrls": [],
        "ragRefs": [ref],
    }


def test_legal_typed_metadata_uri_is_not_malformed() -> None:
    task = _task(
        InputEntry("JAVA_RESOURCE", "metadata", "java://metadata/project-41/api-api-1"),
        task_type="TESTCASE_GENERATION",
    )
    prerequisite = _prerequisite(operations=("READ_METADATA",))
    from app.input_side_audit import load_recipe_index

    resolved = _resolve_input_resources(
        task,
        prerequisite,
        load_recipe_index(RECIPE_DIR),
        {},
        REPO_ROOT,
        RECIPE_DIR,
    )
    assert resolved["javaResourceIssues"] == []
    assert resolved["metadataRefs"] == [("java://metadata/project-41/api-api-1", 41, "api-api-1")]


def test_intentional_isolation_deny_is_authority_ready() -> None:
    ref = "java://rag/project-42/query/isolation"
    key = "SAFETY_41_ISOLATED|41|42|java://rag/project-42/query/isolation"
    task = _task(InputEntry("JAVA_RESOURCE", "query", ref))
    prerequisite = _prerequisite(profile="SAFETY_41_ISOLATED", target=42)
    result = _runtime_findings(
        task,
        prerequisite,
        _resolved_rag(ref),
        _snapshot(
            rag={
                key: {
                    "status": "FORBIDDEN",
                    "authorityDecision": "DENY",
                    "intentionalIsolationDeny": True,
                    "queryCompleted": False,
                }
            }
        ),
    )
    resource_issues, java_issues, auth_issues, pending, zero_hits, _, _ = result
    assert resource_issues == []
    assert java_issues == []
    assert auth_issues == []
    assert pending == []
    assert zero_hits == []


def test_rag_success_zero_hit_is_not_resource_missing() -> None:
    ref = "java://rag/project-41/query/zero-hit"
    key = "NORMAL|41|-|java://rag/project-41/query/zero-hit"
    task = _task(InputEntry("JAVA_RESOURCE", "query", ref))
    result = _runtime_findings(
        task,
        _prerequisite(),
        _resolved_rag(ref),
        _snapshot(
            rag={
                key: {
                    "status": "SUCCESS",
                    "authorityDecision": "ALLOW_HANDLER_ENTERED",
                    "queryCompleted": True,
                    "resultCount": 0,
                }
            }
        ),
    )
    resource_issues, java_issues, auth_issues, pending, zero_hits, _, _ = result
    assert resource_issues == []
    assert java_issues == []
    assert auth_issues == []
    assert pending == []
    assert zero_hits == [ref]


def test_rag_handler_failure_is_not_misreported_as_zero_hit() -> None:
    ref = "java://rag/project-41/query/provider-failure"
    key = "NORMAL|41|-|java://rag/project-41/query/provider-failure"
    task = _task(InputEntry("JAVA_RESOURCE", "query", ref))
    result = _runtime_findings(
        task,
        _prerequisite(),
        _resolved_rag(ref),
        _snapshot(
            rag={
                key: {
                    "status": "FAILED",
                    "authorityDecision": "ALLOW_HANDLER_ENTERED",
                    "queryCompleted": False,
                }
            }
        ),
    )
    resource_issues, _, auth_issues, pending, zero_hits, _, _ = result
    assert resource_issues == []
    assert auth_issues == []
    assert pending
    assert zero_hits == []


def test_unlisted_direct_report_is_java_resource_missing() -> None:
    ref = "java://test-report/project-42/run-703/report-703"
    task = _task(
        InputEntry("JAVA_RESOURCE", "testReport", ref),
        task_type="FAILURE_DIAGNOSIS",
    )
    resolved = {
        "runtimeRecipe": {"recipes": []},
        "metadataRefs": [],
        "reportRefs": [(ref, 42, 703, "DIRECT_REPORT")],
        "targetUrls": [],
        "ragRefs": [],
    }
    snapshot = RuntimeProbeSnapshot(
        "HEALTHY",
        {"NORMAL": {"status": "LOGIN_OK"}},
        {"NORMAL": {"42": {"status": "READ_OK", "role": "VIEWER"}}},
        {},
        {
            "NORMAL|42|java://test-report/project-42/run-703/report-703": {
                "status": "RUN_NOT_LISTED",
                "runListed": False,
            }
        },
        {},
        {},
        {},
        {},
    )
    resource_issues, java_issues, auth_issues, pending, _, _, _ = _runtime_findings(
        task,
        _prerequisite(current=42, operations=("READ_REPORT",)),
        resolved,
        snapshot,
    )
    assert any("run is absent" in issue for issue in resource_issues)
    assert java_issues == []
    assert auth_issues == []
    assert pending == []


def test_canonical_classification_view_excludes_runtime_identity() -> None:
    result = RuntimeAuditResult(
        metadata={
            "taskCount": 1,
            "splitCounts": {"dev": 1},
            "classificationCounts": {
                "READY": 1,
                "TASK_INPUT_CONTRACT_GAP": 0,
                "RUNTIME_RESOURCE_MISSING": 0,
                "RESOURCE_MAPPING_BUG": 0,
                "REAL_JAVA_BUG": 0,
                "STRATEGY_INPUT_CONTRACT_GAP": 0,
                "AUTH_PREREQUISITE_GAP": 0,
                "RUNTIME_RECIPE_GAP": 0,
                "NOT_PREFLIGHTABLE_MODEL_BEHAVIOR": 0,
            },
            "pendingClassificationCount": 0,
        },
        rows=(
            {
                "taskId": "synthetic-task",
                "split": "dev",
                "classification": "READY",
                "classificationPending": [],
                "rootCause": "ready",
            },
        ),
        verification={},
        probe_snapshot=_snapshot(
            gateway={"scope": {"runtimeAgentRunId": "stage21-runtime-probe:uuid"}}
        ),
    )
    canonical = canonical_root_cause_classification_view(result)
    assert "runtimeAgentRunId" not in json.dumps(canonical, sort_keys=True)
