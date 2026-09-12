"""Stage 20.2 orchestration over existing Java public execution boundaries."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from pydantic import ValidationError

from app.agents.testcase_generator import Candidate, TestCaseGenerator
from app.clients.java_apiops import JavaApiOpsClient, JavaApiOpsResponseValidationError
from app.schemas.openapi_metadata import OpenApiMetadataDetail
from app.schemas.runner import RunnerProgress, RunnerSubmission, TestReport
from app.schemas.testcase_dsl import TestCaseDSL
from app.tracing import (
    IdentityAuthority,
    JavaRunReferenceFact,
    TraceEvent,
    TraceRecorder,
    TraceStatus,
    new_identity,
    observe,
    trace_parent,
)
from app.workflows.context_enrichment import ContextEnricher
from app.workflows.generation_context import TestStrategy, build_generation_context
from app.workflows.state import (
    APIOpsAgentState,
    TestCaseGenerationStatus,
    WorkflowPhase,
)
from app.workflows.testcase_generation_graph import build_testcase_generation_graph


class Stage20ExecutionError(RuntimeError):
    """The cross-system workflow could not preserve its integration contract."""


class GeneratedTestCaseNotValidatedError(Stage20ExecutionError):
    """Stage 16 did not produce an accepted, validated TestCase DSL."""


@dataclass(frozen=True, slots=True)
class RunnerReadbackPolicy:
    """Central bound for Java's SSE status observation."""

    overall_deadline_seconds: float = 60.0

    def __post_init__(self) -> None:
        value = self.overall_deadline_seconds
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
            raise ValueError("overall_deadline_seconds must be greater than zero")


@dataclass(frozen=True, slots=True)
class Stage20ExecutionResult:
    """Typed consumer result; Java remains execution-fact authority."""

    trace_id: str
    agent_run_id: str
    metadata: OpenApiMetadataDetail
    testcase: TestCaseDSL
    submission: RunnerSubmission
    terminal_progress: RunnerProgress
    report: TestReport


@dataclass(frozen=True, slots=True)
class PreparedRunnerExecutionResult:
    """Runner/readback result for an already validated input-side DSL."""

    trace_id: str
    agent_run_id: str
    testcase: TestCaseDSL
    submission: RunnerSubmission
    terminal_progress: RunnerProgress
    report: TestReport


class Stage20ExecutionWorkflow:
    """Metadata → Stage 16 → Java submit → Java terminal/report readback."""

    def __init__(
        self,
        client: JavaApiOpsClient,
        generator: TestCaseGenerator,
        *,
        token_provider: Callable[[], str],
        context_enricher: ContextEnricher | None = None,
        trace_recorder: TraceRecorder | None = None,
        readback_policy: RunnerReadbackPolicy | None = None,
    ) -> None:
        if not isinstance(client, JavaApiOpsClient):
            raise TypeError("client must be a JavaApiOpsClient")
        if not isinstance(generator, TestCaseGenerator):
            raise TypeError("generator must be a TestCaseGenerator")
        if not callable(token_provider):
            raise TypeError("token_provider must be callable")
        self._client = client
        self._token_provider = token_provider
        self._trace_recorder = trace_recorder
        self._readback_policy = readback_policy or RunnerReadbackPolicy()
        self._generation_graph = build_testcase_generation_graph(
            generator,
            context_enricher=context_enricher,
            trace_recorder=trace_recorder,
        )

    async def execute(
        self,
        *,
        project_id: int,
        api_id: str,
        strategy: TestStrategy,
        trace_id: str | None = None,
        agent_run_id: str | None = None,
    ) -> Stage20ExecutionResult:
        effective_trace_id = trace_id or new_identity("trace")
        effective_agent_run_id = agent_run_id or new_identity("agent_run")
        token = self._token_provider()
        metadata = await self._client.get_api_metadata(
            project_id=project_id,
            api_id=api_id,
            token=token,
            trace_id=effective_trace_id,
        )
        generation_context = build_generation_context(metadata, strategy)
        state: APIOpsAgentState = {
            "trace_id": effective_trace_id,
            "agent_run_id": effective_agent_run_id,
            "phase": WorkflowPhase.INITIAL,
            "route": None,
            "error": None,
            "attempt_count": 0,
            "max_attempts": 0,
            "project_id": project_id,
            "api_id": api_id,
            "generation_intent": strategy.value,
            "api_metadata": metadata,
            "generation_context": generation_context,
            "context_pack": None,
            "context_status": None,
            "context_error": None,
            "candidate": None,
            "validation_result": None,
            "repair_attempts": 0,
            "max_repair_attempts": 1,
            "generation_status": None,
        }
        generated = await self._generation_graph.ainvoke(state)
        testcase = self._accepted_testcase(generated)
        prepared = await self.execute_prepared_testcase(
            project_id=project_id,
            testcase=testcase,
            trace_id=effective_trace_id,
            agent_run_id=effective_agent_run_id,
        )
        return Stage20ExecutionResult(
            trace_id=prepared.trace_id,
            agent_run_id=prepared.agent_run_id,
            metadata=metadata,
            testcase=prepared.testcase,
            submission=prepared.submission,
            terminal_progress=prepared.terminal_progress,
            report=prepared.report,
        )

    async def execute_prepared_testcase(
        self,
        *,
        project_id: int,
        testcase: TestCaseDSL,
        trace_id: str | None = None,
        agent_run_id: str | None = None,
    ) -> PreparedRunnerExecutionResult:
        """Run an input-side DSL through the existing Java Runner boundary.

        This method deliberately skips only Stage 16 generation.  Submit,
        terminal observation, Report API readback, identity checks, and trace
        facts are the same Stage 20 path used by ``execute``.
        """

        if not isinstance(testcase, TestCaseDSL):
            raise TypeError("testcase must be a validated TestCaseDSL")
        if testcase.project_id != project_id:
            raise ValueError("testcase projectId must match trusted project_id")
        effective_trace_id = trace_id or new_identity("trace")
        effective_agent_run_id = agent_run_id or new_identity("agent_run")
        token = self._token_provider()
        submission = await self._client.submit_testcase(
            project_id=project_id,
            testcase=testcase,
            token=token,
            trace_id=effective_trace_id,
        )
        task_id, run_id = self._single_execution_identity(submission)
        self._record_java_reference(
            trace_id=effective_trace_id,
            agent_run_id=effective_agent_run_id,
            project_id=project_id,
            submission=submission,
            task_id=task_id,
            run_id=run_id,
            reference_stage="SUBMIT_ACCEPTED",
        )
        progress = await self._client.wait_for_run_terminal(
            project_id=project_id,
            run_id=run_id,
            token=token,
            trace_id=effective_trace_id,
            overall_deadline_seconds=self._readback_policy.overall_deadline_seconds,
        )
        if progress.task_id != task_id:
            raise JavaApiOpsResponseValidationError(
                "Java Runner progress taskId did not match submit response"
            )
        self._record_java_reference(
            trace_id=effective_trace_id,
            agent_run_id=effective_agent_run_id,
            project_id=project_id,
            submission=submission,
            task_id=task_id,
            run_id=run_id,
            reference_stage="TERMINAL_OBSERVED",
            java_status=progress.status,
        )
        report = await self._client.get_test_report(
            project_id=project_id,
            run_id=run_id,
            token=token,
            trace_id=effective_trace_id,
        )
        if report.task_id != task_id or report.status != progress.status:
            raise JavaApiOpsResponseValidationError(
                "Java TestReport identity/status did not match terminal progress"
            )
        self._record_java_reference(
            trace_id=effective_trace_id,
            agent_run_id=effective_agent_run_id,
            project_id=project_id,
            submission=submission,
            task_id=task_id,
            run_id=run_id,
            reference_stage="REPORT_READ",
            java_status=report.status,
        )
        return PreparedRunnerExecutionResult(
            trace_id=effective_trace_id,
            agent_run_id=effective_agent_run_id,
            testcase=testcase,
            submission=submission,
            terminal_progress=progress,
            report=report,
        )

    @classmethod
    def accepted_testcase(cls, state: dict[str, object]) -> TestCaseDSL:
        """Expose the Stage 16 acceptance gate to generated-candidate runner bridges."""

        return cls._accepted_testcase(state)

    @staticmethod
    def _accepted_testcase(state: dict[str, object]) -> TestCaseDSL:
        validation = state.get("validation_result")
        candidate = state.get("candidate")
        if (
            state.get("generation_status") is not TestCaseGenerationStatus.ACCEPTED
            or validation is None
            or not getattr(validation, "valid", False)
            or not isinstance(candidate, Candidate)
        ):
            raise GeneratedTestCaseNotValidatedError(
                "only a Stage 16 accepted and validated TestCase DSL may be submitted"
            )
        try:
            return TestCaseDSL.model_validate(candidate.structured)
        except ValidationError as exc:
            raise Stage20ExecutionError(
                "Stage 16 accepted candidate could not be mapped to TestCaseDSL"
            ) from exc

    @staticmethod
    def _single_execution_identity(submission: RunnerSubmission) -> tuple[int, int]:
        if len(submission.task_ids) != 1 or len(submission.run_ids) != 1:
            raise JavaApiOpsResponseValidationError(
                "single TestCase submit must return exactly one taskId and runId"
            )
        return submission.task_ids[0], submission.run_ids[0]

    def _record_java_reference(
        self,
        *,
        trace_id: str,
        agent_run_id: str,
        project_id: int,
        submission: RunnerSubmission,
        task_id: int,
        run_id: int,
        reference_stage: str,
        java_status: str | None = None,
    ) -> None:
        observe(
            self._trace_recorder,
            lambda: JavaRunReferenceFact(
                trace_id=trace_id,
                agent_run_id=agent_run_id,
                parent_identity=trace_parent(
                    "agent_run",
                    agent_run_id,
                    IdentityAuthority.PYTHON,
                ),
                project_id=project_id,
                event=TraceEvent.FACT,
                status=TraceStatus.SUCCESS,
                reference_stage=reference_stage,
                java_batch_id=submission.batch_id,
                java_task_id=task_id,
                java_run_id=run_id,
                java_status=java_status,
            ),
        )


__all__ = [
    "GeneratedTestCaseNotValidatedError",
    "PreparedRunnerExecutionResult",
    "RunnerReadbackPolicy",
    "Stage20ExecutionError",
    "Stage20ExecutionResult",
    "Stage20ExecutionWorkflow",
]
