from __future__ import annotations

from app.evaluator import (
    EvaluationCase,
    EvaluationFacts,
    GroundTruth,
    MetricName,
    RuleBasedEvaluator,
)


def _metric(result: object, name: MetricName):
    return next(item for item in result.metrics if item.metric is name)  # type: ignore[attr-defined]


def test_existing_stage19_evaluator_matches_opaque_report_ids() -> None:
    truth = GroundTruth(
        ground_truth_id="stage19-evidence-test",
        version="test-v1",
        expected_evidence_ids=("report:test-evidence-1", "rag:orders-unique-index"),
    )
    hit_case = EvaluationCase(
        case_id="case-stage19-evidence-hit",
        trace_id="trace-stage19-evidence-hit",
        agent_run_id="agent-stage19-evidence-hit",
        ground_truth_id=truth.ground_truth_id,
        ground_truth_version=truth.version,
        facts=EvaluationFacts(
            evidence_ids=("report:test-evidence-1", "rag:orders-unique-index"),
        ),
        applicable_metrics=(MetricName.EVIDENCE_HIT,),
    )
    miss_case = hit_case.model_copy(
        update={
            "case_id": "case-stage19-evidence-miss",
            "trace_id": "trace-stage19-evidence-miss",
            "agent_run_id": "agent-stage19-evidence-miss",
            "facts": EvaluationFacts(
                evidence_ids=("report:test-evidence-2", "rag:orders-unique-index"),
            ),
        }
    )

    evaluator = RuleBasedEvaluator()
    result = evaluator.evaluate(hit_case, truth, ())
    miss = evaluator.evaluate(miss_case, truth, ())

    assert result.evaluator_version == "rule-evaluator-v1"
    assert result.ground_truth_id == truth.ground_truth_id
    assert _metric(result, MetricName.EVIDENCE_HIT).value == 1.0
    assert _metric(miss, MetricName.EVIDENCE_HIT).value == 0.5
