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


def test_evidence_na_and_missing_provenance_unknown_are_distinct() -> None:
    evaluator = RuleBasedEvaluator()
    not_applicable = evaluator.evaluate(evaluation_case(), truth(), ())
    unknown = evaluator.evaluate(evaluation_case(), truth(expected_evidence_ids=("e1",)), ())

    assert metric(not_applicable, MetricName.EVIDENCE_HIT).status is MetricStatus.NOT_APPLICABLE
    assert metric(unknown, MetricName.EVIDENCE_HIT).status is MetricStatus.UNKNOWN


@pytest.mark.parametrize(
    ("actual", "expected_value", "expected_status"),
    [
        ("UPSTREAM_SCHEMA_DRIFT", 1, MetricStatus.VALUE),
        ("API_SCHEMA_DRIFT", 1, MetricStatus.VALUE),
        ("NETWORK_TIMEOUT", 0, MetricStatus.VALUE),
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
            expected_diagnosis="UPSTREAM_SCHEMA_DRIFT",
            acceptable_diagnosis_alternatives=("API_SCHEMA_DRIFT",),
        ),
        (),
    )

    diagnosis = metric(result, MetricName.DIAGNOSIS_ACCURACY)
    assert diagnosis.status is expected_status
    assert diagnosis.value == expected_value


def test_evidence_hit_and_diagnosis_accuracy_are_independent() -> None:
    result = RuleBasedEvaluator().evaluate(
        evaluation_case(facts=EvaluationFacts(diagnosis="UPSTREAM_SCHEMA_DRIFT")),
        truth(
            expected_evidence_ids=("target",),
            expected_diagnosis="UPSTREAM_SCHEMA_DRIFT",
        ),
        (retrieval(1, ("other",)),),
    )

    assert metric(result, MetricName.EVIDENCE_HIT).value == 0.0
    assert metric(result, MetricName.DIAGNOSIS_ACCURACY).value == 1

    reverse = RuleBasedEvaluator().evaluate(
        evaluation_case(facts=EvaluationFacts(diagnosis="WRONG_ROOT_CAUSE")),
        truth(
            expected_evidence_ids=("target",),
            expected_diagnosis="UPSTREAM_SCHEMA_DRIFT",
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
