"""Shared DiagnosisReport compatibility and citation-boundary tests."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.schemas.diagnosis_report import DiagnosisReport

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
EXAMPLES_ROOT = REPOSITORY_ROOT / "examples"
VALID_FIXTURE = EXAMPLES_ROOT / "diagnosis-report-valid.json"

FAILURE_TYPES = (
    "NONE",
    "ASSERTION_MISMATCH",
    "ASSERTION_EVALUATION_ERROR",
    "HTTP_STATUS_ERROR",
    "TIMEOUT",
    "NETWORK_ERROR",
    "REQUEST_BUILD_ERROR",
    "INVALID_TARGET_URI",
    "DNS_ERROR",
    "CONNECT_ERROR",
    "TLS_ERROR",
    "IO_ERROR",
    "SCHEMA_INVALID",
    "BUSINESS_ERROR",
    "TOOL_ERROR",
    "SYSTEM_ERROR",
    "UNKNOWN",
    "ASSERTION_FAILED",
    "AUTH_ERROR",
    "VALIDATION_ERROR",
    "DATABASE_CONSTRAINT_ERROR",
    "UPSTREAM_SERVICE_ERROR",
)
CONFIDENCES = ("LOW", "MEDIUM", "HIGH")
TOP_LEVEL_REQUIRED_FIELDS = (
    "schemaVersion",
    "reportId",
    "agentRunId",
    "projectId",
    "runId",
    "failureType",
    "summary",
    "rootCauseHypotheses",
    "sufficientEvidence",
    "limitations",
    "recommendedChecks",
    "traceId",
)


def load_fixture(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def test_canonical_diagnosis_report_fixture_passes() -> None:
    model = DiagnosisReport.model_validate(load_fixture(VALID_FIXTURE))

    assert model.schema_version == "0.1.0"
    assert model.report_id == "report:1001001"
    assert model.project_id == 1001
    assert model.run_id == 1001001
    assert model.failure_type == "DATABASE_CONSTRAINT_ERROR"
    assert model.root_cause_hypotheses[0].evidence_refs[0].item_id == "chunk:chunk-1"


def test_canonical_round_trip_preserves_aliases_and_citations() -> None:
    fixture = load_fixture(VALID_FIXTURE)
    dumped = DiagnosisReport.model_validate(fixture).model_dump(by_alias=True)

    assert dumped == fixture
    assert dumped["schemaVersion"] == "0.1.0"
    assert dumped["reportId"] == "report:1001001"
    assert dumped["agentRunId"] == "agent_run_001"
    assert dumped["projectId"] == 1001
    assert dumped["runId"] == 1001001
    assert dumped["failureType"] == "DATABASE_CONSTRAINT_ERROR"
    assert dumped["summary"] == fixture["summary"]
    assert dumped["rootCauseHypotheses"][0]["evidenceRefs"][0]["itemId"] == "chunk:chunk-1"
    assert dumped["sufficientEvidence"] is True
    assert dumped["limitations"] == []
    assert dumped["recommendedChecks"] == fixture["recommendedChecks"]
    assert dumped["traceId"] == "trace_001"
    assert "root_cause_hypotheses" not in dumped


@pytest.mark.parametrize("field", TOP_LEVEL_REQUIRED_FIELDS)
def test_top_level_required_fields_cannot_be_missing(field: str) -> None:
    payload = load_fixture(VALID_FIXTURE)
    del payload[field]

    with pytest.raises(ValidationError):
        DiagnosisReport.model_validate(payload)


def test_schema_version_must_be_the_shared_constant() -> None:
    payload = load_fixture(VALID_FIXTURE)
    payload["schemaVersion"] = "1.0.0"

    with pytest.raises(ValidationError):
        DiagnosisReport.model_validate(payload)


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("reportId", ""),
        ("reportId", 123),
        ("agentRunId", True),
        ("summary", 123),
        ("traceId", 123),
    ),
)
def test_string_fields_reject_empty_values_and_coercion(field: str, value: object) -> None:
    payload = load_fixture(VALID_FIXTURE)
    payload[field] = value

    with pytest.raises(ValidationError):
        DiagnosisReport.model_validate(payload)


def test_positive_project_and_run_ids_are_valid() -> None:
    payload = load_fixture(VALID_FIXTURE)
    payload["projectId"] = 1
    payload["runId"] = 1

    model = DiagnosisReport.model_validate(payload)

    assert model.project_id == 1
    assert model.run_id == 1


@pytest.mark.parametrize("project_id", ("1", True, 0, -1))
def test_project_id_requires_strict_positive_integer(project_id: object) -> None:
    payload = load_fixture(VALID_FIXTURE)
    payload["projectId"] = project_id

    with pytest.raises(ValidationError):
        DiagnosisReport.model_validate(payload)


@pytest.mark.parametrize("run_id", ("1", True, 0, -1))
def test_run_id_requires_strict_positive_integer(run_id: object) -> None:
    payload = load_fixture(VALID_FIXTURE)
    payload["runId"] = run_id

    with pytest.raises(ValidationError):
        DiagnosisReport.model_validate(payload)


@pytest.mark.parametrize("failure_type", FAILURE_TYPES)
def test_all_shared_failure_types_are_accepted(failure_type: str) -> None:
    payload = load_fixture(VALID_FIXTURE)
    payload["failureType"] = failure_type

    model = DiagnosisReport.model_validate(payload)

    assert model.failure_type == failure_type


@pytest.mark.parametrize("failure_type", ("RETRYING", "FAIL", "assertion_failed", "banana"))
def test_unknown_failure_type_is_rejected_without_normalization(failure_type: str) -> None:
    payload = load_fixture(VALID_FIXTURE)
    payload["failureType"] = failure_type

    with pytest.raises(ValidationError):
        DiagnosisReport.model_validate(payload)


@pytest.mark.parametrize("sufficient_evidence", (True, False))
def test_sufficient_evidence_accepts_strict_boolean(sufficient_evidence: bool) -> None:
    payload = load_fixture(VALID_FIXTURE)
    payload["sufficientEvidence"] = sufficient_evidence

    model = DiagnosisReport.model_validate(payload)

    assert model.sufficient_evidence is sufficient_evidence


@pytest.mark.parametrize("sufficient_evidence", (1, 0, "true", "false"))
def test_sufficient_evidence_rejects_non_boolean_coercion(sufficient_evidence: object) -> None:
    payload = load_fixture(VALID_FIXTURE)
    payload["sufficientEvidence"] = sufficient_evidence

    with pytest.raises(ValidationError):
        DiagnosisReport.model_validate(payload)


def test_required_arrays_allow_empty_values() -> None:
    payload = load_fixture(VALID_FIXTURE)
    payload["rootCauseHypotheses"] = []
    payload["limitations"] = []
    payload["recommendedChecks"] = []

    model = DiagnosisReport.model_validate(payload)

    assert model.root_cause_hypotheses == []
    assert model.limitations == []
    assert model.recommended_checks == []


def test_insufficient_evidence_can_have_no_root_cause_hypotheses() -> None:
    payload = load_fixture(VALID_FIXTURE)
    payload["rootCauseHypotheses"] = []
    payload["sufficientEvidence"] = False
    payload["limitations"] = ["The available evidence is insufficient."]
    payload["recommendedChecks"] = ["Collect the failing run logs."]

    model = DiagnosisReport.model_validate(payload)

    assert model.root_cause_hypotheses == []
    assert model.sufficient_evidence is False


@pytest.mark.parametrize("field", ("limitations", "recommendedChecks"))
def test_required_string_arrays_reject_empty_items(field: str) -> None:
    payload = load_fixture(VALID_FIXTURE)
    payload[field] = [""]

    with pytest.raises(ValidationError):
        DiagnosisReport.model_validate(payload)


@pytest.mark.parametrize("confidence", CONFIDENCES)
def test_all_shared_confidences_are_accepted(confidence: str) -> None:
    payload = load_fixture(VALID_FIXTURE)
    payload["rootCauseHypotheses"][0]["confidence"] = confidence

    model = DiagnosisReport.model_validate(payload)

    assert model.root_cause_hypotheses[0].confidence == confidence


@pytest.mark.parametrize("confidence", ("low", "VERY_HIGH", "UNKNOWN", "banana"))
def test_unknown_confidence_is_rejected_without_normalization(confidence: str) -> None:
    payload = load_fixture(VALID_FIXTURE)
    payload["rootCauseHypotheses"][0]["confidence"] = confidence

    with pytest.raises(ValidationError):
        DiagnosisReport.model_validate(payload)


def test_root_cause_hypothesis_requires_non_empty_statement() -> None:
    payload = load_fixture(VALID_FIXTURE)
    payload["rootCauseHypotheses"][0]["statement"] = ""

    with pytest.raises(ValidationError):
        DiagnosisReport.model_validate(payload)


@pytest.mark.parametrize("field", ("statement", "confidence", "evidenceRefs"))
def test_root_cause_hypothesis_required_fields_cannot_be_missing(field: str) -> None:
    payload = load_fixture(VALID_FIXTURE)
    del payload["rootCauseHypotheses"][0][field]

    with pytest.raises(ValidationError):
        DiagnosisReport.model_validate(payload)


def test_root_cause_hypothesis_requires_at_least_one_evidence_ref() -> None:
    payload = load_fixture(VALID_FIXTURE)
    payload["rootCauseHypotheses"][0]["evidenceRefs"] = []

    with pytest.raises(ValidationError):
        DiagnosisReport.model_validate(payload)


def test_evidence_ref_requires_non_empty_item_id() -> None:
    payload = load_fixture(VALID_FIXTURE)
    payload["rootCauseHypotheses"][0]["evidenceRefs"][0]["itemId"] = ""

    with pytest.raises(ValidationError):
        DiagnosisReport.model_validate(payload)


def test_evidence_ref_item_id_cannot_be_missing() -> None:
    payload = load_fixture(VALID_FIXTURE)
    del payload["rootCauseHypotheses"][0]["evidenceRefs"][0]["itemId"]

    with pytest.raises(ValidationError):
        DiagnosisReport.model_validate(payload)


def test_python_structural_validation_does_not_lookup_or_repair_citations() -> None:
    payload = load_fixture(VALID_FIXTURE)
    payload["rootCauseHypotheses"][0]["evidenceRefs"][0]["itemId"] = "chunk:not-in-context"

    model = DiagnosisReport.model_validate(payload)
    dumped = model.model_dump(by_alias=True)

    assert model.root_cause_hypotheses[0].evidence_refs[0].item_id == "chunk:not-in-context"
    assert dumped["rootCauseHypotheses"][0]["evidenceRefs"][0]["itemId"] == "chunk:not-in-context"


def test_top_level_unknown_field_is_rejected() -> None:
    payload = load_fixture(VALID_FIXTURE)
    payload["verified"] = True

    with pytest.raises(ValidationError):
        DiagnosisReport.model_validate(payload)


def test_root_cause_hypothesis_unknown_field_is_rejected() -> None:
    payload = load_fixture(VALID_FIXTURE)
    payload["rootCauseHypotheses"][0]["probability"] = 0.9

    with pytest.raises(ValidationError):
        DiagnosisReport.model_validate(payload)


def test_evidence_ref_unknown_field_is_rejected() -> None:
    payload = load_fixture(VALID_FIXTURE)
    payload["rootCauseHypotheses"][0]["evidenceRefs"][0]["sourceType"] = "RAG"

    with pytest.raises(ValidationError):
        DiagnosisReport.model_validate(payload)


def test_snake_case_input_is_not_silently_accepted() -> None:
    payload = load_fixture(VALID_FIXTURE)
    payload["root_cause_hypotheses"] = payload.pop("rootCauseHypotheses")

    with pytest.raises(ValidationError):
        DiagnosisReport.model_validate(payload)


def test_mutations_do_not_add_python_only_execution_fact_fields() -> None:
    payload = copy.deepcopy(load_fixture(VALID_FIXTURE))
    model = DiagnosisReport.model_validate(payload)
    dumped = model.model_dump(by_alias=True)

    assert "verified" not in dumped
    assert "executionConfirmed" not in dumped
    assert "authoritativeRootCause" not in dumped
