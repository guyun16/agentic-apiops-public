from __future__ import annotations

import asyncio
import inspect
import json
from collections.abc import Callable
from pathlib import Path

import pytest

from app.benchmark import (
    CURRENT_JAVA_REPORT,
    BenchmarkExecutionOutcome,
    BenchmarkFailureCategory,
    BenchmarkFailureStage,
    BenchmarkInfrastructureError,
    BenchmarkLifecycleStatus,
    BenchmarkRunner,
    BenchmarkRunPolicy,
    BenchmarkTaskFailure,
    BenchmarkTaskStatus,
    FixtureSetup,
    JavaExecutionStatus,
    JsonBenchmarkResultStore,
    StaticFixtureAdapter,
    ToolResultObservation,
    is_stage21_initial_report_task,
    load_dataset,
    resolve_python_fixture,
    select_dataset_tasks,
)
from app.evaluator import (
    EvaluationCase,
    EvaluationFacts,
    EvaluationResult,
    GroundTruth,
    RuleBasedEvaluator,
    SafetyOutcome,
    StructuredFact,
)
from app.tracing import (
    Latency,
    ModelCall,
    ModelIdentity,
    PayloadDigest,
    PromptIdentity,
    TokenUsage,
    TraceEvent,
    TraceRecord,
    TraceStatus,
)


@pytest.fixture(scope="module")
def dataset():
    return load_dataset()


def _pair(dataset, task_id: str) -> tuple[object, GroundTruth]:
    task = next(task for task in dataset.tasks if task.benchmark_task_id == task_id)
    truth = next(
        truth
        for truth in dataset.ground_truths
        if truth.ground_truth_id == task.ground_truth_ref.ground_truth_id
        and truth.version == task.ground_truth_ref.version
    )
    return task, truth


def _outcome(trace_id: str, agent_run_id: str) -> BenchmarkExecutionOutcome:
    return BenchmarkExecutionOutcome(
        trace_id=trace_id,
        agent_run_id=agent_run_id,
        facts=EvaluationFacts(),
    )


def test_dataset_selection_is_manifest_ordered_and_supports_split_category_and_golden_filters(
    dataset,
) -> None:
    selected = select_dataset_tasks(
        dataset,
        split="dev",
        category="TESTCASE_GENERATION",
    )
    expected_ids = [
        entry.benchmark_task_id
        for entry in dataset.manifest.tasks
        if entry.split.value == "dev"
        and next(
            task for task in dataset.tasks if task.benchmark_task_id == entry.benchmark_task_id
        ).task_type.value
        == "TESTCASE_GENERATION"
    ]
    assert len(selected) == len(expected_ids)
    assert [task.benchmark_task_id for task, _ in selected] == expected_ids
    assert all(task.task_type.value == "TESTCASE_GENERATION" for task, _ in selected)
    assert all(
        next(
            entry
            for entry in dataset.manifest.tasks
            if entry.benchmark_task_id == task.benchmark_task_id
        ).split.value
        == "dev"
        for task, _ in selected
    )

    golden = select_dataset_tasks(dataset, golden_only=True)
    assert [task.benchmark_task_id for task, _ in golden] == [
        "bench_task_golden_e2e_apiops",
        "bench_task_golden_failure_diagnosis",
        "bench_task_golden_rag_evidence",
        "bench_task_golden_testcase_happy",
        "bench_task_golden_tool_safety",
    ]


class FakeWorkflowAdapter:
    def __init__(self, behavior: Callable[..., BenchmarkExecutionOutcome] | None = None) -> None:
        self.calls: list[str] = []
        self.behavior = behavior

    async def execute(
        self,
        task,
        setup: FixtureSetup,
        *,
        trace_id: str,
        agent_run_id: str,
    ) -> BenchmarkExecutionOutcome:
        self.calls.append(task.benchmark_task_id)
        if self.behavior is None:
            return _outcome(trace_id, agent_run_id)
        result = self.behavior(
            task,
            setup,
            trace_id=trace_id,
            agent_run_id=agent_run_id,
        )
        if hasattr(result, "__await__"):
            result = await result
        return result


class FailingFixtureAdapter(StaticFixtureAdapter):
    def __init__(self, failing_task_id: str | None = None) -> None:
        self.failing_task_id = failing_task_id
        self.setup_calls: list[str] = []
        self.cleanup_calls: list[str] = []

    async def setup(self, task) -> FixtureSetup:
        self.setup_calls.append(task.benchmark_task_id)
        if task.benchmark_task_id == self.failing_task_id:
            raise RuntimeError("controlled setup failure")
        return await super().setup(task)

    async def cleanup(self, task, setup: FixtureSetup | None) -> None:
        self.cleanup_calls.append(task.benchmark_task_id)


class CleanupFailureAdapter(StaticFixtureAdapter):
    def __init__(self, failing_task_id: str) -> None:
        self.failing_task_id = failing_task_id

    async def cleanup(self, task, setup: FixtureSetup | None) -> None:
        if task.benchmark_task_id == self.failing_task_id:
            raise RuntimeError("controlled cleanup failure")


@pytest.mark.anyio
async def test_normal_batch_is_stable_and_persists_every_task(dataset, tmp_path: Path) -> None:
    task_ids = (
        "bench_task_golden_testcase_happy",
        "bench_task_golden_rag_evidence",
        "bench_task_golden_tool_safety",
    )
    pairs = [_pair(dataset, task_id) for task_id in task_ids]
    store = JsonBenchmarkResultStore(tmp_path / "results")
    adapter = FakeWorkflowAdapter()
    progress = []

    runner = BenchmarkRunner(adapter, result_store=store)
    run = await runner.run_batch(
        [task for task, _ in pairs],
        [truth for _, truth in pairs],
        evaluation_run_id="evaluation_run:test-normal",
        on_progress=progress.append,
    )

    assert [result.benchmark_task_id for result in run.results] == list(task_ids)
    assert all(result.status is BenchmarkTaskStatus.SUCCESS for result in run.results)
    assert all(result.cleanup_status is BenchmarkLifecycleStatus.SUCCESS for result in run.results)
    assert len(progress) == 3
    assert (
        store.task_path("evaluation_run:test-normal", "_baseline").parent / "run.json"
    ).is_file()
    assert all(
        store.task_path("evaluation_run:test-normal", task_id).is_file() for task_id in task_ids
    )
    assert adapter.calls == list(task_ids)


@pytest.mark.anyio
async def test_agent_failure_is_persisted_without_benchmark_retry_and_batch_continues(
    dataset, tmp_path: Path
) -> None:
    first, first_truth = _pair(dataset, "bench_task_golden_testcase_happy")
    second, second_truth = _pair(dataset, "bench_task_golden_rag_evidence")

    def behavior(task, setup, *, trace_id: str, agent_run_id: str):
        if task.benchmark_task_id == first.benchmark_task_id:
            raise RuntimeError("agent workflow failed; token=should-not-be-persisted")
        return _outcome(trace_id, agent_run_id)

    adapter = FakeWorkflowAdapter(behavior)
    store = JsonBenchmarkResultStore(tmp_path / "results")
    run = await BenchmarkRunner(adapter, result_store=store).run_batch(
        [first, second],
        [first_truth, second_truth],
        evaluation_run_id="evaluation_run:test-agent-failure",
    )

    failed, succeeded = run.results
    assert failed.status is BenchmarkTaskStatus.FAILED
    assert failed.failure_stage is BenchmarkFailureStage.EXECUTION
    assert failed.failure_category == BenchmarkFailureCategory.AGENT_FAILURE.value
    assert failed.infrastructure_attempts == 1
    assert succeeded.status is BenchmarkTaskStatus.SUCCESS
    assert adapter.calls == [first.benchmark_task_id, second.benchmark_task_id]
    assert store.task_path(run.evaluation_run_id, first.benchmark_task_id).is_file()
    artifact_text = store.task_path(
        run.evaluation_run_id,
        first.benchmark_task_id,
    ).read_text(encoding="utf-8")
    assert "should-not-be-persisted" not in artifact_text
    assert "[REDACTED]" in artifact_text


@pytest.mark.anyio
async def test_transient_infrastructure_retry_is_bounded_and_distinct_from_agent_retry(
    dataset,
) -> None:
    task, truth = _pair(dataset, "bench_task_golden_testcase_happy")
    attempts = 0

    def eventually_succeeds(task, setup, *, trace_id: str, agent_run_id: str):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise BenchmarkInfrastructureError(
                "temporary connection reset",
                code="TRANSIENT_CONNECTION_RESET",
                retryable=True,
            )
        return _outcome(trace_id, agent_run_id)

    policy = BenchmarkRunPolicy(max_infrastructure_attempts=2)
    result = await BenchmarkRunner(
        FakeWorkflowAdapter(eventually_succeeds), policy=policy
    ).run_task(
        task,
        truth,
        evaluation_run_id="evaluation_run:test-retry",
    )
    assert result.status is BenchmarkTaskStatus.SUCCESS
    assert result.infrastructure_attempts == 2
    assert result.agent_retry_count == 0

    def always_fails(task, setup, *, trace_id: str, agent_run_id: str):
        raise BenchmarkInfrastructureError(
            "service unavailable",
            code="SERVICE_UNAVAILABLE",
            retryable=True,
        )

    saturated = await BenchmarkRunner(
        FakeWorkflowAdapter(always_fails),
        policy=policy,
    ).run_task(task, truth, evaluation_run_id="evaluation_run:test-retry-saturated")
    assert saturated.status is BenchmarkTaskStatus.FAILED
    assert saturated.failure_category == BenchmarkFailureCategory.INFRASTRUCTURE_FAILURE.value
    assert saturated.infrastructure_attempts == 2


@pytest.mark.anyio
async def test_setup_failure_skips_workflow_and_continues(dataset, tmp_path: Path) -> None:
    first, first_truth = _pair(dataset, "bench_task_golden_testcase_happy")
    second, second_truth = _pair(dataset, "bench_task_golden_rag_evidence")
    fixtures = FailingFixtureAdapter(first.benchmark_task_id)
    adapter = FakeWorkflowAdapter()
    store = JsonBenchmarkResultStore(tmp_path / "results")

    run = await BenchmarkRunner(adapter, fixture_adapter=fixtures, result_store=store).run_batch(
        [first, second],
        [first_truth, second_truth],
        evaluation_run_id="evaluation_run:test-setup-failure",
    )

    failed, succeeded = run.results
    assert failed.failure_stage is BenchmarkFailureStage.SETUP
    assert failed.failure_category == BenchmarkFailureCategory.SETUP_FAILURE.value
    assert failed.setup_status is BenchmarkLifecycleStatus.FAILED
    assert succeeded.status is BenchmarkTaskStatus.SUCCESS
    assert adapter.calls == [second.benchmark_task_id]
    assert fixtures.cleanup_calls == [first.benchmark_task_id, second.benchmark_task_id]
    assert store.task_path(run.evaluation_run_id, first.benchmark_task_id).is_file()


@pytest.mark.anyio
async def test_evaluation_failure_preserves_execution_references(dataset) -> None:
    task, truth = _pair(dataset, "bench_task_golden_failure_diagnosis")

    def evaluate_failure(
        case: EvaluationCase,
        ground_truth: GroundTruth,
        trace_records: tuple[TraceRecord, ...],
    ) -> EvaluationResult:
        raise RuntimeError("controlled evaluation failure")

    def executed(task, setup, *, trace_id: str, agent_run_id: str):
        return BenchmarkExecutionOutcome(
            trace_id=trace_id,
            agent_run_id=agent_run_id,
            facts=EvaluationFacts(),
            run_id=701,
            report_id="report:701",
            tool_call_ids=("tool-call:701",),
            rag_query_ids=("rag-query:701",),
        )

    result = await BenchmarkRunner(
        FakeWorkflowAdapter(executed),
        evaluator=evaluate_failure,
    ).run_task(task, truth, evaluation_run_id="evaluation_run:test-eval-failure")

    assert result.status is BenchmarkTaskStatus.FAILED
    assert result.failure_stage is BenchmarkFailureStage.EVALUATION
    assert result.failure_category == BenchmarkFailureCategory.EVALUATION_FAILURE.value
    assert result.evaluation_result is None
    assert result.run_id == 701
    assert result.report_id == "report:701"
    assert result.tool_call_ids == ("tool-call:701",)
    assert result.rag_query_ids == ("rag-query:701",)
    assert result.cleanup_status is BenchmarkLifecycleStatus.SUCCESS


@pytest.mark.anyio
async def test_runner_projects_model_call_count_and_usage_from_existing_trace(dataset) -> None:
    task, truth = _pair(dataset, "bench_task_testcase_auth_missing_token")

    def model_call(call_id: str, event: TraceEvent) -> ModelCall:
        terminal = event is TraceEvent.TERMINAL
        return ModelCall(
            event=event,
            status=TraceStatus.SUCCESS if terminal else TraceStatus.RUNNING,
            trace_id="trace:model-facts",
            agent_run_id="agent_run:model-facts",
            model_call_id=call_id,
            model_identity=ModelIdentity(provider="test", model="test-model"),
            prompt=PromptIdentity(name="test", version="v1"),
            model_input=PayloadDigest.from_value("input"),
            model_output=PayloadDigest.from_value("output") if terminal else None,
            token_usage=(
                TokenUsage(prompt_tokens=10, completion_tokens=4, total_tokens=14)
                if terminal
                else None
            ),
            latency=Latency(duration_ms=2.5) if terminal else None,
        )

    def executed(task, setup, *, trace_id: str, agent_run_id: str):
        del task, setup
        return BenchmarkExecutionOutcome(
            trace_id=trace_id,
            agent_run_id=agent_run_id,
            facts=EvaluationFacts(),
            trace_records=(
                model_call("model-call-1", TraceEvent.START),
                model_call("model-call-1", TraceEvent.TERMINAL),
                model_call("model-call-2", TraceEvent.START),
                model_call("model-call-2", TraceEvent.TERMINAL),
            ),
            java_execution_status=JavaExecutionStatus.NOT_APPLICABLE,
        )

    result = await BenchmarkRunner(FakeWorkflowAdapter(executed)).run_task(
        task,
        truth,
        evaluation_run_id="evaluation_run:model-facts",
    )

    assert result.model_call_ids == ("model-call-1", "model-call-2")
    assert result.model_call_count == 2
    assert result.model_latency_ms == 5.0
    assert result.prompt_tokens == 20
    assert result.completion_tokens == 8
    assert result.total_tokens == 28


@pytest.mark.anyio
async def test_formal_evidence_snapshot_retains_redacted_replay_authority(dataset) -> None:
    task, truth = _pair(dataset, "bench_task_golden_testcase_happy")

    def executed(task, setup, *, trace_id: str, agent_run_id: str):
        del task, setup
        return BenchmarkExecutionOutcome(
            trace_id=trace_id,
            agent_run_id=agent_run_id,
            facts=EvaluationFacts(
                diagnosis="BUSINESS_ERROR",
                structured_facts=(
                    StructuredFact(
                        name="candidate",
                        value={"request": {"authorization": "Bearer do-not-store"}},
                    ),
                    StructuredFact(name="diagnosis_outcome", value="COMPLETED"),
                    StructuredFact(name="sufficient_evidence", value=True),
                    StructuredFact(name="safety_outcome", value="SAFE"),
                    StructuredFact(name="safety_terminal_decision", value="SAFE"),
                ),
            ),
            tool_result_observations=(
                ToolResultObservation(
                    toolCallId="java-call:retained",
                    toolName="rag.search",
                    status="SUCCESS",
                    hasData=True,
                    ragQueryId="rag-query:retained",
                    resultCount=1,
                    mappingStatus="SUCCESS",
                ),
            ),
        )

    result = await BenchmarkRunner(FakeWorkflowAdapter(executed)).run_task(
        task,
        truth,
        evaluation_run_id="evaluation_run:formal-evidence",
    )

    assert result.formal_evidence is not None
    dumped = result.formal_evidence.model_dump(mode="json")
    assert dumped["redactedCandidate"]["request"]["authorization"] == "[REDACTED]"
    assert dumped["diagnosisOutcome"]["failureType"] == "BUSINESS_ERROR"
    assert dumped["terminalDecisionFacts"] == [
        {"name": "safety_outcome", "value": "SAFE"},
        {"name": "safety_terminal_decision", "value": "SAFE"},
    ]
    assert dumped["toolResultMappings"][0]["mappingStatus"] == "SUCCESS"
    assert dumped["toolResultMappings"][0]["ragQueryId"] == "rag-query:retained"
    assert "do-not-store" not in json.dumps(dumped)


@pytest.mark.anyio
async def test_cleanup_failure_is_visible_and_policy_can_abort(dataset) -> None:
    first, first_truth = _pair(dataset, "bench_task_golden_testcase_happy")
    second, second_truth = _pair(dataset, "bench_task_golden_rag_evidence")
    adapter = FakeWorkflowAdapter()
    cleanup = CleanupFailureAdapter(first.benchmark_task_id)

    continuing = await BenchmarkRunner(adapter, fixture_adapter=cleanup).run_batch(
        [first, second],
        [first_truth, second_truth],
        evaluation_run_id="evaluation_run:test-cleanup-continue",
    )
    assert continuing.aborted is False
    assert continuing.results[0].status is BenchmarkTaskStatus.FAILED
    assert continuing.results[0].failure_category == BenchmarkFailureCategory.CLEANUP_FAILURE.value
    assert continuing.results[0].evaluation_result is not None
    assert continuing.results[0].cleanup_error_summary is not None
    assert continuing.results[1].status is BenchmarkTaskStatus.SUCCESS

    aborting = await BenchmarkRunner(
        FakeWorkflowAdapter(),
        fixture_adapter=CleanupFailureAdapter(first.benchmark_task_id),
        policy=BenchmarkRunPolicy(abort_on_cleanup_failure=True),
    ).run_batch(
        [first, second],
        [first_truth, second_truth],
        evaluation_run_id="evaluation_run:test-cleanup-abort",
    )
    assert aborting.aborted is True
    assert len(aborting.results) == 1
    assert aborting.abort_reason == f"cleanup failure for {first.benchmark_task_id}"


@pytest.mark.anyio
async def test_human_reject_fixture_is_deterministic_and_not_retried(dataset) -> None:
    task, truth = _pair(dataset, "bench_task_tool_human_reject")
    fixture = json.loads(
        resolve_python_fixture(
            "python-apiops-agentlab/tests/benchmark/fixtures/support/tool-human-reject.json"
        ).read_text(encoding="utf-8")
    )
    attempts = 0

    def rejected(task, setup, *, trace_id: str, agent_run_id: str):
        nonlocal attempts
        attempts += 1
        assert fixture["facts"]["humanDecision"] == "REJECT"
        return BenchmarkExecutionOutcome(
            trace_id=trace_id,
            agent_run_id=agent_run_id,
            facts=EvaluationFacts(safety_outcome=SafetyOutcome.HUMAN_REJECTED),
        )

    result = await BenchmarkRunner(FakeWorkflowAdapter(rejected)).run_task(
        task,
        truth,
        evaluation_run_id="evaluation_run:test-human-reject",
    )
    assert result.status is BenchmarkTaskStatus.SUCCESS
    assert result.infrastructure_attempts == 1
    assert attempts == 1
    assert (
        next(
            metric
            for metric in result.evaluation_result.metrics
            if metric.metric.value == "safety_accuracy"
        ).value
        == 1
    )


@pytest.mark.anyio
async def test_task_timeout_is_bounded_persisted_and_followed_by_next_task(
    dataset, tmp_path: Path
) -> None:
    first, first_truth = _pair(dataset, "bench_task_golden_testcase_happy")
    second, second_truth = _pair(dataset, "bench_task_golden_rag_evidence")

    async def behavior(task, setup, *, trace_id: str, agent_run_id: str):
        if task.benchmark_task_id == first.benchmark_task_id:
            await asyncio.sleep(0.05)
        return _outcome(trace_id, agent_run_id)

    store = JsonBenchmarkResultStore(tmp_path / "results")
    run = await BenchmarkRunner(
        FakeWorkflowAdapter(behavior),
        result_store=store,
        policy=BenchmarkRunPolicy(task_timeout_seconds=0.01),
    ).run_batch(
        [first, second],
        [first_truth, second_truth],
        evaluation_run_id="evaluation_run:test-timeout",
    )
    assert run.results[0].status is BenchmarkTaskStatus.TIMEOUT
    assert run.results[0].failure_stage is BenchmarkFailureStage.EXECUTION
    assert run.results[1].status is BenchmarkTaskStatus.SUCCESS
    assert store.task_path(run.evaluation_run_id, first.benchmark_task_id).is_file()


@pytest.mark.anyio
async def test_stage20_internal_timeout_is_not_outer_benchmark_timeout(dataset) -> None:
    task, truth = _pair(dataset, "bench_task_golden_failure_diagnosis")

    def java_timeout(task, setup, *, trace_id: str, agent_run_id: str):
        raise BenchmarkTaskFailure(
            "Java status observation timed out after its own boundary",
            category=BenchmarkFailureCategory.PROVIDER_FAILURE,
            code="JAVA_STATUS_QUERY_TIMEOUT",
        )

    result = await BenchmarkRunner(FakeWorkflowAdapter(java_timeout)).run_task(
        task,
        truth,
        evaluation_run_id="evaluation_run:test-java-timeout",
    )

    assert result.status is BenchmarkTaskStatus.FAILED
    assert result.status is not BenchmarkTaskStatus.TIMEOUT
    assert result.failure_category == BenchmarkFailureCategory.PROVIDER_FAILURE.value
    assert result.failure_code == "JAVA_STATUS_QUERY_TIMEOUT"


@pytest.mark.anyio
async def test_fixture_cleanup_isolates_task_initial_state(dataset) -> None:
    first, first_truth = _pair(dataset, "bench_task_golden_testcase_happy")
    second, second_truth = _pair(dataset, "bench_task_golden_rag_evidence")

    class IsolatedFixtureAdapter(StaticFixtureAdapter):
        def __init__(self) -> None:
            self.current: str | None = None

        async def setup(self, task) -> FixtureSetup:
            assert self.current is None
            self.current = task.benchmark_task_id
            return FixtureSetup(
                fixture_refs=(task.benchmark_task_id,),
                handle=task.benchmark_task_id,
            )

        async def cleanup(self, task, setup: FixtureSetup | None) -> None:
            assert setup is not None
            assert self.current == task.benchmark_task_id
            self.current = None

    fixture = IsolatedFixtureAdapter()
    seen: list[str] = []

    def observe(task, setup, *, trace_id: str, agent_run_id: str):
        assert fixture.current == task.benchmark_task_id
        seen.append(fixture.current)
        return _outcome(trace_id, agent_run_id)

    run = await BenchmarkRunner(
        FakeWorkflowAdapter(observe),
        fixture_adapter=fixture,
    ).run_batch(
        [first, second],
        [first_truth, second_truth],
        evaluation_run_id="evaluation_run:test-isolation",
    )
    assert [result.status for result in run.results] == [
        BenchmarkTaskStatus.SUCCESS,
        BenchmarkTaskStatus.SUCCESS,
    ]
    assert seen == [first.benchmark_task_id, second.benchmark_task_id]
    assert fixture.current is None


@pytest.mark.anyio
async def test_runner_reuses_stage19_evaluation_result(dataset) -> None:
    task, truth = _pair(dataset, "bench_task_golden_testcase_happy")
    result = await BenchmarkRunner(FakeWorkflowAdapter()).run_task(
        task,
        truth,
        evaluation_run_id="evaluation_run:test-evaluation-result",
    )

    assert isinstance(result.evaluation_result, EvaluationResult)
    assert result.evaluation_result.evaluation_id == result.evaluation_id
    assert result.evaluation_result.evaluator_version == "rule-evaluator-v1"
    assert not hasattr(result, "metrics")


def test_runner_has_no_direct_owned_store_or_internal_service_dependency() -> None:
    source = Path(inspect.getfile(BenchmarkRunner)).read_text(encoding="utf-8").lower()
    for forbidden in ("mysql", "redis", "rabbitmq", "qdrant", "raw logs", "java repository"):
        assert forbidden not in source
    assert "workflow_adapter.execute" in source


@pytest.mark.anyio
async def test_mixed_failures_all_persist_as_task_results(dataset, tmp_path: Path) -> None:
    task_ids = (
        "bench_task_golden_testcase_happy",
        "bench_task_golden_failure_diagnosis",
        "bench_task_golden_rag_evidence",
        "bench_task_golden_tool_safety",
        "bench_task_golden_e2e_apiops",
    )
    pairs = [_pair(dataset, task_id) for task_id in task_ids]
    attempts: dict[str, int] = {}

    def behavior(task, setup, *, trace_id: str, agent_run_id: str):
        task_id = task.benchmark_task_id
        attempts[task_id] = attempts.get(task_id, 0) + 1
        if task_id == task_ids[1]:
            raise RuntimeError("agent failure")
        if task_id == task_ids[2]:
            raise BenchmarkInfrastructureError(
                "permanent infrastructure failure",
                code="SERVICE_UNAVAILABLE",
                retryable=False,
            )
        if task_id == task_ids[3]:
            raise RuntimeError("timeout-like task failure")
        return _outcome(trace_id, agent_run_id)

    fixtures = FailingFixtureAdapter(task_ids[4])
    store = JsonBenchmarkResultStore(tmp_path / "results")
    run = await BenchmarkRunner(
        FakeWorkflowAdapter(behavior),
        fixture_adapter=fixtures,
        result_store=store,
    ).run_batch(
        [task for task, _ in pairs],
        [truth for _, truth in pairs],
        evaluation_run_id="evaluation_run:test-mixed-failures",
    )

    assert len(run.results) == 5
    assert all(store.task_path(run.evaluation_run_id, task_id).is_file() for task_id in task_ids)
    assert run.results[0].status is BenchmarkTaskStatus.SUCCESS
    assert run.results[1].failure_category == BenchmarkFailureCategory.AGENT_FAILURE.value
    assert run.results[2].failure_category == BenchmarkFailureCategory.INFRASTRUCTURE_FAILURE.value
    assert run.results[3].failure_category == BenchmarkFailureCategory.AGENT_FAILURE.value
    assert run.results[4].failure_category == BenchmarkFailureCategory.SETUP_FAILURE.value
    assert attempts[task_ids[1]] == 1
    artifact = json.loads(
        store.task_path(run.evaluation_run_id, task_ids[1]).read_text(encoding="utf-8")
    )
    assert artifact["status"] == "FAILED"
    assert "evaluationResult" not in artifact or artifact["evaluationResult"] is None


@pytest.mark.anyio
async def test_golden_runner_projects_current_report_and_keeps_unresolved_without_identity(
    tmp_path: Path,
) -> None:
    projected_truths: list[GroundTruth] = []

    def current_report(task, setup, *, trace_id: str, agent_run_id: str):
        if is_stage21_initial_report_task(task):
            return BenchmarkExecutionOutcome(
                trace_id=trace_id,
                agent_run_id=agent_run_id,
                report_id="report:test-current-1",
            )
        return _outcome(trace_id, agent_run_id)

    def capture_ground_truth(case, ground_truth, trace_records):
        del trace_records
        projected_truths.append(ground_truth)
        return RuleBasedEvaluator().evaluate(case, ground_truth, ())

    store = JsonBenchmarkResultStore(tmp_path / "golden-results")
    run = await BenchmarkRunner(
        FakeWorkflowAdapter(current_report),
        evaluator=capture_ground_truth,
        result_store=store,
    ).run_dataset(
        golden_only=True,
        evaluation_run_id="evaluation_run:test-golden-batch",
    )

    assert len(run.selected_task_ids) == 5
    assert len(run.results) == 5
    assert all(result.status is BenchmarkTaskStatus.SUCCESS for result in run.results)
    projected = next(
        truth
        for truth in projected_truths
        if truth.ground_truth_id == "gt_stage21_failure_diagnosis"
    )
    assert projected.expected_evidence_ids == (
        "report:test-current-1",
        "rag:orders-unique-index",
    )
    assert CURRENT_JAVA_REPORT not in projected.expected_evidence_ids
    assert all(
        store.task_path(run.evaluation_run_id, task_id).is_file()
        for task_id in run.selected_task_ids
    )
    assert (
        store.task_path("evaluation_run:test-golden-batch", "_baseline").parent
        / "run.json"
    ).is_file()

    missing_store = JsonBenchmarkResultStore(tmp_path / "missing-current-report")
    missing = await BenchmarkRunner(
        FakeWorkflowAdapter(),
        result_store=missing_store,
    ).run_dataset(
        golden_only=True,
        task_ids=("bench_task_golden_failure_diagnosis",),
        evaluation_run_id="evaluation_run:test-golden-missing-current-report",
    )
    missing_current_report = missing.results[0]
    assert missing_current_report.status is BenchmarkTaskStatus.SUCCESS
    assert missing_current_report.failure_code is None
    assert missing_current_report.report_id is None
    assert missing_current_report.evaluation_result is not None
    assert any(
        metric.metric.value == "evidence_hit" and metric.status.value == "UNKNOWN"
        for metric in missing_current_report.evaluation_result.metrics
    )
    print(
        "STAGE21_GOLDEN_BATCH "
        + json.dumps(
            {
                "selected": len(run.selected_task_ids),
                "executed": len(run.results),
                "success": sum(
                    result.status is BenchmarkTaskStatus.SUCCESS for result in run.results
                ),
                "failures": sum(
                    result.status is BenchmarkTaskStatus.FAILED for result in run.results
                ),
                "timeouts": sum(
                    result.status is BenchmarkTaskStatus.TIMEOUT for result in run.results
                ),
                "artifacts": len(tuple((tmp_path / "golden-results").rglob("*.json"))),
            },
            sort_keys=True,
        )
    )
