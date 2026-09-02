from __future__ import annotations

import pytest

from app.evaluator import (
    EvaluationResult,
    MetricName,
    MetricResult,
    MetricsCalculator,
    MetricStatus,
)


def evaluation_result(index: int, metric: MetricResult) -> EvaluationResult:
    return EvaluationResult(
        evaluation_id=f"evaluation-{index}",
        case_id=f"case-{index}",
        trace_id=f"trace-{index}",
        agent_run_id=f"run-{index}",
        ground_truth_id="gt",
        ground_truth_version="v1",
        evaluator_version="rule-evaluator-v1",
        metrics=(metric,),
    )


def test_metrics_calculator_excludes_na_and_preserves_unknown_counts() -> None:
    results = (
        evaluation_result(1, MetricResult.measured(MetricName.DIAGNOSIS_ACCURACY, 1)),
        evaluation_result(2, MetricResult.measured(MetricName.DIAGNOSIS_ACCURACY, 0)),
        evaluation_result(
            3,
            MetricResult.unavailable(
                MetricName.DIAGNOSIS_ACCURACY,
                MetricStatus.NOT_APPLICABLE,
                "diagnosis not required",
            ),
        ),
        evaluation_result(4, MetricResult.measured(MetricName.DIAGNOSIS_ACCURACY, 1)),
        evaluation_result(
            5,
            MetricResult.unavailable(
                MetricName.DIAGNOSIS_ACCURACY,
                MetricStatus.UNKNOWN,
                "diagnosis fact missing",
            ),
        ),
    )

    summary = MetricsCalculator().calculate(results)
    diagnosis = summary.metrics[0]

    assert summary.case_count == 5
    assert diagnosis.total_count == 5
    assert diagnosis.applicable_count == 4
    assert diagnosis.value_count == 3
    assert diagnosis.not_applicable_count == 1
    assert diagnosis.unknown_count == 1
    assert diagnosis.error_count == 0
    assert diagnosis.rate == pytest.approx(2 / 3)
    assert diagnosis.mean == pytest.approx(2 / 3)


def test_metrics_calculator_counts_error_separately_from_zero_score() -> None:
    results = (
        evaluation_result(1, MetricResult.measured(MetricName.SAFETY_ACCURACY, 0)),
        evaluation_result(
            2,
            MetricResult.unavailable(
                MetricName.SAFETY_ACCURACY,
                MetricStatus.ERROR,
                "evaluator failed",
            ),
        ),
    )

    safety = MetricsCalculator().calculate(results).metrics[0]

    assert safety.value_count == 1
    assert safety.error_count == 1
    assert safety.mean == 0.0
    assert safety.rate == 0.0


def test_latency_mean_uses_known_samples_without_calling_it_a_rate() -> None:
    results = (
        evaluation_result(
            1,
            MetricResult.measured(MetricName.WALL_CLOCK_LATENCY_MS, 100.0),
        ),
        evaluation_result(
            2,
            MetricResult.measured(MetricName.WALL_CLOCK_LATENCY_MS, 300.0),
        ),
        evaluation_result(
            3,
            MetricResult.unavailable(
                MetricName.WALL_CLOCK_LATENCY_MS,
                MetricStatus.UNKNOWN,
                "timestamp missing",
            ),
        ),
    )

    latency = MetricsCalculator().calculate(results).metrics[0]

    assert latency.value_count == 2
    assert latency.unknown_count == 1
    assert latency.mean == 200.0
    assert latency.rate is None


def test_aggregation_is_deterministic_and_rejects_mixed_evaluator_versions() -> None:
    result = evaluation_result(1, MetricResult.measured(MetricName.VALID_JSON, 1))
    calculator = MetricsCalculator()

    assert calculator.calculate((result,)) == calculator.calculate((result,))
    incompatible = result.model_copy(update={"evaluator_version": "rule-evaluator-v2"})
    with pytest.raises(ValueError, match="mixed evaluator versions"):
        calculator.calculate((result, incompatible))


def test_cost_aggregation_rejects_mixed_currencies() -> None:
    usd = evaluation_result(
        1,
        MetricResult.measured(MetricName.COST, 0.5, unit="USD"),
    )
    eur = evaluation_result(
        2,
        MetricResult.measured(MetricName.COST, 0.4, unit="EUR"),
    )

    with pytest.raises(ValueError, match="mixed units"):
        MetricsCalculator().calculate((usd, eur))


def test_empty_aggregation_has_no_fabricated_metrics() -> None:
    summary = MetricsCalculator().calculate(())

    assert summary.case_count == 0
    assert summary.evaluator_version is None
    assert summary.metrics == ()
