from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.evaluator import (
    EvaluationCase,
    EvaluationFacts,
    EvaluationResult,
    ExpectedToolArguments,
    GroundTruth,
    MetricName,
    MetricResult,
    MetricStatus,
    SafetyOutcome,
)


def test_ground_truth_requires_stable_identity_and_version() -> None:
    truth = GroundTruth(
        ground_truth_id="gt-orders",
        version="2026-08-23",
        expected_tools=("rag.search",),
        expected_tool_arguments=(
            ExpectedToolArguments(
                tool_name="rag.search",
                arguments={"query": "orders"},
            ),
        ),
        expected_evidence_ids=("evidence-orders",),
        expected_diagnosis="SYSTEM_ERROR",
        acceptable_diagnosis_alternatives=("UPSTREAM_SERVICE_ERROR",),
        expected_safety_outcome=SafetyOutcome.SAFE,
    )

    assert truth.ground_truth_id == "gt-orders"
    assert truth.version == "2026-08-23"
    with pytest.raises(ValidationError):
        GroundTruth.model_validate({"version": "v1"})
    with pytest.raises(ValidationError):
        GroundTruth.model_validate({"ground_truth_id": "gt"})


def test_ground_truth_rejects_diagnosis_labels_agent_schema_cannot_emit() -> None:
    with pytest.raises(
        ValidationError,
        match="not expressible by DiagnosisReport.failureType",
    ):
        GroundTruth(
            ground_truth_id="gt-unreachable-diagnosis",
            version="v1",
            expected_diagnosis="HTTP_500_SYSTEM_ERROR",
        )


def test_evaluation_case_correlates_trace_run_and_ground_truth() -> None:
    case = EvaluationCase(
        case_id="case-1",
        trace_id="trace-1",
        agent_run_id="run-1",
        ground_truth_id="gt-1",
        ground_truth_version="v3",
        facts=EvaluationFacts(),
    )

    assert case.trace_id == "trace-1"
    assert case.agent_run_id == "run-1"
    assert case.ground_truth_id == "gt-1"
    assert case.ground_truth_version == "v3"


def test_metric_result_preserves_value_na_unknown_and_error_semantics() -> None:
    value = MetricResult.measured(MetricName.DIAGNOSIS_ACCURACY, 0)
    not_applicable = MetricResult.unavailable(
        MetricName.DIAGNOSIS_ACCURACY,
        MetricStatus.NOT_APPLICABLE,
        "diagnosis is not required",
    )
    unknown = MetricResult.unavailable(
        MetricName.TOTAL_TOKENS,
        MetricStatus.UNKNOWN,
        "provider usage missing",
    )
    error = MetricResult.unavailable(
        MetricName.EXACT_MATCH,
        MetricStatus.ERROR,
        "comparison failed",
    )

    assert value.value == 0
    assert not_applicable.value is None
    assert unknown.value is None
    assert error.value is None
    assert {not_applicable.status, unknown.status, error.status} == {
        MetricStatus.NOT_APPLICABLE,
        MetricStatus.UNKNOWN,
        MetricStatus.ERROR,
    }
    with pytest.raises(ValidationError):
        MetricResult(
            metric=MetricName.TOTAL_TOKENS,
            status=MetricStatus.UNKNOWN,
            value=0,
            reason="must not collapse to zero",
        )


def test_evaluation_result_combines_distinct_metrics() -> None:
    result = EvaluationResult(
        evaluation_id="evaluation-1",
        case_id="case-1",
        trace_id="trace-1",
        agent_run_id="run-1",
        ground_truth_id="gt-1",
        ground_truth_version="v1",
        evaluator_version="rule-v1",
        metrics=(
            MetricResult.measured(MetricName.VALID_JSON, 1),
            MetricResult.measured(MetricName.SCHEMA_VALID, 0),
        ),
    )

    assert [metric.metric for metric in result.metrics] == [
        MetricName.VALID_JSON,
        MetricName.SCHEMA_VALID,
    ]
    with pytest.raises(ValidationError):
        EvaluationResult(
            evaluation_id="evaluation-duplicate",
            case_id="case-1",
            trace_id="trace-1",
            agent_run_id="run-1",
            ground_truth_id="gt-1",
            ground_truth_version="v1",
            evaluator_version="rule-v1",
            metrics=(result.metrics[0], result.metrics[0]),
        )


def test_models_are_strict_and_frozen() -> None:
    result = MetricResult.measured(MetricName.VALID_JSON, 1)
    with pytest.raises(ValidationError):
        MetricResult.model_validate({"metric": "valid_json", "status": "VALUE", "value": "1"})
    with pytest.raises(ValidationError):
        result.value = 0  # type: ignore[misc]
