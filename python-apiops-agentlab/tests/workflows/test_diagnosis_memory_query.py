"""Tests for the deterministic Diagnosis Historical Memory query canonicalizer."""

from __future__ import annotations

import sqlite3
from copy import deepcopy
from typing import Any

import pytest

from app.memory import (
    HistoricalFailureMemoryCandidate,
    InMemoryMemoryStore,
    MemoryLifecycleStatus,
    MemoryRetriever,
    MemoryWritePolicy,
    VerificationStatus,
)
from app.schemas.diagnosis_report import DiagnosisReport
from app.schemas.runner import TestReport as RunnerTestReport
from app.workflows.diagnosis_memory_query import (
    build_memory_symptoms,
    recall_historical_memory,
)


def report_payload() -> dict[str, Any]:
    return {
        "projectId": 41,
        "taskId": 301,
        "runId": 701,
        "reportId": "report:701",
        "status": "ASSERTION_FAILED",
        "startedAt": "2026-08-23T11:59:58Z",
        "finishedAt": "2026-08-23T12:00:00Z",
        "summary": {
            "totalCases": 2,
            "totalSteps": 3,
            "totalAssertions": 2,
            "passedAssertions": 1,
            "failedAssertions": 1,
            "failureType": "ASSERTION_MISMATCH",
        },
        "cases": [
            {
                "caseId": "case-failed",
                "status": "ASSERTION_FAILED",
                "failureType": "ASSERTION_MISMATCH",
                "steps": [
                    {
                        "stepId": "step-failed",
                        "status": "ASSERTION_FAILED",
                        "failureType": "ASSERTION_MISMATCH",
                        "responseStatusCode": 500,
                        "durationMs": 12,
                        "assertionResults": [
                            {
                                "type": "STATUS_CODE",
                                "passed": False,
                                "expected": 200,
                                "actual": 500,
                                "message": "status mismatch",
                            },
                            {
                                "type": "HEADER",
                                "passed": True,
                                "expected": "application/json",
                                "actual": "application/json",
                                "message": "header matched",
                            },
                        ],
                    },
                    {
                        "stepId": "step-execution",
                        "status": "EXECUTION_FAILED",
                        "failureType": "NETWORK_ERROR",
                        "responseStatusCode": None,
                        "durationMs": 12,
                        "assertionResults": [],
                    },
                ],
            },
            {
                "caseId": "case-passed",
                "status": "SUCCESS",
                "failureType": "NONE",
                "steps": [
                    {
                        "stepId": "step-passed",
                        "status": "SUCCESS",
                        "failureType": "NONE",
                        "responseStatusCode": 200,
                        "durationMs": 5,
                        "assertionResults": [
                            {
                                "type": "STATUS_CODE",
                                "passed": True,
                                "expected": 200,
                                "actual": 200,
                                "message": "status matched",
                            }
                        ],
                    }
                ],
            },
        ],
    }


def make_report(payload: dict[str, Any] | None = None) -> RunnerTestReport:
    return RunnerTestReport.model_validate(report_payload() if payload is None else payload)


def test_assertion_failure_emits_only_v1_failure_atoms() -> None:
    symptoms = build_memory_symptoms(make_report())

    assert symptoms == (
        "assertion_type:STATUS_CODE",
        "case_failure_type:ASSERTION_MISMATCH",
        "response_status_code:500",
        "run_status:ASSERTION_FAILED",
        "step_failure_type:ASSERTION_MISMATCH",
        "step_failure_type:NETWORK_ERROR",
        "summary_failure_type:ASSERTION_MISMATCH",
    )
    assert "HEADER" not in symptoms
    assert "status mismatch" not in symptoms


@pytest.mark.parametrize(
    ("status", "failure_type"),
    [("EXECUTION_FAILED", "NETWORK_ERROR"), ("TIMEOUT", "TIMEOUT")],
)
def test_execution_failure_and_timeout_are_canonicalized(
    status: str,
    failure_type: str,
) -> None:
    payload = report_payload()
    payload["status"] = status
    payload["summary"]["failureType"] = failure_type
    case = payload["cases"][0]
    case["status"] = status
    case["failureType"] = failure_type
    step = case["steps"][0]
    step["status"] = status
    step["failureType"] = failure_type
    step["responseStatusCode"] = None
    step["assertionResults"] = []

    symptoms = build_memory_symptoms(make_report(payload))

    assert f"run_status:{status}" in symptoms
    assert f"summary_failure_type:{failure_type}" in symptoms
    assert f"case_failure_type:{failure_type}" in symptoms
    assert f"step_failure_type:{failure_type}" in symptoms


def test_multiple_cases_and_steps_are_order_independent_and_deduplicated() -> None:
    payload = report_payload()
    failed_case = payload["cases"][0]
    duplicate_step = deepcopy(failed_case["steps"][0])
    failed_case["steps"].append(duplicate_step)
    reordered = deepcopy(payload)
    reordered["cases"] = list(reversed(reordered["cases"]))
    reordered["cases"][1]["steps"] = list(reversed(reordered["cases"][1]["steps"]))

    original = build_memory_symptoms(make_report(payload))
    changed_order = build_memory_symptoms(make_report(reordered))

    assert original == changed_order
    assert original.count("step_failure_type:ASSERTION_MISMATCH") == 1
    assert original.count("response_status_code:500") == 1


def test_success_none_cases_and_steps_do_not_add_symptoms() -> None:
    payload = report_payload()
    payload["status"] = "SUCCESS"
    payload["summary"]["failureType"] = "NONE"
    payload["cases"] = [
        {
            "caseId": "case-passed",
            "status": "SUCCESS",
            "failureType": "NONE",
            "steps": [
                {
                    "stepId": "step-passed",
                    "status": "SUCCESS",
                    "failureType": "NONE",
                    "responseStatusCode": 200,
                    "durationMs": 5,
                    "assertionResults": [],
                }
            ],
        }
    ]

    assert build_memory_symptoms(make_report(payload)) == (
        "run_status:SUCCESS",
        "summary_failure_type:NONE",
    )


def test_failed_assertion_type_is_kept_but_message_expected_and_actual_are_ignored() -> None:
    first_payload = report_payload()
    second_payload = deepcopy(first_payload)
    assertion = second_payload["cases"][0]["steps"][0]["assertionResults"][0]
    assertion["message"] = "different generated wording"
    assertion["expected"] = 201
    assertion["actual"] = 503

    first = build_memory_symptoms(make_report(first_payload))
    second = build_memory_symptoms(make_report(second_payload))

    assert first == second
    assert "assertion_type:STATUS_CODE" in first
    assert all("different generated wording" not in atom for atom in first)


def test_run_instance_identity_does_not_change_symptoms() -> None:
    first_payload = report_payload()
    second_payload = deepcopy(first_payload)
    second_payload.update(
        {
            "runId": 999,
            "reportId": "report:999",
            "startedAt": "2027-01-01T00:00:00Z",
            "finishedAt": "2027-01-01T00:01:00Z",
        }
    )

    assert build_memory_symptoms(make_report(first_payload)) == build_memory_symptoms(
        make_report(second_payload)
    )


def test_result_has_no_empty_atoms_or_non_contract_fields() -> None:
    symptoms = build_memory_symptoms(make_report())
    allowed_prefixes = (
        "run_status:",
        "summary_failure_type:",
        "case_failure_type:",
        "step_failure_type:",
        "response_status_code:",
        "assertion_type:",
    )

    assert all(symptom for symptom in symptoms)
    assert all(symptom.startswith(allowed_prefixes) for symptom in symptoms)
    assert all("root cause" not in symptom for symptom in symptoms)
    assert all("status mismatch" not in symptom for symptom in symptoms)


def diagnosis_candidate(*root_causes: str) -> DiagnosisReport:
    return DiagnosisReport.model_validate(
        {
            "schemaVersion": "0.1.0",
            "reportId": "report:701",
            "agentRunId": "agent-run-20",
            "projectId": 41,
            "runId": 701,
            "failureType": "ASSERTION_MISMATCH",
            "summary": "The status assertion failed.",
            "rootCauseHypotheses": [
                {
                    "statement": root_cause,
                    "confidence": "MEDIUM",
                    "evidenceRefs": [{"itemId": "report:701"}],
                }
                for root_cause in root_causes
            ],
            "sufficientEvidence": True,
            "limitations": [],
            "recommendedChecks": ["Inspect the endpoint."],
            "traceId": "trace-20",
        }
    )


def memory_entry(*, project_id: int = 41, root_cause: str) -> tuple[InMemoryMemoryStore, object]:
    store = InMemoryMemoryStore()
    candidate = HistoricalFailureMemoryCandidate(
        project_id=project_id,
        api_id="api-orders",
        summary="prior failure",
        symptoms=list(build_memory_symptoms(make_report())),
        root_cause=root_cause,
        resolution="inspect the endpoint",
        source_run_id=700,
        verification_status=VerificationStatus.VERIFIED,
    )
    decision = MemoryWritePolicy(store).write(candidate, project_id=project_id)
    assert decision.entry is not None
    return store, decision.entry


class RecordingRetriever(MemoryRetriever):
    def __init__(self, entry: object) -> None:
        super().__init__(InMemoryMemoryStore())
        self.entry = entry
        self.calls: list[dict[str, object]] = []

    def retrieve_similar(self, **kwargs: object) -> list[object]:
        self.calls.append(kwargs)
        return [self.entry]


def test_recall_uses_exact_identity_and_deduplicates_memory_ids() -> None:
    root_cause = "The endpoint returned an unexpected server response."
    _, entry = memory_entry(root_cause=root_cause)
    retriever = RecordingRetriever(entry)
    candidate = diagnosis_candidate(root_cause, "A second possible endpoint failure.")

    matches = recall_historical_memory(
        project_id=41,
        api_id="api-orders",
        report=make_report(),
        candidate=candidate,
        retriever=retriever,
    )

    assert matches == (entry,)
    assert len(retriever.calls) == 2
    assert retriever.calls[0] == {
        "project_id": 41,
        "api_id": "api-orders",
        "symptoms": build_memory_symptoms(make_report()),
        "root_cause": root_cause,
    }
    assert retriever.calls[1]["project_id"] == 41
    assert retriever.calls[1]["api_id"] == "api-orders"
    assert retriever.calls[1]["symptoms"] == build_memory_symptoms(make_report())


def test_recall_rejects_cross_project_and_non_active_entries() -> None:
    root_cause = "The endpoint returned an unexpected server response."
    _, cross_project = memory_entry(project_id=202, root_cause=root_cause)
    cross_project_result = recall_historical_memory(
        project_id=41,
        api_id="api-orders",
        report=make_report(),
        candidate=diagnosis_candidate(root_cause),
        retriever=RecordingRetriever(cross_project),
    )
    assert cross_project_result == ()

    store, active = memory_entry(root_cause=root_cause)
    retriever = MemoryRetriever(store)
    assert recall_historical_memory(
        project_id=41,
        api_id="api-orders",
        report=make_report(),
        candidate=diagnosis_candidate(root_cause),
        retriever=retriever,
    ) == (active,)
    store.update_lifecycle(active.memory_id, MemoryLifecycleStatus.STALE)
    assert (
        recall_historical_memory(
            project_id=41,
            api_id="api-orders",
            report=make_report(),
            candidate=diagnosis_candidate(root_cause),
            retriever=retriever,
        )
        == ()
    )


def test_recall_fails_closed_when_memory_infrastructure_is_unavailable() -> None:
    class BrokenStore(InMemoryMemoryStore):
        def find_by_failure_fingerprint(self, **kwargs: object) -> list[object]:
            del kwargs
            raise sqlite3.OperationalError("memory unavailable")

    root_cause = "The endpoint returned an unexpected server response."
    result = recall_historical_memory(
        project_id=41,
        api_id="api-orders",
        report=make_report(),
        candidate=diagnosis_candidate(root_cause),
        retriever=MemoryRetriever(BrokenStore()),
    )

    assert result == ()
