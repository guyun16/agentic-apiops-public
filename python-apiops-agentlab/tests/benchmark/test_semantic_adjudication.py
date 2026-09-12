from __future__ import annotations

import json

import pytest

from app.benchmark.models import BenchmarkTask, DatasetSplit, TaskType
from app.benchmark.outcome_v2 import (
    OutcomeAuthority,
    OutcomeMode,
    OutcomePolicy,
    OutcomePolicyTask,
    ToolRequirement,
    V2OutcomeStatus,
    project_outcome_v2,
)
from app.benchmark.runner import (
    BenchmarkExecutionOutcome,
    BenchmarkLifecycleStatus,
    BenchmarkRun,
    BenchmarkRunner,
    BenchmarkRunPolicy,
    BenchmarkTaskResult,
    BenchmarkTaskStatus,
    CallableStage20WorkflowAdapter,
)
from app.benchmark.semantic_adjudication import (
    RootCauseSemanticReference,
    SemanticAdjudicationResult,
    SemanticAdjudicator,
    SemanticDecision,
    build_root_cause_judge_request,
    extract_root_cause_candidate,
)
from app.benchmark.success import TaskSuccessStatus
from app.evaluator import (
    CalibrationCaseResult,
    EvaluationCase,
    EvaluationFacts,
    EvaluationResult,
    FakeDeterministicJudge,
    GroundTruth,
    JudgeCalibrationResult,
    JudgeConfiguration,
    JudgeDimension,
    JudgeRequest,
    JudgeResult,
    JudgeRubric,
    JudgeSubject,
    MetricName,
    MetricResult,
    MetricStatus,
    StructuredFact,
)
from app.tracing import ModelIdentity, PromptIdentity

TASK_ID = "bench_task_semantic_root_cause"
GT_ID = "gt_semantic_root_cause"


def configuration() -> JudgeConfiguration:
    return JudgeConfiguration(
        rubric=JudgeRubric(
            rubric_id="diagnosis-root-cause-equivalence",
            version="v1",
            dimension=JudgeDimension.DIAGNOSIS_QUALITY,
            criteria=(
                "The candidate root cause is semantically equivalent to the reference.",
                "The candidate does not invent execution or evidence facts.",
            ),
        ),
        prompt=PromptIdentity(name="stage21-semantic-judge", version="v1"),
        model_identity=ModelIdentity(
            provider="fake-provider",
            model="deterministic-judge",
            version="fixture-v1",
        ),
    )


def facts(*, diagnosis: str | None = None) -> EvaluationFacts:
    hypotheses = [
        {
            "statement": "The persisted order key already exists in the orders table.",
            "confidence": "HIGH",
            "evidenceRefs": [{"itemId": "evidence:orders-unique"}],
        }
    ]
    return EvaluationFacts(
        diagnosis=diagnosis,
        evidence_ids=("evidence:orders-unique",),
        structured_facts=(
            StructuredFact(name="root_cause_hypotheses", value=hypotheses),
            StructuredFact(name="rootCauseHypotheses", value=hypotheses),
            StructuredFact(name="sufficientEvidence", value=True),
        ),
    )


def case(current_facts: EvaluationFacts | None = None) -> EvaluationCase:
    return EvaluationCase(
        case_id="case:semantic",
        trace_id="trace:semantic",
        agent_run_id="agent_run:semantic",
        ground_truth_id=GT_ID,
        ground_truth_version="v1",
        facts=current_facts or facts(),
    )


def evaluation_result(current_case: EvaluationCase | None = None) -> EvaluationResult:
    current = current_case or case()
    return EvaluationResult(
        evaluation_id="evaluation:semantic",
        case_id=current.case_id,
        trace_id=current.trace_id,
        agent_run_id=current.agent_run_id,
        ground_truth_id=current.ground_truth_id,
        ground_truth_version=current.ground_truth_version,
        evaluator_version="rule-evaluator-v1",
        metrics=(
            MetricResult.unavailable(
                MetricName.DIAGNOSIS_ACCURACY,
                MetricStatus.UNKNOWN,
                "semantic ambiguity in unit fixture",
            ),
        ),
    )


def reference() -> RootCauseSemanticReference:
    return RootCauseSemanticReference(
        referenceId="reference:orders-unique",
        version="v1",
        benchmarkTaskId=TASK_ID,
        groundTruthId=GT_ID,
        groundTruthVersion="v1",
        statements=(
            "Order creation failed because the database uniqueness constraint was violated.",
        ),
        evidenceReferences=("evidence:orders-unique",),
    )


def judge_result(request: JudgeRequest, score: float) -> JudgeResult:
    return JudgeResult(
        judge_result_id=f"judge-result:{request.judge_case_id}:{score}",
        judge_case_id=request.judge_case_id,
        trace_id=request.trace_id,
        agent_run_id=request.agent_run_id,
        dimension=request.configuration.rubric.dimension,
        score=score,
        reason="Preset semantic result.",
        configuration=request.configuration,
    )


def calibration(config: JudgeConfiguration):
    request = JudgeRequest(
        judge_case_id="calibration:semantic",
        trace_id="trace:calibration",
        agent_run_id="agent_run:calibration",
        subject=JudgeSubject(
            candidate_summary="The persisted key exists.",
            reference_summary="The key violates uniqueness.",
        ),
        configuration=config,
    )
    result = judge_result(request, 1.0)
    return JudgeCalibrationResult(
        calibration_id="calibration:semantic",
        configuration=config,
        case_results=(
            CalibrationCaseResult(
                fixture_id="calibration-fixture:semantic",
                human_label_source="unit",
                human_label_version="v1",
                expected_human_score=1.0,
                tolerance=0.0,
                judge_result=result,
                absolute_error=0.0,
                agrees=True,
            ),
        ),
        agreement_count=1,
        disagreement_count=0,
        agreement_rate=1.0,
    )


def adjudicator_for(score: float = 1.0, *, with_calibration: bool = True):
    current_case = case()
    current_reference = reference()
    config = configuration()
    request = build_root_cause_judge_request(
        current_case,
        extract_root_cause_candidate(current_case.facts),
        current_reference,
        config,
    )
    fake = FakeDeterministicJudge((judge_result(request, score),))
    return (
        SemanticAdjudicator(
            fake,
            configuration=config,
            calibration=calibration(config) if with_calibration else None,
        ),
        fake,
        current_case,
        current_reference,
    )


@pytest.mark.anyio
@pytest.mark.parametrize("status", (TaskSuccessStatus.PASS, TaskSuccessStatus.FAIL))
async def test_decisive_deterministic_result_never_calls_judge(status: TaskSuccessStatus) -> None:
    adjudicator, fake, current_case, current_reference = adjudicator_for()

    result = await adjudicator.adjudicate(
        task_id=TASK_ID,
        task_type=TaskType.FAILURE_DIAGNOSIS,
        case=current_case,
        evaluation_result=evaluation_result(current_case),
        deterministic_status=status,
        reference=current_reference,
    )

    assert result.decision is SemanticDecision.NOT_ELIGIBLE
    assert fake.calls == []


@pytest.mark.anyio
async def test_semantic_match_calls_reused_judge_once() -> None:
    adjudicator, fake, current_case, current_reference = adjudicator_for(1.0)

    result = await adjudicator.adjudicate(
        task_id=TASK_ID,
        task_type=TaskType.FAILURE_DIAGNOSIS,
        case=current_case,
        evaluation_result=evaluation_result(current_case),
        reference=current_reference,
    )

    assert result.decision is SemanticDecision.SEMANTIC_MATCH
    assert result.eligible is True
    assert result.judge_result is not None
    assert len(fake.calls) == 1
    assert fake.calls[0].subject.reference_summary == current_reference.statements[0]


@pytest.mark.anyio
async def test_semantic_mismatch_is_not_a_default_pass() -> None:
    adjudicator, fake, current_case, current_reference = adjudicator_for(0.0)

    result = await adjudicator.adjudicate(
        task_id=TASK_ID,
        task_type=TaskType.FAILURE_DIAGNOSIS,
        case=current_case,
        evaluation_result=evaluation_result(current_case),
        reference=current_reference,
    )

    assert result.decision is SemanticDecision.SEMANTIC_MISMATCH
    assert len(fake.calls) == 1


@pytest.mark.anyio
async def test_missing_candidate_or_reference_stays_unresolved_without_judge() -> None:
    adjudicator, fake, current_case, current_reference = adjudicator_for()

    missing_candidate = await adjudicator.adjudicate(
        task_id=TASK_ID,
        task_type=TaskType.FAILURE_DIAGNOSIS,
        case=case(EvaluationFacts()),
        evaluation_result=evaluation_result(case(EvaluationFacts())),
        reference=current_reference,
    )
    missing_reference = await adjudicator.adjudicate(
        task_id=TASK_ID,
        task_type=TaskType.FAILURE_DIAGNOSIS,
        case=current_case,
        evaluation_result=evaluation_result(current_case),
        reference=None,
    )
    missing_observed_evidence_case = case(
        EvaluationFacts(structured_facts=facts().structured_facts)
    )
    missing_observed_evidence = await adjudicator.adjudicate(
        task_id=TASK_ID,
        task_type=TaskType.FAILURE_DIAGNOSIS,
        case=missing_observed_evidence_case,
        evaluation_result=evaluation_result(missing_observed_evidence_case),
        reference=current_reference,
    )

    assert missing_candidate.decision is SemanticDecision.UNRESOLVED
    assert missing_reference.decision is SemanticDecision.UNRESOLVED
    assert missing_observed_evidence.decision is SemanticDecision.UNRESOLVED
    assert fake.calls == []


@pytest.mark.anyio
async def test_non_allowlisted_dimension_never_calls_judge() -> None:
    adjudicator, fake, current_case, current_reference = adjudicator_for()

    result = await adjudicator.adjudicate(
        task_id=TASK_ID,
        task_type=TaskType.FAILURE_DIAGNOSIS,
        case=current_case,
        evaluation_result=evaluation_result(current_case),
        reference=current_reference,
        dimension=JudgeDimension.SEMANTIC_QUALITY,
    )

    assert result.decision is SemanticDecision.NOT_ELIGIBLE
    assert fake.calls == []


@pytest.mark.anyio
async def test_missing_calibration_and_judge_failure_stay_unresolved() -> None:
    adjudicator, fake, current_case, current_reference = adjudicator_for(with_calibration=False)
    no_calibration = await adjudicator.adjudicate(
        task_id=TASK_ID,
        task_type=TaskType.FAILURE_DIAGNOSIS,
        case=current_case,
        evaluation_result=evaluation_result(current_case),
        reference=current_reference,
    )

    class FailingJudge:
        async def judge(self, request: JudgeRequest) -> JudgeResult:
            raise RuntimeError("provider unavailable")

    request = build_root_cause_judge_request(
        current_case,
        extract_root_cause_candidate(current_case.facts),
        current_reference,
        configuration(),
    )
    failing = SemanticAdjudicator(
        FailingJudge(),
        configuration=configuration(),
        calibration=calibration(configuration()),
    )
    provider_failure = await failing.adjudicate(
        task_id=TASK_ID,
        task_type=TaskType.FAILURE_DIAGNOSIS,
        case=current_case,
        evaluation_result=evaluation_result(current_case),
        reference=current_reference,
    )

    assert no_calibration.decision is SemanticDecision.UNRESOLVED
    assert provider_failure.decision is SemanticDecision.UNRESOLVED
    assert fake.calls == []
    assert request.subject.reference_summary == current_reference.statements[0]


@pytest.mark.anyio
async def test_nonsemantic_unknown_does_not_call_judge() -> None:
    adjudicator, fake, current_case, current_reference = adjudicator_for()
    result_with_evidence_gap = evaluation_result(current_case).model_copy(
        update={
            "metrics": (
                MetricResult.unavailable(
                    MetricName.DIAGNOSIS_ACCURACY,
                    MetricStatus.UNKNOWN,
                    "diagnosis wording is ambiguous",
                ),
                MetricResult.unavailable(
                    MetricName.EVIDENCE_HIT,
                    MetricStatus.UNKNOWN,
                    "evidence identity is unavailable",
                ),
            )
        }
    )

    result = await adjudicator.adjudicate(
        task_id=TASK_ID,
        task_type=TaskType.FAILURE_DIAGNOSIS,
        case=current_case,
        evaluation_result=result_with_evidence_gap,
        reference=current_reference,
    )

    assert result.decision is SemanticDecision.UNRESOLVED
    assert fake.calls == []


@pytest.mark.anyio
async def test_intermediate_judge_score_remains_unresolved() -> None:
    adjudicator, fake, current_case, current_reference = adjudicator_for(0.9)

    result = await adjudicator.adjudicate(
        task_id=TASK_ID,
        task_type=TaskType.FAILURE_DIAGNOSIS,
        case=current_case,
        evaluation_result=evaluation_result(current_case),
        reference=current_reference,
    )

    assert result.decision is SemanticDecision.UNRESOLVED
    assert len(fake.calls) == 1


@pytest.mark.anyio
async def test_failure_type_deterministic_fail_cannot_be_overridden() -> None:
    current_case = case(facts(diagnosis="WRONG_FAILURE_TYPE"))
    config = configuration()
    fake = FakeDeterministicJudge(())
    adjudicator = SemanticAdjudicator(
        fake,
        configuration=config,
        calibration=calibration(config),
    )

    result = await adjudicator.adjudicate(
        task_id=TASK_ID,
        task_type=TaskType.FAILURE_DIAGNOSIS,
        case=current_case,
        evaluation_result=evaluation_result(current_case),
        deterministic_status=TaskSuccessStatus.FAIL,
        reference=reference(),
    )

    assert result.decision is SemanticDecision.NOT_ELIGIBLE
    assert fake.calls == []
    assert current_case.facts.safety_outcome is None
    assert current_case.facts.evidence_ids == ("evidence:orders-unique",)


def benchmark_task() -> BenchmarkTask:
    return BenchmarkTask(
        schemaVersion="0.2.0",
        benchmarkTaskId=TASK_ID,
        taskType=TaskType.FAILURE_DIAGNOSIS,
        instruction="Diagnose the bounded test failure.",
        initialState={
            "entries": ({"kind": "LITERAL", "key": "projectId", "value": 41},),
        },
        allowedTools=(),
        forbiddenActions=("sql.write",),
        expectedOutput={},
        groundTruthRef={"groundTruthId": GT_ID, "version": "v1"},
        evaluationSpec={"selectedMetrics": (MetricName.DIAGNOSIS_ACCURACY,)},
        metrics=(MetricName.DIAGNOSIS_ACCURACY,),
    )


def benchmark_truth() -> GroundTruth:
    return GroundTruth(
        ground_truth_id=GT_ID,
        version="v1",
        expected_diagnosis="DATABASE_CONSTRAINT_ERROR",
    )


@pytest.mark.anyio
async def test_runner_calls_judge_only_after_execution_and_persists_sidecar() -> None:
    task = benchmark_task()
    truth = benchmark_truth()
    config = configuration()
    events: list[str] = []

    class RecordingJudge:
        def __init__(self) -> None:
            self.calls: list[JudgeRequest] = []

        async def judge(self, current: JudgeRequest) -> JudgeResult:
            self.calls.append(current)
            events.append("judge")
            return judge_result(current, 1.0)

    judge = RecordingJudge()

    async def execute(current_task, setup, *, trace_id: str, agent_run_id: str):
        events.append("execute")
        payload = json.dumps(current_task.model_dump(mode="json"))
        assert reference().statements[0] not in payload
        assert reference().reference_id not in payload
        assert reference().statements[0] not in json.dumps(setup.fixture_refs)
        return BenchmarkExecutionOutcome(
            trace_id=trace_id,
            agent_run_id=agent_run_id,
            facts=facts(),
        )

    result = await BenchmarkRunner(
        CallableStage20WorkflowAdapter(execute),
        judge=judge,
        judge_configuration=config,
        judge_calibration=calibration(config),
        semantic_references={TASK_ID: reference()},
        identity_factory=lambda prefix: f"{prefix}:fixed",
    ).run_task(task, truth, evaluation_run_id="evaluation:semantic")

    assert events == ["execute", "judge"]
    assert result.status is BenchmarkTaskStatus.SUCCESS
    assert result.task_success is not None
    assert result.task_success.status is TaskSuccessStatus.UNKNOWN
    assert result.semantic_adjudication is not None
    assert result.semantic_adjudication.decision is SemanticDecision.SEMANTIC_MATCH
    assert result.evaluation_result is not None
    assert any(
        metric.metric is MetricName.DIAGNOSIS_ACCURACY
        for metric in result.evaluation_result.metrics
    )
    assert len(judge.calls) == 1


@pytest.mark.anyio
async def test_runner_without_judge_keeps_semantic_sidecar_absent() -> None:
    async def execute(current_task, setup, *, trace_id: str, agent_run_id: str):
        return BenchmarkExecutionOutcome(
            trace_id=trace_id,
            agent_run_id=agent_run_id,
            facts=facts(),
        )

    result = await BenchmarkRunner(
        CallableStage20WorkflowAdapter(execute),
        identity_factory=lambda prefix: f"{prefix}:fixed",
    ).run_task(
        benchmark_task(),
        benchmark_truth(),
        evaluation_run_id="evaluation:semantic-no-judge",
    )

    assert result.semantic_adjudication is None


def semantic_result(score: float = 1.0) -> SemanticAdjudicationResult:
    current_case = case()
    config = configuration()
    current_reference = reference()
    request = build_root_cause_judge_request(
        current_case,
        extract_root_cause_candidate(current_case.facts),
        current_reference,
        config,
    )
    return SemanticAdjudicationResult(
        dimension=JudgeDimension.DIAGNOSIS_QUALITY,
        eligible=True,
        decision=(
            SemanticDecision.SEMANTIC_MATCH
            if score == 1.0
            else SemanticDecision.SEMANTIC_MISMATCH
        ),
        reason="Preset semantic result.",
        judgeResult=judge_result(request, score),
        rubricVersion=config.rubric.version,
        deterministicBasis=("deterministic_status=UNKNOWN",),
        candidateSource="test-candidate",
        referenceSource="reference:orders-unique@v1",
    )


def v2_result(
    metrics: tuple[MetricResult, ...],
    *,
    semantic: SemanticAdjudicationResult | None = None,
    status: BenchmarkTaskStatus = BenchmarkTaskStatus.SUCCESS,
    tool_call_ids: tuple[str, ...] = (),
    observations=(),
) -> BenchmarkTaskResult:
    return BenchmarkTaskResult(
        evaluationRunId="evaluation:v2",
        benchmarkTaskId=TASK_ID,
        taskType=TaskType.FAILURE_DIAGNOSIS,
        status=status,
        agentRunId="agent:v2",
        traceId="trace:v2",
        toolCallIds=tool_call_ids,
        toolResultObservations=observations,
        caseId="case:v2",
        evaluationResult=EvaluationResult(
            evaluation_id="evaluation:v2",
            case_id="case:v2",
            trace_id="trace:v2",
            agent_run_id="agent:v2",
            ground_truth_id=GT_ID,
            ground_truth_version="v1",
            evaluator_version="rule-evaluator-v1",
            metrics=metrics,
        ),
        semanticAdjudication=semantic,
        setupStatus=BenchmarkLifecycleStatus.SUCCESS,
        cleanupStatus=BenchmarkLifecycleStatus.SUCCESS,
        durationMs=1.0,
    )


def v2_policy(
    *,
    required_tool: bool = False,
    semantic_allowed: bool = True,
) -> OutcomePolicy:
    requirements = (
        {
            "toolName": "rag.search",
            "requirement": ToolRequirement.REQUIRED,
            "reason": "required for unit test",
        },
    ) if required_tool else ()
    return OutcomePolicy(
        policyVersion="stage21-semantic-test",
        datasetId="dataset:v2",
        datasetVersion="v1",
        taskSchemaVersion="0.2.0",
        tasks=(
            OutcomePolicyTask(
                benchmarkTaskId=TASK_ID,
                taskType=TaskType.FAILURE_DIAGNOSIS,
                split=DatasetSplit.DEV,
                scenario="semantic unit",
                outcomeAuthority=OutcomeAuthority.SUPPORTED_BY_EXISTING_FACTS,
                outcomeMetrics=(MetricName.DIAGNOSIS_ACCURACY,),
                outcomeMode=OutcomeMode.ALL,
                toolRequirements=requirements,
                semanticAdjudicationAllowed=semantic_allowed,
            ),
        ),
    )


def v2_run(result: BenchmarkTaskResult) -> BenchmarkRun:
    from datetime import UTC, datetime

    now = datetime.now(UTC)
    return BenchmarkRun(
        evaluationRunId="evaluation:v2",
        datasetId="dataset:v2",
        datasetVersion="v1",
        taskSchemaVersion="0.2.0",
        selectedTaskIds=(TASK_ID,),
        results=(result,),
        startedAt=now,
        completedAt=now,
        policy=BenchmarkRunPolicy(),
    )


def unknown_diagnosis() -> MetricResult:
    return MetricResult.unavailable(
        MetricName.DIAGNOSIS_ACCURACY,
        MetricStatus.UNKNOWN,
        "deterministic diagnosis is unresolved",
    )


def test_explicit_v2_semantic_match_can_resolve_only_unknown_outcome() -> None:
    projection = project_outcome_v2(
        v2_run(v2_result((unknown_diagnosis(),), semantic=semantic_result())),
        v2_policy(),
    )

    task = projection.tasks[0]
    assert task.v2_status is V2OutcomeStatus.PASS
    assert task.semantic_used_for_final_outcome is True
    assert task.semantic_adjudication is not None
    assert task.semantic_adjudication.used_for_final_outcome is True


def test_v2_without_semantic_opt_in_preserves_deterministic_unknown() -> None:
    projection = project_outcome_v2(
        v2_run(v2_result((unknown_diagnosis(),), semantic=semantic_result())),
        v2_policy(semantic_allowed=False),
    )

    task = projection.tasks[0]
    assert task.v2_status is V2OutcomeStatus.UNKNOWN
    assert task.semantic_used_for_final_outcome is False
    assert task.semantic_adjudication is not None
    assert task.semantic_adjudication.used_for_final_outcome is False


def test_semantic_match_cannot_mask_required_tool_safety_citation_or_runner_failure() -> None:
    cases = (
        v2_result((unknown_diagnosis(),), semantic=semantic_result()),
        v2_result(
            (
                unknown_diagnosis(),
                MetricResult.measured(MetricName.SAFETY_ACCURACY, 0),
            ),
            semantic=semantic_result(),
        ),
        v2_result(
            (
                unknown_diagnosis(),
                MetricResult.measured(MetricName.EVIDENCE_HIT, 0),
            ),
            semantic=semantic_result(),
        ),
        v2_result(
            (unknown_diagnosis(),),
            semantic=semantic_result(),
            status=BenchmarkTaskStatus.FAILED,
        ),
    )
    policies = (v2_policy(required_tool=True), v2_policy(), v2_policy(), v2_policy())

    projections = [
        project_outcome_v2(v2_run(result), policy)
        for result, policy in zip(cases, policies)
    ]

    assert all(
        projection.tasks[0].v2_status is not V2OutcomeStatus.PASS
        for projection in projections
    )
    assert all(
        projection.tasks[0].semantic_used_for_final_outcome is False for projection in projections
    )


def test_v2_semantic_mismatch_cannot_override_deterministic_fail() -> None:
    result = v2_result(
        (MetricResult.measured(MetricName.DIAGNOSIS_ACCURACY, 0),),
        semantic=semantic_result(0.0),
    )

    projection = project_outcome_v2(v2_run(result), v2_policy())

    assert projection.tasks[0].v2_status is V2OutcomeStatus.FAIL
    assert projection.tasks[0].semantic_used_for_final_outcome is False
