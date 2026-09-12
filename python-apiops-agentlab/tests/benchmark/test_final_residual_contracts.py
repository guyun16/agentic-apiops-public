"""Contract corrections retain exact business and transport distinctions."""

from __future__ import annotations

import pytest

from app.benchmark import load_dataset
from app.benchmark.generation_inputs import resolve_generation_metadata_input
from app.benchmark.models import JavaResourceReference
from app.evaluator import (
    EvaluationCase,
    EvaluationFacts,
    MetricName,
    MetricStatus,
    RuleBasedEvaluator,
    StructuredFact,
)


def _truth(truth_id):
    return next(t for t in load_dataset().ground_truths if t.ground_truth_id == truth_id)


def _evaluate(truth, facts, metric):
    case = EvaluationCase(
        case_id="contract-counterexample",
        trace_id="contract-trace",
        agent_run_id="contract-run",
        ground_truth_id=truth.ground_truth_id,
        ground_truth_version=truth.version,
        facts=facts,
        applicable_metrics=(metric,),
    )
    return next(
        item
        for item in RuleBasedEvaluator().evaluate(case, truth, ()).metrics
        if item.metric is metric
    )


@pytest.mark.parametrize(
    ("observed", "accepted"),
    [("CONNECT_ERROR", 1), ("DNS_ERROR", 1), ("HTTP_ERROR", 0), ("ASSERTION_MISMATCH", 0)],
)
def test_dns_contract_accepts_only_explicit_transport_classes(observed, accepted):
    truth = _truth("gt_stage21_formal_failure_transport_dns")
    result = _evaluate(truth, EvaluationFacts(diagnosis=observed), MetricName.DIAGNOSIS_ACCURACY)
    assert result.value == accepted


@pytest.mark.parametrize(
    ("business_code", "accepted"),
    [("ORDER_BUSINESS_CONFLICT", True), ("INVENTORY_NOT_ENOUGH", False), ("ORDER_SUCCESS", False)],
)
def test_inventory_boundary_contract_rejects_legacy_or_success_code(business_code, accepted):
    truth = _truth("gt_stage21_formal_testcase_boundary_inventory_zero")
    facts = EvaluationFacts(
        structured_facts=tuple(
            StructuredFact(
                name=fact.name, value=business_code if fact.name == "business_error" else fact.value
            )
            for fact in truth.expected_facts
        )
    )
    result = _evaluate(truth, facts, MetricName.EXACT_MATCH)
    assert (result.value == 1) is accepted


@pytest.mark.parametrize(
    ("changed_name", "changed_value"),
    [
        ("java_runner_status", "ASSERTION_FAILED"),
        ("business_outcome", "ORDER_SUCCESS"),
        ("expected_http_status", 200),
    ],
)
def test_negative_e2e_requires_passing_assertions_and_rejected_business(
    changed_name, changed_value
):
    truth = _truth("gt_stage21_e2e_apiops")
    correct = EvaluationFacts(structured_facts=truth.expected_facts)
    assert _evaluate(truth, correct, MetricName.EXACT_MATCH).value == 1
    changed = correct.model_copy(
        update={
            "structured_facts": tuple(
                StructuredFact(
                    name=fact.name, value=changed_value if fact.name == changed_name else fact.value
                )
                for fact in truth.expected_facts
            )
        }
    )
    assert _evaluate(truth, changed, MetricName.EXACT_MATCH).value != 1
    assert (
        _evaluate(
            truth,
            EvaluationFacts(diagnosis="DATABASE_CONSTRAINT_ERROR"),
            MetricName.DIAGNOSIS_ACCURACY,
        ).value
        == 0
    )


def test_e2e_selects_exact_contract_facts_and_current_java_evidence():
    task = next(
        t for t in load_dataset().tasks if t.benchmark_task_id == "bench_task_golden_e2e_apiops"
    )
    truth = _truth("gt_stage21_e2e_apiops")
    assert MetricName.EXACT_MATCH in task.evaluation_spec.selected_metrics
    assert truth.expected_evidence_ids == (
        "CURRENT_JAVA_REPORT",
        "stage21-rag-v2/project-41/api-contract-and-testcase-runbook",
    )
    assert truth.acceptable_diagnosis_alternatives == ()


@pytest.mark.parametrize(
    ("task_id", "truth_id"),
    [
        (
            "bench_task_formal_testcase_business_inventory_expected",
            "gt_stage21_formal_testcase_business_inventory_expected",
        ),
        (
            "bench_task_formal_testcase_inventory_conflict_metadata",
            "gt_stage21_formal_testcase_inventory_conflict_metadata",
        ),
        (
            "bench_task_testcase_business_inventory_python",
            "gt_stage21_testcase_business_inventory_python",
        ),
    ],
)
def test_final_business_contract_uses_java_metadata_and_rejects_wrong_or_missing_code(
    task_id, truth_id
):
    task = next(t for t in load_dataset().tasks if t.benchmark_task_id == task_id)
    truth = _truth(truth_id)
    assert truth.version == task.ground_truth_ref.version == "v2"
    assert [
        entry.ref
        for entry in task.initial_state.entries
        if isinstance(entry, JavaResourceReference)
    ] == ["java://metadata/project-41/formal-final-acceptance"]
    # This input must be fetched from Java, not silently substituted by the local resolver.
    assert resolve_generation_metadata_input(task) is None
    correct = EvaluationFacts(structured_facts=truth.expected_facts)
    assert _evaluate(truth, correct, MetricName.EXACT_MATCH).value == 1
    for wrong_code in ("INVENTORY_NOT_ENOUGH", "ORDER_SUCCESS", "AUTH_UNAUTHORIZED"):
        changed = correct.model_copy(
            update={
                "structured_facts": tuple(
                    StructuredFact(
                        name=fact.name,
                        value=wrong_code if fact.name == "business_error" else fact.value,
                    )
                    for fact in truth.expected_facts
                )
            }
        )
        assert _evaluate(truth, changed, MetricName.EXACT_MATCH).value != 1
    missing = correct.model_copy(
        update={
            "structured_facts": tuple(
                fact for fact in truth.expected_facts if fact.name != "business_error"
            )
        }
    )
    result = _evaluate(truth, missing, MetricName.EXACT_MATCH)
    assert result.status is MetricStatus.UNKNOWN
    assert result.value is None
