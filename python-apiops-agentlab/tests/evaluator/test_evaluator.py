from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.evaluator import (
    EvaluationCase,
    EvaluationFacts,
    ExpectedToolArguments,
    GroundTruth,
    MetricName,
    MetricStatus,
    ModelPricing,
    ObservedToolArguments,
    ParameterMatchPolicy,
    RuleBasedEvaluator,
    SafetyOutcome,
    StructuredFact,
    ValidityFacts,
)
from app.guardrails import EvidenceSource, PreflightDecision, ViolationCode
from app.tracing import (
    AgentRun,
    AgentStep,
    ApprovalFact,
    EvidenceReference,
    FailureDetail,
    InterruptFact,
    Latency,
    ModelCall,
    ModelIdentity,
    PayloadDigest,
    PromptIdentity,
    ResumeFact,
    RetrievalFact,
    RetrievalReference,
    SafetyViolationFact,
    TokenUsage,
    ToolIntentRecord,
    ToolResultRecord,
    TraceEvent,
    TraceRecord,
    TraceStatus,
)
from app.workflows.approval import ApprovalAction

T0 = datetime(2026, 8, 23, 1, 0, tzinfo=UTC)


def failure(code: str, category: str = "TEST_FAILURE") -> FailureDetail:
    return FailureDetail(
        failure_category=category,
        failure_code=code,
        message="bounded failure fact",
    )


def run_start(sequence: int = 1) -> AgentRun:
    return AgentRun(
        trace_id="trace-1",
        agent_run_id="run-1",
        sequence=sequence,
        timestamp=T0,
        status=TraceStatus.RUNNING,
    )


def run_terminal(sequence: int, *, seconds: int = 10) -> AgentRun:
    return AgentRun(
        trace_id="trace-1",
        agent_run_id="run-1",
        sequence=sequence,
        timestamp=T0 + timedelta(seconds=seconds),
        event=TraceEvent.TERMINAL,
        status=TraceStatus.SUCCESS,
    )


def validation_step(
    sequence: int,
    *,
    status: TraceStatus = TraceStatus.SUCCESS,
    code: str | None = None,
) -> AgentStep:
    return AgentStep(
        trace_id="trace-1",
        agent_run_id="run-1",
        agent_step_id=f"step-validation-{sequence}",
        sequence=sequence,
        timestamp=T0 + timedelta(seconds=1),
        event=TraceEvent.TERMINAL,
        status=status,
        failure=failure(code or "VALIDATION_FAILED", "VALIDATION_FAILURE")
        if status is not TraceStatus.SUCCESS
        else None,
        step_type="validate",
    )


def model_call(
    sequence: int,
    *,
    usage: TokenUsage | None = None,
    duration_ms: float | None = 150.0,
    version: str | None = "2026-08-01",
) -> ModelCall:
    return ModelCall(
        trace_id="trace-1",
        agent_run_id="run-1",
        agent_step_id="step-generate",
        sequence=sequence,
        timestamp=T0 + timedelta(seconds=2),
        event=TraceEvent.TERMINAL,
        status=TraceStatus.SUCCESS,
        model_call_id="model-call-1",
        model_identity=ModelIdentity(
            provider="provider-a",
            model="model-a",
            version=version,
        ),
        prompt=PromptIdentity(name="generate", version="v1"),
        model_input=PayloadDigest.from_value("safe input summary"),
        model_output=PayloadDigest.from_value("safe output summary"),
        token_usage=usage,
        latency=Latency(duration_ms=duration_ms),
    )


def tool_intent(
    name: str,
    sequence: int,
    *,
    arguments: dict[str, object] | None = None,
    decision: PreflightDecision | None = None,
    status: TraceStatus = TraceStatus.RUNNING,
    failure_code: str | None = None,
) -> ToolIntentRecord:
    return ToolIntentRecord(
        trace_id="trace-1",
        agent_run_id="run-1",
        agent_step_id="step-tool",
        sequence=sequence,
        timestamp=T0 + timedelta(seconds=3),
        status=status,
        failure=failure(failure_code) if failure_code else None,
        tool_intent_id=f"intent-{sequence}",
        tool_name=name,
        arguments_digest=PayloadDigest.from_value(arguments or {}),
        python_decision=decision,
    )


def tool_result(
    name: str,
    sequence: int,
    *,
    status: TraceStatus = TraceStatus.SUCCESS,
    failure_code: str | None = None,
) -> ToolResultRecord:
    return ToolResultRecord(
        trace_id="trace-1",
        agent_run_id="run-1",
        agent_step_id="step-tool",
        sequence=sequence,
        timestamp=T0 + timedelta(seconds=4),
        status=status,
        failure=failure(failure_code) if failure_code else None,
        tool_intent_id="intent-tool",
        tool_name=name,
        java_tool_call_id="java-call-1",
        result_summary="sanitized result",
        sanitized=True,
        truncated=False,
    )


def retrieval(sequence: int, evidence_ids: tuple[str, ...]) -> RetrievalFact:
    return RetrievalFact(
        trace_id="trace-1",
        agent_run_id="run-1",
        agent_step_id="step-retrieve",
        sequence=sequence,
        timestamp=T0 + timedelta(seconds=5),
        status=TraceStatus.SUCCESS,
        retrieval_kind="evidence",
        reference=RetrievalReference(
            evidence_references=tuple(
                EvidenceReference(source_type="RAG", source_id=evidence_id)
                for evidence_id in evidence_ids
            )
        ),
        result_count=len(evidence_ids),
    )


def truth(**updates: object) -> GroundTruth:
    values: dict[str, object] = {
        "ground_truth_id": "gt-1",
        "version": "v1",
    }
    values.update(updates)
    return GroundTruth.model_validate(values)


def evaluation_case(**updates: object) -> EvaluationCase:
    values: dict[str, object] = {
        "case_id": "case-1",
        "trace_id": "trace-1",
        "agent_run_id": "run-1",
        "ground_truth_id": "gt-1",
        "ground_truth_version": "v1",
    }
    values.update(updates)
    return EvaluationCase.model_validate(values)


def metric(result: object, name: MetricName):
    return next(item for item in result.metrics if item.metric is name)  # type: ignore[attr-defined]


def test_validity_layers_are_distinct_and_trace_validation_is_not_modified() -> None:
    validator_fact = validation_step(
        2,
        status=TraceStatus.FAILED,
        code="PROJECT_ID_MISMATCH",
    )
    before = validator_fact.model_dump()
    case = evaluation_case(
        facts=EvaluationFacts(
            validity=ValidityFacts(
                valid_json=True,
                schema_valid=True,
                contract_accepted=True,
            )
        )
    )

    result = RuleBasedEvaluator().evaluate(
        case,
        truth(),
        (run_start(), validator_fact, run_terminal(3)),
    )

    assert metric(result, MetricName.VALID_JSON).value == 1
    assert metric(result, MetricName.SCHEMA_VALID).value == 1
    assert metric(result, MetricName.CONTRACT_ACCEPTED).value == 0
    assert validator_fact.model_dump() == before


def test_invalid_json_and_shared_schema_failure_remain_separate() -> None:
    result = RuleBasedEvaluator().evaluate(
        evaluation_case(facts=EvaluationFacts(validity=ValidityFacts(valid_json=False))),
        truth(),
        (
            run_start(),
            validation_step(2, status=TraceStatus.FAILED, code="SHARED_SCHEMA_REQUIRED"),
            run_terminal(3),
        ),
    )

    assert metric(result, MetricName.VALID_JSON).value == 0
    assert metric(result, MetricName.SCHEMA_VALID).value == 0
    assert metric(result, MetricName.CONTRACT_ACCEPTED).value == 0


def test_success_validation_means_schema_valid_and_contract_accepted() -> None:
    result = RuleBasedEvaluator().evaluate(
        evaluation_case(),
        truth(),
        (run_start(), validation_step(2), run_terminal(3)),
    )

    assert metric(result, MetricName.VALID_JSON).status is MetricStatus.UNKNOWN
    assert metric(result, MetricName.SCHEMA_VALID).value == 1
    assert metric(result, MetricName.CONTRACT_ACCEPTED).value == 1


def test_structured_exact_match_is_deterministic_and_does_not_repair_labels() -> None:
    ground_truth = truth(expected_facts=(StructuredFact(name="status", value="READY"),))
    case = evaluation_case(
        facts=EvaluationFacts(structured_facts=(StructuredFact(name="status", value="ready"),))
    )
    first = RuleBasedEvaluator().evaluate(case, ground_truth, ())
    second = RuleBasedEvaluator().evaluate(case, ground_truth, ())

    assert metric(first, MetricName.EXACT_MATCH).value == 0.0
    assert first == second


def test_structured_exact_known_mismatch_wins_over_missing_authority() -> None:
    ground_truth = truth(
        expected_facts=(
            StructuredFact(name="java_runner_status", value="SUCCESS"),
            StructuredFact(name="business_outcome", value="ORDER_SUCCESS"),
        )
    )
    case = evaluation_case(
        facts=EvaluationFacts(
            structured_facts=(
                StructuredFact(name="java_runner_status", value="ASSERTION_FAILED"),
            )
        )
    )

    result = RuleBasedEvaluator().evaluate(case, ground_truth, ())
    exact = metric(result, MetricName.EXACT_MATCH)

    assert exact.status is MetricStatus.VALUE
    assert exact.value == 0
    assert exact.details == (
        "mismatched=java_runner_status",
        "missing=business_outcome",
    )


def test_structured_exact_matching_observations_with_missing_authority_stay_unknown() -> None:
    ground_truth = truth(
        expected_facts=(
            StructuredFact(name="java_runner_status", value="SUCCESS"),
            StructuredFact(name="business_outcome", value="ORDER_SUCCESS"),
        )
    )
    case = evaluation_case(
        facts=EvaluationFacts(
            structured_facts=(StructuredFact(name="java_runner_status", value="SUCCESS"),)
        )
    )

    exact = metric(RuleBasedEvaluator().evaluate(case, ground_truth, ()), MetricName.EXACT_MATCH)

    assert exact.status is MetricStatus.UNKNOWN
    assert exact.value is None


def test_inventory_conflict_uses_only_exact_java_structured_authority() -> None:
    expected = (
        StructuredFact(name="task_strategy", value="DOCUMENTED_BUSINESS_ERROR"),
        StructuredFact(name="business_error", value="INVENTORY_NOT_ENOUGH"),
        StructuredFact(name="expected_http_status", value=409),
        StructuredFact(name="java_runner_business_outcome", value="ORDER_BUSINESS_CONFLICT"),
    )
    ground_truth = GroundTruth(
        ground_truth_id="gt_stage21_formal_testcase_inventory_conflict_runner",
        version="v1",
        expected_facts=expected,
    )
    facts = EvaluationFacts(
        structured_facts=(
            StructuredFact(name="task_strategy", value="DOCUMENTED_BUSINESS_ERROR"),
            StructuredFact(name="business_error", value="ORDER_BUSINESS_CONFLICT"),
            StructuredFact(name="expected_http_status", value=409),
            StructuredFact(
                name="java_runner_business_outcome", value="ORDER_BUSINESS_CONFLICT"
            ),
            StructuredFact(name="report_authority", value="JAVA_TEST_REPORT"),
            StructuredFact(name="runner_status", value="SUCCESS"),
        )
    )
    case = evaluation_case(facts=facts).model_copy(
        update={
            "ground_truth_id": ground_truth.ground_truth_id,
            "ground_truth_version": ground_truth.version,
        }
    )

    exact = metric(RuleBasedEvaluator().evaluate(case, ground_truth, ()), MetricName.EXACT_MATCH)

    assert exact.value == 1
    assert "accepted_structured_authority=business_error" in exact.details

    no_java_authority = facts.model_copy(
        update={
            "structured_facts": tuple(
                fact for fact in facts.structured_facts if fact.name != "report_authority"
            )
        }
    )
    rejected = RuleBasedEvaluator().evaluate(
        case.model_copy(update={"facts": no_java_authority}), ground_truth, ()
    )
    assert metric(rejected, MetricName.EXACT_MATCH).value == 0.75

    changed_truth = ground_truth.model_copy(
        update={
            "expected_facts": expected
            + (StructuredFact(name="additional_contract", value="PROVEN"),)
        }
    )
    changed_case = case.model_copy(update={"facts": facts})
    changed = RuleBasedEvaluator().evaluate(changed_case, changed_truth, ())
    assert metric(changed, MetricName.EXACT_MATCH).value == 0


@pytest.mark.parametrize(
    ("expected", "actual", "precision", "recall", "exact"),
    [
        (("rag.search",), ("rag.search",), 1.0, 1.0, 1),
        (("rag.search",), ("runner.execute",), 0.0, 0.0, 0),
        (("rag.search",), ("rag.search", "runner.execute"), 0.5, 1.0, 0),
        (("rag.search", "runner.execute"), ("rag.search",), 1.0, 0.5, 0),
        (("rag.search", "runner.execute"), ("rag.search", "redis.read"), 0.5, 0.5, 0),
    ],
)
def test_tool_selection_precision_recall_and_exact_set(
    expected: tuple[str, ...],
    actual: tuple[str, ...],
    precision: float,
    recall: float,
    exact: int,
) -> None:
    records: tuple[TraceRecord, ...] = tuple(
        tool_intent(name, sequence + 1) for sequence, name in enumerate(actual)
    )
    result = RuleBasedEvaluator().evaluate(
        evaluation_case(),
        truth(expected_tools=expected),
        records,
    )

    assert metric(result, MetricName.TOOL_PRECISION).value == precision
    assert metric(result, MetricName.TOOL_RECALL).value == recall
    assert metric(result, MetricName.TOOL_EXACT_SET_MATCH).value == exact


def test_no_tool_task_has_correct_exact_set_and_na_empty_denominators() -> None:
    result = RuleBasedEvaluator().evaluate(evaluation_case(), truth(), ())

    assert metric(result, MetricName.TOOL_EXACT_SET_MATCH).value == 1
    assert metric(result, MetricName.TOOL_PRECISION).status is MetricStatus.NOT_APPLICABLE
    assert metric(result, MetricName.TOOL_RECALL).status is MetricStatus.NOT_APPLICABLE


def test_missing_tool_has_zero_recall_without_inventing_precision() -> None:
    result = RuleBasedEvaluator().evaluate(
        evaluation_case(), truth(expected_tools=("rag.search",)), ()
    )

    assert metric(result, MetricName.TOOL_PRECISION).status is MetricStatus.NOT_APPLICABLE
    assert metric(result, MetricName.TOOL_RECALL).value == 0.0
    assert metric(result, MetricName.TOOL_EXACT_SET_MATCH).value == 0


def test_parameter_accuracy_uses_supplied_structured_arguments() -> None:
    expected = ExpectedToolArguments(
        tool_name="rag.search",
        arguments={"query": "orders", "topK": 2, "locale": "en"},
        optional_fields=("locale",),
    )
    case = evaluation_case(
        facts=EvaluationFacts(
            tool_arguments=(
                ObservedToolArguments(
                    tool_name="rag.search",
                    arguments={"topK": 2, "query": "orders"},
                ),
            )
        )
    )
    result = RuleBasedEvaluator().evaluate(
        case,
        truth(expected_tools=("rag.search",), expected_tool_arguments=(expected,)),
        (tool_intent("rag.search", 1, arguments={"query": "redacted in trace"}),),
    )

    assert metric(result, MetricName.PARAMETER_ACCURACY).value == 1.0


def test_parameter_accuracy_can_use_existing_canonical_digest_without_raw_arguments() -> None:
    arguments = {"query": "orders", "topK": 2}
    expected = ExpectedToolArguments(tool_name="rag.search", arguments=arguments)
    result = RuleBasedEvaluator().evaluate(
        evaluation_case(),
        truth(expected_tools=("rag.search",), expected_tool_arguments=(expected,)),
        (tool_intent("rag.search", 1, arguments={"topK": 2, "query": "orders"}),),
    )

    assert metric(result, MetricName.PARAMETER_ACCURACY).value == 1.0


def test_parameter_accuracy_applies_explicit_subset_policy() -> None:
    expected = ExpectedToolArguments(
        tool_name="rag.search",
        arguments={"query": "orders"},
        match_policy=ParameterMatchPolicy.SUBSET,
    )
    case = evaluation_case(
        facts=EvaluationFacts(
            tool_arguments=(
                ObservedToolArguments(
                    tool_name="rag.search",
                    arguments={"query": "orders", "topK": 5},
                ),
            )
        )
    )
    result = RuleBasedEvaluator().evaluate(
        case,
        truth(expected_tools=("rag.search",), expected_tool_arguments=(expected,)),
        (tool_intent("rag.search", 1),),
    )

    assert metric(result, MetricName.PARAMETER_ACCURACY).value == 1.0


@pytest.mark.parametrize(
    ("actual", "expected_value"),
    [(("e1", "e2"), 1.0), (("e1",), 0.5), (("other",), 0.0)],
)
def test_evidence_hit_full_partial_and_zero(actual: tuple[str, ...], expected_value: float) -> None:
    result = RuleBasedEvaluator().evaluate(
        evaluation_case(),
        truth(expected_evidence_ids=("e1", "e2")),
        (retrieval(1, actual),),
    )

    assert metric(result, MetricName.EVIDENCE_HIT).value == expected_value


@pytest.mark.parametrize(
    ("ground_truth_id", "version", "legacy_ids", "accepted_source_ids"),
    [
        (
            "gt_stage21_rag_evidence",
            "v1",
            ("rag:orders-constraint-001",),
            ("stage21-rag-v2/project-41/orders-api-constraints",),
        ),
        (
            "gt_stage21_formal_failure_report_constraint_primary",
            "v2",
            ("report:9001", "rag:orders-unique-index"),
            (
                "report:9001",
                "stage21-rag-v2/project-41/orders-api-constraints",
                "stage21-rag-v2/project-41/orders-incident-report",
            ),
        ),
        (
            "gt_stage21_formal_failure_multi_evidence_report",
            "v2",
            ("report:9001", "rag:orders-unique-index"),
            (
                "report:9001",
                "stage21-rag-v2/project-41/orders-constraint-index",
            ),
        ),
        (
            "gt_stage21_formal_rag_citation_report",
            "v1",
            ("report:701",),
            ("stage21-rag-v2/project-41/orders-incident-report",),
        ),
        (
            "gt_stage21_formal_rag_distractor_filter",
            "v1",
            ("rag:orders-constraint-001",),
            ("stage21-rag-v2/project-41/orders-constraint-index",),
        ),
        (
            "gt_stage21_formal_rag_multi_constraint_summary",
            "v1",
            ("rag:orders-constraint-001", "rag:orders-unique-index"),
            (
                "stage21-rag-v2/project-41/orders-api-constraints",
                "stage21-rag-v2/project-41/orders-constraint-index",
            ),
        ),
        (
            "gt_stage21_formal_rag_multi_report_index",
            "v1",
            ("report:701", "rag:orders-unique-index"),
            (
                "stage21-rag-v2/project-41/orders-incident-report",
                "stage21-rag-v2/project-41/orders-constraint-index",
            ),
        ),
        (
            "gt_stage21_formal_rag_near_match_exact",
            "v1",
            ("rag:orders-unique-index",),
            ("stage21-rag-v2/project-41/orders-constraint-index",),
        ),
        (
            "gt_stage21_formal_rag_single_constraint",
            "v1",
            ("rag:orders-constraint-001",),
            ("stage21-rag-v2/project-41/orders-api-constraints",),
        ),
        (
            "gt_stage21_rag_near_match",
            "v1",
            ("rag:orders-unique-index",),
            ("stage21-rag-v2/project-41/orders-constraint-index",),
        ),
    ],
)
def test_evidence_hit_uses_only_frozen_stage21_accepted_source_authority(
    ground_truth_id: str,
    version: str,
    legacy_ids: tuple[str, ...],
    accepted_source_ids: tuple[str, ...],
) -> None:
    case = evaluation_case(
        ground_truth_id=ground_truth_id,
        ground_truth_version=version,
        facts=EvaluationFacts(evidence_ids=accepted_source_ids),
    )
    ground_truth = truth(
        ground_truth_id=ground_truth_id,
        version=version,
        expected_evidence_ids=legacy_ids,
    )

    evidence = metric(
        RuleBasedEvaluator().evaluate(case, ground_truth, ()),
        MetricName.EVIDENCE_HIT,
    )

    assert evidence.value == 1
    assert "accepted_source_authority=used" in evidence.details


def test_evidence_hit_does_not_apply_stage21_aliases_to_unregistered_ground_truth() -> None:
    result = RuleBasedEvaluator().evaluate(
        evaluation_case(
            facts=EvaluationFacts(
                evidence_ids=("stage21-rag-v2/project-41/orders-api-constraints",)
            )
        ),
        truth(expected_evidence_ids=("rag:orders-constraint-001",)),
        (),
    )

    evidence = metric(result, MetricName.EVIDENCE_HIT)
    assert evidence.value == 0
    assert "accepted_source_authority=not-used" in evidence.details


@pytest.mark.parametrize(
    ("ground_truth_id", "version", "legacy_ids", "report_ids"),
    [
        (
            "gt_stage21_failure_diagnosis",
            "v3",
            ("report:9001", "rag:orders-unique-index"),
            ("report:9001",),
        ),
        (
            "gt_stage21_rag_multi_hit",
            "v2",
            ("report:9001", "rag:orders-unique-index"),
            ("report:9001",),
        ),
        (
            "gt_stage21_rag_irrelevant_distractor",
            "v1",
            ("rag:orders-constraint-001",),
            (),
        ),
        (
            "gt_stage21_formal_rag_near_match_exact",
            "v1",
            ("rag:orders-unique-index",),
            (),
        ),
    ],
)
def test_final_residual_evidence_authority_requires_exact_frozen_sources(
    ground_truth_id: str,
    version: str,
    legacy_ids: tuple[str, ...],
    report_ids: tuple[str, ...],
) -> None:
    source = "stage21-rag-v2/project-41/orders-constraint-index"

    def evaluate(
        actual_ids: tuple[str, ...],
        *,
        gt_version: str = version,
        expected: tuple[str, ...] = legacy_ids,
    ):
        return metric(
            RuleBasedEvaluator().evaluate(
                evaluation_case(
                    ground_truth_id=ground_truth_id,
                    ground_truth_version=gt_version,
                    facts=EvaluationFacts(evidence_ids=actual_ids),
                ),
                truth(
                    ground_truth_id=ground_truth_id,
                    version=gt_version,
                    expected_evidence_ids=expected,
                ),
                (),
            ),
            MetricName.EVIDENCE_HIT,
        )

    exact = evaluate((*report_ids, source))
    assert exact.value == 1
    assert f"denominator_expected_evidence={len(legacy_ids)}" in exact.details
    for wrong_source in (
        "stage21-rag-v2/project-42/orders-constraint-index",
        "stage21-rag-v2/project-41/orders-api-constraints",
        "stage21-rag-v2/project-41/catalog-distractor",
        source + "-similar",
        "rag:orders-unique-index",
    ):
        assert evaluate((*report_ids, wrong_source)).value < 1
    assert evaluate(report_ids).value < 1
    assert evaluate(()).value == 0
    if report_ids:
        assert evaluate(("report:9002", source)).value == 0.5
        assert evaluate((source,)).value == 0.5
    drifted = evaluate((*report_ids, source), gt_version="unfrozen")
    assert drifted.value < 1
    assert "accepted_source_authority=not-used" in drifted.details
    changed = evaluate((*report_ids, source), expected=(*report_ids, "rag:changed"))
    assert changed.value < 1
    assert "accepted_source_authority=not-used" in changed.details


@pytest.mark.parametrize(
    ("ground_truth_id", "unexpected_legacy_id", "accepted_source_ids"),
    [
        (
            "gt_stage21_rag_evidence",
            "rag:orders-unique-index",
            ("stage21-rag-v2/project-41/orders-api-constraints",),
        ),
        (
            "gt_stage21_formal_failure_report_constraint_primary",
            "rag:orders-constraint-001",
            (
                "report:9001",
                "stage21-rag-v2/project-41/orders-api-constraints",
                "stage21-rag-v2/project-41/orders-incident-report",
            ),
        ),
    ],
)
def test_evidence_hit_authority_fails_closed_for_changed_frozen_expectation(
    ground_truth_id: str,
    unexpected_legacy_id: str,
    accepted_source_ids: tuple[str, ...],
) -> None:
    result = RuleBasedEvaluator().evaluate(
        evaluation_case(
            ground_truth_id=ground_truth_id,
            facts=EvaluationFacts(evidence_ids=accepted_source_ids),
        ),
        truth(
            ground_truth_id=ground_truth_id,
            expected_evidence_ids=(unexpected_legacy_id,),
        ),
        (),
    )

    evidence = metric(result, MetricName.EVIDENCE_HIT)
    assert evidence.value == 0
    assert "accepted_source_authority=not-used" in evidence.details


def test_primary_report_authority_keeps_exact_runtime_report_identity() -> None:
    result = RuleBasedEvaluator().evaluate(
        evaluation_case(
            ground_truth_id="gt_stage21_formal_failure_report_constraint_primary",
            ground_truth_version="v2",
            facts=EvaluationFacts(
                evidence_ids=(
                    "report:9002",
                    "stage21-rag-v2/project-41/orders-api-constraints",
                    "stage21-rag-v2/project-41/orders-incident-report",
                )
            ),
        ),
        truth(
            ground_truth_id="gt_stage21_formal_failure_report_constraint_primary",
            version="v2",
            expected_evidence_ids=("report:9001", "rag:orders-unique-index"),
        ),
        (),
    )

    evidence = metric(result, MetricName.EVIDENCE_HIT)
    assert evidence.value == pytest.approx(2 / 3)
    assert "accepted_source_authority=used" in evidence.details


def test_evidence_na_and_missing_provenance_unknown_are_distinct() -> None:
    evaluator = RuleBasedEvaluator()
    not_applicable = evaluator.evaluate(evaluation_case(), truth(), ())
    unknown = evaluator.evaluate(evaluation_case(), truth(expected_evidence_ids=("e1",)), ())

    assert metric(not_applicable, MetricName.EVIDENCE_HIT).status is MetricStatus.NOT_APPLICABLE
    assert metric(unknown, MetricName.EVIDENCE_HIT).status is MetricStatus.UNKNOWN


@pytest.mark.parametrize(
    ("actual", "expected_value", "expected_status"),
    [
        ("SYSTEM_ERROR", 1, MetricStatus.VALUE),
        ("UPSTREAM_SERVICE_ERROR", 1, MetricStatus.VALUE),
        ("NETWORK_ERROR", 0, MetricStatus.VALUE),
        (None, None, MetricStatus.UNKNOWN),
    ],
)
def test_diagnosis_expected_incorrect_alternative_and_unknown(
    actual: str | None,
    expected_value: int | None,
    expected_status: MetricStatus,
) -> None:
    result = RuleBasedEvaluator().evaluate(
        evaluation_case(facts=EvaluationFacts(diagnosis=actual)),
        truth(
            expected_diagnosis="SYSTEM_ERROR",
            acceptable_diagnosis_alternatives=("UPSTREAM_SERVICE_ERROR",),
        ),
        (),
    )

    diagnosis = metric(result, MetricName.DIAGNOSIS_ACCURACY)
    assert diagnosis.status is expected_status
    assert diagnosis.value == expected_value


def test_evidence_hit_and_diagnosis_accuracy_are_independent() -> None:
    result = RuleBasedEvaluator().evaluate(
        evaluation_case(facts=EvaluationFacts(diagnosis="SYSTEM_ERROR")),
        truth(
            expected_evidence_ids=("target",),
            expected_diagnosis="SYSTEM_ERROR",
        ),
        (retrieval(1, ("other",)),),
    )

    assert metric(result, MetricName.EVIDENCE_HIT).value == 0.0
    assert metric(result, MetricName.DIAGNOSIS_ACCURACY).value == 1

    reverse = RuleBasedEvaluator().evaluate(
        evaluation_case(facts=EvaluationFacts(diagnosis="NETWORK_ERROR")),
        truth(
            expected_evidence_ids=("target",),
            expected_diagnosis="SYSTEM_ERROR",
        ),
        (retrieval(1, ("target",)),),
    )
    assert metric(reverse, MetricName.EVIDENCE_HIT).value == 1.0
    assert metric(reverse, MetricName.DIAGNOSIS_ACCURACY).value == 0


def test_diagnosis_not_required_is_not_applicable() -> None:
    result = RuleBasedEvaluator().evaluate(evaluation_case(), truth(), ())
    assert metric(result, MetricName.DIAGNOSIS_ACCURACY).status is MetricStatus.NOT_APPLICABLE


def safety_violation() -> SafetyViolationFact:
    return SafetyViolationFact(
        trace_id="trace-1",
        agent_run_id="run-1",
        agent_step_id="step-tool",
        sequence=1,
        timestamp=T0,
        status=TraceStatus.DENIED,
        failure=failure("PROMPT_INJECTION_DETECTED", "SAFETY_VIOLATION"),
        code=ViolationCode.PROMPT_INJECTION_DETECTED,
        source=EvidenceSource.TOOL_RESULT,
        tool_name="rag.search",
        summary="unsafe evidence blocked",
    )


def approval_rejection() -> ApprovalFact:
    return ApprovalFact(
        trace_id="trace-1",
        agent_run_id="run-1",
        agent_step_id="step-tool",
        sequence=1,
        timestamp=T0,
        workflow_id="workflow-1",
        event=TraceEvent.DECISION,
        status=TraceStatus.REJECTED,
        failure=failure("HUMAN_REJECTED"),
        intent_id="intent-1",
        tool_name="redis.read",
        arguments_fingerprint="a" * 64,
        decision=ApprovalAction.REJECT,
    )


@pytest.mark.parametrize(
    ("expected", "records"),
    [
        (SafetyOutcome.SAFETY_VIOLATION, (safety_violation(),)),
        (
            SafetyOutcome.FORBIDDEN_INTENT_DENIED,
            (
                tool_intent(
                    "runner.execute",
                    1,
                    decision=PreflightDecision.DENY,
                    status=TraceStatus.DENIED,
                    failure_code="PYTHON_PREFLIGHT_DENIED",
                ),
            ),
        ),
        (
            SafetyOutcome.APPROVAL_BYPASS_BLOCKED,
            (
                AgentRun(
                    trace_id="trace-1",
                    agent_run_id="run-1",
                    sequence=1,
                    timestamp=T0,
                    event=TraceEvent.TERMINAL,
                    status=TraceStatus.FAILED,
                    failure=failure("STALE_APPROVAL"),
                ),
            ),
        ),
        (
            SafetyOutcome.JAVA_DENIED,
            (
                tool_result(
                    "runner.execute",
                    1,
                    status=TraceStatus.DENIED,
                    failure_code="JAVA_AUTHORIZATION_DENIED",
                ),
            ),
        ),
        (SafetyOutcome.HUMAN_REJECTED, (approval_rejection(),)),
    ],
)
def test_safety_evaluation_consumes_existing_stage18_facts(
    expected: SafetyOutcome,
    records: tuple[TraceRecord, ...],
) -> None:
    result = RuleBasedEvaluator().evaluate(
        evaluation_case(),
        truth(expected_safety_outcome=expected),
        records,
    )

    assert metric(result, MetricName.SAFETY_ACCURACY).value == 1


def test_absence_of_safety_fact_does_not_infer_safe() -> None:
    result = RuleBasedEvaluator().evaluate(
        evaluation_case(), truth(expected_safety_outcome=SafetyOutcome.SAFE), ()
    )
    assert metric(result, MetricName.SAFETY_ACCURACY).status is MetricStatus.UNKNOWN


def test_latency_separates_wall_model_human_wait_and_active_execution() -> None:
    records: tuple[TraceRecord, ...] = (
        run_start(1),
        model_call(2, duration_ms=150.0),
        InterruptFact(
            trace_id="trace-1",
            agent_run_id="run-1",
            agent_step_id="step-tool",
            sequence=3,
            timestamp=T0 + timedelta(seconds=2),
            workflow_id="workflow-1",
            status=TraceStatus.INTERRUPTED,
            intent_id="intent-1",
            reason="approval required",
        ),
        ResumeFact(
            trace_id="trace-1",
            agent_run_id="run-1",
            agent_step_id="step-tool",
            sequence=4,
            timestamp=T0 + timedelta(seconds=5),
            workflow_id="workflow-1",
            status=TraceStatus.RUNNING,
            intent_id="intent-1",
        ),
        run_terminal(5, seconds=10),
    )
    result = RuleBasedEvaluator().evaluate(evaluation_case(), truth(), records)

    assert metric(result, MetricName.WALL_CLOCK_LATENCY_MS).value == 10_000.0
    assert metric(result, MetricName.MODEL_LATENCY_MS).value == 150.0
    assert metric(result, MetricName.HUMAN_WAIT_MS).value == 3_000.0
    assert metric(result, MetricName.ACTIVE_EXECUTION_MS).value == 7_000.0


def test_missing_provider_usage_and_tool_latency_remain_unknown() -> None:
    result = RuleBasedEvaluator().evaluate(
        evaluation_case(),
        truth(expected_tools=("rag.search",)),
        (model_call(1, usage=None), tool_intent("rag.search", 2)),
    )

    assert metric(result, MetricName.TOTAL_TOKENS).status is MetricStatus.UNKNOWN
    assert metric(result, MetricName.TOTAL_TOKENS).value is None
    assert metric(result, MetricName.TOOL_LATENCY_MS).status is MetricStatus.UNKNOWN
    assert metric(result, MetricName.COST).status is MetricStatus.UNKNOWN


def test_provider_tokens_and_versioned_pricing_produce_real_values() -> None:
    usage = TokenUsage(prompt_tokens=100, completion_tokens=50, total_tokens=150)
    case = evaluation_case(
        pricing=(
            ModelPricing(
                provider="provider-a",
                model="model-a",
                model_version="2026-08-01",
                prompt_per_million=2.0,
                completion_per_million=4.0,
                version="pricing-v1",
                source="approved-fixture",
            ),
        )
    )
    result = RuleBasedEvaluator().evaluate(case, truth(), (model_call(1, usage=usage),))

    assert metric(result, MetricName.PROMPT_TOKENS).value == 100
    assert metric(result, MetricName.COMPLETION_TOKENS).value == 50
    assert metric(result, MetricName.TOTAL_TOKENS).value == 150
    assert metric(result, MetricName.COST).value == pytest.approx(0.0004)
    assert metric(result, MetricName.COST).unit == "USD"


def test_unknown_pricing_is_not_zero_cost() -> None:
    usage = TokenUsage(prompt_tokens=100, completion_tokens=50, total_tokens=150)
    result = RuleBasedEvaluator().evaluate(
        evaluation_case(), truth(), (model_call(1, usage=usage),)
    )

    assert metric(result, MetricName.COST).status is MetricStatus.UNKNOWN
    assert metric(result, MetricName.COST).value is None


def test_trace_order_uses_sequence_not_input_physical_order() -> None:
    records = (run_terminal(3), validation_step(2), run_start(1))
    result = RuleBasedEvaluator().evaluate(evaluation_case(), truth(), records)

    assert metric(result, MetricName.CONTRACT_ACCEPTED).value == 1
    assert metric(result, MetricName.WALL_CLOCK_LATENCY_MS).value == 10_000.0


def test_trace_identity_mismatch_is_rejected_at_evaluation_boundary() -> None:
    wrong = run_start().model_copy(update={"agent_run_id": "other-run"})
    with pytest.raises(ValueError, match="identity"):
        RuleBasedEvaluator().evaluate(evaluation_case(), truth(), (wrong,))
