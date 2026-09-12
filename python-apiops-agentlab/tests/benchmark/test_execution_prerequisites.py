"""Deterministic validation for the Stage 21 execution prerequisite sidecar."""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

import pytest

from app.tools import ToolCatalog, ToolIntent, map_tool_intent

FIXTURE_ROOT = Path(__file__).parent / "fixtures"
MANIFEST_PATH = FIXTURE_ROOT / "dataset-manifest.json"
SIDECAR_PATH = FIXTURE_ROOT / "stage21-execution-prerequisites.json"
OUTCOME_POLICY_PATH = FIXTURE_ROOT / "stage21-outcome-policy-v2.json"

ROW_FIELDS = {
    "benchmarkTaskId",
    "authProfile",
    "currentProjectId",
    "targetProjectId",
    "resourceProjectId",
    "requiredOperations",
    "minimumProjectRole",
    "requiredAuthorities",
    "resourceSetupType",
    "resourceOwnership",
    "contractGaps",
}
OPTIONAL_ROW_FIELDS = {
    "approvedToolArguments",
    "approvalAuthority",
    "approvalDecision",
    "selectedTool",
    "terminalSafetyDecision",
    "candidateValidationPolicy",
}
PROFILES = {"NORMAL", "SAFETY_41_ISOLATED", "SAFETY_42_ISOLATED", "UNASSIGNED"}
ROLES = {"VIEWER", "EDITOR", "OWNER", "NONE", "NOT_APPLICABLE"}
OPERATIONS = {
    "READ_METADATA",
    "READ_REPORT",
    "RUNNER_SUBMIT",
    "RUNNER_STATUS",
    "TOOL_CALL",
    "RAG_SEARCH",
    "NO_JAVA_ACCESS",
    "NO_TOOL_CALL",
}
RESOURCE_TYPES = {
    "EXISTING_JAVA_RESOURCE",
    "RUNTIME_RECIPE",
    "BENCHMARK_LOCAL_INPUT",
    "TEST_ONLY_REFERENCE",
    "INVALID_FOR_STANDALONE_BASELINE",
    "NOT_APPLICABLE",
}
GAPS = {
    "NONE",
    "AUTH_PROFILE_GAP",
    "TARGET_SCOPE_CONTRACT_GAP",
    "RESOURCE_SCOPE_AMBIGUOUS",
    "RESOURCE_REFERENCE_GAP",
    "RUNTIME_RECIPE_GAP",
    "TASK_EXECUTION_CONFIG_MISMATCH",
}
FORBIDDEN_EXPECTED_KEYS = {
    "expected",
    "groundtruth",
    "expectedtoolcalls",
    "expectedevidenceids",
    "expectedoutput",
    "tasksuccess",
    "expectedsafety",
}

TARGET_SCOPE_TASKS = {
    "bench_task_golden_tool_safety": (41, 42, None, "SAFETY_41_ISOLATED"),
    "bench_task_tool_java_deny": (41, 42, 42, "SAFETY_41_ISOLATED"),
    "bench_task_rag_wrong_project": (42, 41, 41, "SAFETY_42_ISOLATED"),
    "bench_task_formal_rag_wrong_project_isolation": (41, 42, 42, "SAFETY_41_ISOLATED"),
    "bench_task_formal_tool_cross_project_request": (41, 42, 42, "SAFETY_41_ISOLATED"),
    # Human-approved execution amendment; expected-side files are not loaded here.
    "bench_task_formal_tool_java_deny_project": (41, 42, None, "SAFETY_41_ISOLATED"),
    "bench_task_e2e_diagnosis_tool_guarded": (42, 41, 42, "SAFETY_42_ISOLATED"),
    "bench_task_formal_e2e_generation_diagnosis_guarded": (
        41,
        42,
        None,
        "SAFETY_41_ISOLATED",
    ),
    "bench_task_formal_tool_deny_no_alternate_path": (
        41,
        42,
        None,
        "SAFETY_41_ISOLATED",
    ),
}
UNASSIGNED_TASKS: set[str] = set()
RUNNER_SUBMIT_TASKS = {
    "bench_task_golden_e2e_apiops",
    "bench_task_e2e_generation_runner_success",
    "bench_task_e2e_generation_business_failure",
    "bench_task_formal_e2e_generation_diagnosis_guarded",
    "bench_task_testcase_happy_create_order_runner",
    "bench_task_testcase_business_inventory_runner",
    "bench_task_formal_testcase_inventory_conflict_runner",
}


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _rows() -> tuple[dict[str, Any], ...]:
    return tuple(_load_json(SIDECAR_PATH)["tasks"])


def _task_records() -> dict[str, dict[str, Any]]:
    manifest = _load_json(MANIFEST_PATH)
    return {
        entry["benchmarkTaskId"]: _load_json(FIXTURE_ROOT / entry["taskFile"])
        for entry in manifest["tasks"]
    }


def _entry_value(entry: dict[str, Any]) -> Any:
    return entry.get("ref", entry.get("value"))


def _structured_project(value: Any) -> int | None:
    if not isinstance(value, str) or not value.startswith("java://"):
        return None
    match = re.search(r"(?:^|/)project-(\d+)(?:/|-|$)", value)
    return int(match.group(1)) if match else None


def _manifest_resource_project(task_id: str, task: dict[str, Any]) -> int | None:
    if task_id == "bench_task_rag_wrong_project":
        return 41
    for entry in task["initialState"]["entries"]:
        project_id = _structured_project(_entry_value(entry))
        if project_id is not None:
            return project_id
    return None


def _manifest_current_project(task: dict[str, Any]) -> int | None:
    entries = {entry["key"]: entry for entry in task["initialState"]["entries"]}
    for key in ("sourceProjectId", "projectId"):
        value = entries.get(key, {}).get("value")
        if isinstance(value, int) and not isinstance(value, bool) and value > 0:
            return value
    return None


def test_sidecar_matches_active_manifest_exactly() -> None:
    manifest = _load_json(MANIFEST_PATH)
    sidecar = _load_json(SIDECAR_PATH)
    manifest_ids = [entry["benchmarkTaskId"] for entry in manifest["tasks"]]
    sidecar_ids = [row["benchmarkTaskId"] for row in sidecar["tasks"]]

    assert len(manifest_ids) == 105
    assert len(set(manifest_ids)) == 105
    assert len(sidecar_ids) == 105
    assert len(set(sidecar_ids)) == 105
    assert sidecar_ids == manifest_ids
    assert sidecar["datasetId"] == manifest["datasetId"]
    assert sidecar["datasetVersion"] == manifest["datasetVersion"]
    assert sidecar["taskSchemaVersion"] == manifest["taskSchemaVersion"]


def test_sidecar_rows_are_strict_and_expected_side_free() -> None:
    for row in _rows():
        assert ROW_FIELDS <= set(row) <= ROW_FIELDS | OPTIONAL_ROW_FIELDS
        assert row["authProfile"] in PROFILES
        assert row["minimumProjectRole"] in ROLES
        assert set(row["requiredOperations"]).issubset(OPERATIONS)
        assert row["resourceSetupType"] in RESOURCE_TYPES
        assert set(row["contractGaps"]).issubset(GAPS)
        assert row["contractGaps"]
        assert not ("NONE" in row["contractGaps"] and len(row["contractGaps"]) > 1)
        assert row.get("candidateValidationPolicy") in {
            None,
            "PRESERVE_INTENTIONAL_INVALIDITY",
        }

        for key in row:
            assert key.lower() not in FORBIDDEN_EXPECTED_KEYS


def test_intentionally_invalid_generation_policy_is_input_side_and_bounded() -> None:
    rows = {row["benchmarkTaskId"]: row for row in _rows()}
    policy_task_ids = {
        task_id
        for task_id, row in rows.items()
        if row.get("candidateValidationPolicy") == "PRESERVE_INTENTIONAL_INVALIDITY"
    }

    assert policy_task_ids == {
        "bench_task_testcase_missing_required_api_id",
        "bench_task_testcase_missing_required_schema",
        "bench_task_formal_testcase_extra_agent_field",
        "bench_task_formal_testcase_invalid_http_method",
        "bench_task_formal_testcase_missing_api_id_against_contract",
        "bench_task_formal_testcase_missing_json_path_expected",
        "bench_task_formal_testcase_missing_schema_version_against_contract",
        "bench_task_formal_testcase_missing_status_expected",
        "bench_task_formal_testcase_project_id_type",
        "bench_task_formal_testcase_unknown_assertion_type",
    }


def test_sidecar_profile_and_scope_assignments_are_frozen() -> None:
    rows = {row["benchmarkTaskId"]: row for row in _rows()}

    assert Counter(row["authProfile"] for row in rows.values()) == {
        "NORMAL": 96,
        "SAFETY_41_ISOLATED": 7,
        "SAFETY_42_ISOLATED": 2,
    }
    assert set(task_id for task_id, row in rows.items() if row["authProfile"] == "UNASSIGNED") == (
        UNASSIGNED_TASKS
    )

    for task_id, (current, target, resource, profile) in TARGET_SCOPE_TASKS.items():
        row = rows[task_id]
        assert (
            row["currentProjectId"],
            row["targetProjectId"],
            row["resourceProjectId"],
            row["authProfile"],
        ) == (current, target, resource, profile)
        assert row["targetProjectId"] is not None or profile == "UNASSIGNED"

    for row in rows.values():
        if row["authProfile"] == "NORMAL":
            assert row["targetProjectId"] is None

    assert (
        rows["bench_task_e2e_diagnosis_tool_guarded"]["authProfile"],
        rows["bench_task_e2e_diagnosis_tool_guarded"]["currentProjectId"],
        rows["bench_task_e2e_diagnosis_tool_guarded"]["resourceProjectId"],
        rows["bench_task_e2e_diagnosis_tool_guarded"]["contractGaps"],
    ) == ("SAFETY_42_ISOLATED", 42, 42, ["NONE"])
    assert (
        rows["bench_task_formal_tool_deny_no_alternate_path"]["authProfile"],
        rows["bench_task_formal_tool_deny_no_alternate_path"]["currentProjectId"],
        rows["bench_task_formal_tool_deny_no_alternate_path"]["targetProjectId"],
        rows["bench_task_formal_tool_deny_no_alternate_path"]["contractGaps"],
    ) == ("SAFETY_41_ISOLATED", 41, 42, ["NONE"])
    assert (
        rows["bench_task_formal_tool_java_deny_project"]["authProfile"],
        rows["bench_task_formal_tool_java_deny_project"]["currentProjectId"],
        rows["bench_task_formal_tool_java_deny_project"]["targetProjectId"],
        rows["bench_task_formal_tool_java_deny_project"]["contractGaps"],
    ) == (
        "SAFETY_41_ISOLATED",
        41,
        42,
        ["TARGET_SCOPE_CONTRACT_GAP"],
    )


def test_sidecar_permission_and_authority_invariants() -> None:
    rows = {row["benchmarkTaskId"]: row for row in _rows()}

    assert (
        set(
            task_id for task_id, row in rows.items() if "RUNNER_SUBMIT" in row["requiredOperations"]
        )
        == RUNNER_SUBMIT_TASKS
    )
    for row in rows.values():
        if "RUNNER_SUBMIT" in row["requiredOperations"]:
            assert row["minimumProjectRole"] in {"EDITOR", "OWNER"}
        if any(operation in row["requiredOperations"] for operation in ("TOOL_CALL", "RAG_SEARCH")):
            assert row["requiredAuthorities"] == ["TOOL_READ"]
        if row["requiredOperations"] == ["NO_JAVA_ACCESS"]:
            assert row["minimumProjectRole"] == "NOT_APPLICABLE"
            assert row["requiredAuthorities"] == []
        if row["requiredOperations"] == ["NO_TOOL_CALL"]:
            assert row["requiredAuthorities"] == ["TOOL_READ"]


def test_sidecar_counts_and_foreign_resource_scope_are_machine_checked() -> None:
    rows = _rows()
    tasks = _task_records()
    row_by_id = {row["benchmarkTaskId"]: row for row in rows}

    assert Counter(row["minimumProjectRole"] for row in rows) == {
        "VIEWER": 76,
        "EDITOR": 7,
        "NOT_APPLICABLE": 22,
    }
    assert Counter(row["resourceSetupType"] for row in rows) == {
        "EXISTING_JAVA_RESOURCE": 34,
        "RUNTIME_RECIPE": 37,
        "TEST_ONLY_REFERENCE": 21,
        "BENCHMARK_LOCAL_INPUT": 13,
    }
    assert Counter(gap for row in rows for gap in row["contractGaps"]) == {
        "NONE": 75,
        "RESOURCE_REFERENCE_GAP": 21,
        "RUNTIME_RECIPE_GAP": 2,
        "TARGET_SCOPE_CONTRACT_GAP": 6,
        "TASK_EXECUTION_CONFIG_MISMATCH": 1,
    }

    foreign_ids = {
        task_id
        for task_id, row in row_by_id.items()
        if row["currentProjectId"] is not None
        and row["resourceProjectId"] is not None
        and row["currentProjectId"] != row["resourceProjectId"]
    }
    expected_sidecar_foreign_ids = {
        "bench_task_tool_java_deny",
        "bench_task_rag_wrong_project",
        "bench_task_formal_rag_wrong_project_isolation",
        "bench_task_formal_testcase_boundary_inventory_zero",
        "bench_task_formal_tool_cross_project_request",
    }
    assert foreign_ids == expected_sidecar_foreign_ids
    # The sidecar retains the historical execution note; the corrected typed
    # task reference is project-scoped to its trusted project 41.
    expected_manifest_foreign_ids = expected_sidecar_foreign_ids - {
        "bench_task_formal_testcase_boundary_inventory_zero"
    }
    assert {
        task_id
        for task_id, task in tasks.items()
        if _manifest_current_project(task) is not None
        and _manifest_resource_project(task_id, task) is not None
        and _manifest_current_project(task) != _manifest_resource_project(task_id, task)
    } == expected_manifest_foreign_ids


@pytest.mark.parametrize(
    ("task_id", "expected_operations"),
    [
        ("bench_task_golden_testcase_happy", ["READ_METADATA"]),
        ("bench_task_golden_failure_diagnosis", ["READ_REPORT", "TOOL_CALL", "RAG_SEARCH"]),
        ("bench_task_golden_rag_evidence", ["READ_REPORT", "TOOL_CALL", "RAG_SEARCH"]),
        ("bench_task_golden_tool_safety", ["TOOL_CALL", "RAG_SEARCH"]),
        (
            "bench_task_golden_e2e_apiops",
            [
                "READ_METADATA",
                "RUNNER_SUBMIT",
                "RUNNER_STATUS",
                "READ_REPORT",
                "TOOL_CALL",
                "RAG_SEARCH",
            ],
        ),
    ],
)
def test_representative_operations_are_frozen_from_input_side(
    task_id: str, expected_operations: list[str]
) -> None:
    row = next(row for row in _rows() if row["benchmarkTaskId"] == task_id)
    assert row["requiredOperations"] == expected_operations


def test_execution_required_tools_match_the_formal_offline_policy() -> None:
    rows = {row["benchmarkTaskId"]: row for row in _rows()}
    policy = _load_json(OUTCOME_POLICY_PATH)
    policy_required = {
        item["benchmarkTaskId"]: requirements[0]["toolName"]
        for item in policy["tasks"]
        if (
            requirements := [
                requirement
                for requirement in item["toolRequirements"]
                if requirement["requirement"] == "REQUIRED"
            ]
        )
    }
    prerequisite_required = {
        task_id: (
            "rag.search"
            if "RAG_SEARCH" in row["requiredOperations"]
            else "redis.read"
        )
        for task_id, row in rows.items()
        if "TOOL_CALL" in row["requiredOperations"]
    }

    assert prerequisite_required == policy_required
    assert rows["bench_task_tool_no_bypass"]["requiredOperations"] == ["NO_TOOL_CALL"]
    assert rows["bench_task_formal_tool_no_bypass_database"]["requiredOperations"] == [
        "NO_TOOL_CALL"
    ]
    assert rows["bench_task_formal_tool_allowed_redis_exact"][
        "approvedToolArguments"
    ] == {"key": "runner:701"}


def test_sensitive_read_preapproval_is_explicit_bounded_and_input_side() -> None:
    sidecar = _load_json(SIDECAR_PATH)
    rows = {row["benchmarkTaskId"]: row for row in sidecar["tasks"]}
    approved = {
        task_id: row
        for task_id, row in rows.items()
        if row.get("approvalDecision") is not None
        or row.get("approvalAuthority") is not None
    }

    assert sidecar["sidecarVersion"] == "1.1.1"
    assert set(approved) == {"bench_task_formal_tool_allowed_redis_exact"}
    row = approved["bench_task_formal_tool_allowed_redis_exact"]
    assert row["approvalDecision"] == "APPROVE"
    assert row["approvalAuthority"] == "BENCHMARK_EXECUTION_PREREQUISITE"
    assert row["selectedTool"] == "redis.read"
    assert row["approvedToolArguments"] == {"key": "runner:701"}
    assert "TOOL_CALL" in row["requiredOperations"]
    assert "terminalSafetyDecision" not in row


def test_sidecar_target_does_not_inject_into_model_tool_arguments() -> None:
    row = next(
        row
        for row in _rows()
        if row["benchmarkTaskId"] == "bench_task_formal_tool_java_deny_project"
    )
    assert row["targetProjectId"] == 42

    intent = ToolIntent(
        tool_name="rag.search",
        arguments={"query": "order failure", "topK": 1},
    )
    call = map_tool_intent(
        intent,
        catalog=ToolCatalog(),
        agent_run_id="run-no-sidecar-injection",
        project_id=str(row["currentProjectId"]),
        trace_id="trace-no-sidecar-injection",
    )

    assert "targetProjectId" not in call.params
