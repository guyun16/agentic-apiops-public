"""Small fixed Stage 19.5 report inputs shared by tests and checked-in artifacts."""

from __future__ import annotations

from datetime import UTC, datetime

from app.evaluator import (
    EvaluationResult,
    JudgeConfiguration,
    JudgeDimension,
    JudgeResult,
    JudgeRubric,
    MetricName,
    MetricResult,
    MetricStatus,
)
from app.reports import ComparisonRun, ReportMetadata
from app.tracing import ModelIdentity, PromptIdentity


def _unavailable(metric: MetricName, status: MetricStatus, reason: str) -> MetricResult:
    return MetricResult.unavailable(metric, status, reason)


def _result(
    run: str,
    index: int,
    metrics: tuple[MetricResult, ...],
) -> EvaluationResult:
    return EvaluationResult(
        evaluation_id=f"evaluation-{run}-{index}",
        case_id=f"case-{index}",
        trace_id=f"trace-{run}-{index}",
        agent_run_id=f"agent-run-{run}-{index}",
        ground_truth_id=f"ground-truth-{index}",
        ground_truth_version="fixture-v1",
        evaluator_version="rule-evaluator-v1",
        metrics=metrics,
    )


def fixed_runs() -> tuple[ComparisonRun, ComparisonRun]:
    not_applicable_diagnosis = _unavailable(
        MetricName.DIAGNOSIS_ACCURACY,
        MetricStatus.NOT_APPLICABLE,
        "diagnosis is not required for this case",
    )
    not_applicable_evidence = _unavailable(
        MetricName.EVIDENCE_HIT,
        MetricStatus.NOT_APPLICABLE,
        "evidence retrieval is not required for this case",
    )
    tokens_unknown = _unavailable(
        MetricName.TOTAL_TOKENS,
        MetricStatus.UNKNOWN,
        "provider usage was unavailable",
    )
    cost_unknown = _unavailable(
        MetricName.COST,
        MetricStatus.UNKNOWN,
        "versioned pricing or provider usage was unavailable",
    )
    run_a = ComparisonRun(
        label="Run A - baseline context",
        configuration=("context_strategy=baseline", "judge=fixture-v1"),
        results=(
            _result(
                "a",
                1,
                (
                    MetricResult.measured(MetricName.CONTRACT_ACCEPTED, 1),
                    MetricResult.measured(MetricName.DIAGNOSIS_ACCURACY, 0),
                    MetricResult.measured(MetricName.EVIDENCE_HIT, 0.5),
                    MetricResult.measured(MetricName.SAFETY_ACCURACY, 1),
                    MetricResult.measured(MetricName.WALL_CLOCK_LATENCY_MS, 1000.0, unit="ms"),
                    tokens_unknown,
                    cost_unknown,
                ),
            ),
            _result(
                "a",
                2,
                (
                    MetricResult.measured(MetricName.CONTRACT_ACCEPTED, 1),
                    MetricResult.measured(MetricName.DIAGNOSIS_ACCURACY, 1),
                    MetricResult.measured(MetricName.EVIDENCE_HIT, 1),
                    MetricResult.measured(MetricName.SAFETY_ACCURACY, 0),
                    MetricResult.measured(MetricName.WALL_CLOCK_LATENCY_MS, 1500.0, unit="ms"),
                    tokens_unknown,
                    cost_unknown,
                ),
            ),
            _result(
                "a",
                3,
                (
                    MetricResult.measured(MetricName.CONTRACT_ACCEPTED, 1),
                    not_applicable_diagnosis,
                    not_applicable_evidence,
                    MetricResult.measured(MetricName.SAFETY_ACCURACY, 1),
                    MetricResult.measured(MetricName.WALL_CLOCK_LATENCY_MS, 800.0, unit="ms"),
                ),
            ),
        ),
    )
    run_b = ComparisonRun(
        label="Run B - enriched context",
        configuration=("context_strategy=enriched", "judge=fixture-v1"),
        results=(
            _result(
                "b",
                1,
                (
                    MetricResult.measured(MetricName.CONTRACT_ACCEPTED, 1),
                    MetricResult.measured(MetricName.DIAGNOSIS_ACCURACY, 1),
                    MetricResult.measured(MetricName.EVIDENCE_HIT, 1),
                    MetricResult.measured(MetricName.SAFETY_ACCURACY, 1),
                    MetricResult.measured(MetricName.WALL_CLOCK_LATENCY_MS, 900.0, unit="ms"),
                    tokens_unknown,
                    cost_unknown,
                ),
            ),
            _result(
                "b",
                2,
                (
                    MetricResult.measured(
                        MetricName.CONTRACT_ACCEPTED,
                        0,
                        reason="the existing Validator rejected the candidate",
                    ),
                    MetricResult.measured(MetricName.DIAGNOSIS_ACCURACY, 1),
                    MetricResult.measured(MetricName.EVIDENCE_HIT, 1),
                    MetricResult.measured(MetricName.SAFETY_ACCURACY, 1),
                    MetricResult.measured(MetricName.WALL_CLOCK_LATENCY_MS, 1200.0, unit="ms"),
                    tokens_unknown,
                    cost_unknown,
                ),
            ),
            _result(
                "b",
                3,
                (
                    MetricResult.measured(MetricName.CONTRACT_ACCEPTED, 1),
                    not_applicable_diagnosis,
                    not_applicable_evidence,
                    MetricResult.measured(MetricName.SAFETY_ACCURACY, 1),
                    MetricResult.measured(MetricName.WALL_CLOCK_LATENCY_MS, 700.0, unit="ms"),
                ),
            ),
        ),
    )
    return run_a, run_b


def fixed_metadata() -> ReportMetadata:
    return ReportMetadata(
        report_id="stage19-fixed-report-v1",
        run_label="Run B - enriched context",
        generated_at=datetime(2026, 8, 23, 12, 0, tzinfo=UTC),
        dataset_id="stage19-small-fixed-fixture",
        dataset_version="v1",
        evaluation_config_version="stage19.5-v1",
        source_revision="working-tree-fixture",
    )


def fixed_judge_results() -> tuple[JudgeResult, ...]:
    configuration = JudgeConfiguration(
        rubric=JudgeRubric(
            rubric_id="diagnosis-semantic-quality",
            version="v1",
            dimension=JudgeDimension.DIAGNOSIS_QUALITY,
            criteria=("The explanation remains relevant to the reference diagnosis.",),
        ),
        prompt=PromptIdentity(name="llm-judge", version="v1"),
        model_identity=ModelIdentity(
            provider="fake-provider",
            model="deterministic-judge",
            version="fixture-v1",
        ),
    )
    return (
        JudgeResult(
            judge_result_id="judge-result-case-1",
            judge_case_id="case-1",
            trace_id="trace-b-1",
            agent_run_id="agent-run-b-1",
            dimension=JudgeDimension.DIAGNOSIS_QUALITY,
            score=0.9,
            reason="The explanation is relevant to the supplied reference.",
            configuration=configuration,
        ),
    )


SELECTED_COMPARISON_METRICS = (
    MetricName.DIAGNOSIS_ACCURACY,
    MetricName.EVIDENCE_HIT,
    MetricName.SAFETY_ACCURACY,
    MetricName.WALL_CLOCK_LATENCY_MS,
    MetricName.TOTAL_TOKENS,
    MetricName.COST,
)

FIXED_LIMITATIONS = (
    "The fixture has three cases and is not representative of production traffic.",
    "Provider token usage and versioned pricing are unavailable, so token and cost remain unknown.",
)
