"""Thin real-model execution adapter for the existing AgentLab workflows.

The adapter owns only task-to-workflow translation.  ``BenchmarkRunner`` still
owns setup, evaluation, persistence, and batch policy; Stage 16/18/20 and
Stage 19 remain the authorities for their respective facts.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from app.agents.diagnosis import DiagnosisCandidateParseError, DiagnosisIdentityError
from app.agents.diagnosis_contract import context_payload, observe_diagnosis_contract
from app.agents.testcase_generator import Candidate, IntentionalInvaliditySpec, TestCaseGenerator
from app.clients.java_apiops import JavaApiOpsClient, JavaApiOpsError
from app.clients.llm import LLMClient
from app.evaluator import (
    EvaluationFacts,
    MetricName,
    ObservedToolArguments,
    SafetyOutcome,
    StructuredFact,
)
from app.guardrails.violations import EvidenceSource, ViolationCode
from app.rag.context import (
    ContextItem,
    ContextPack,
    ContextPackBuilder,
    ContextPolicy,
    ContextSource,
)
from app.schemas.diagnosis_report import DiagnosisReport
from app.schemas.openapi_metadata import OpenApiMetadataDetail
from app.schemas.runner import TestReport
from app.schemas.tool_call import ToolCall
from app.tools import ToolCatalog, ToolIntent, ToolRouter
from app.tracing import (
    ApprovalFact,
    JavaRunReferenceFact,
    ModelCall,
    RetrievalFact,
    SafetyViolationFact,
    ToolPlanningRecord,
    ToolResultRecord,
    TraceEvent,
    TraceRecord,
    TraceRecorder,
    TraceStatus,
    failure_detail,
)
from app.workflows.approval import (
    ApprovalAction,
    ApprovalDecision,
    ApprovalRequest,
    fingerprint_arguments,
)
from app.workflows.candidate_validation import validate_candidate
from app.workflows.context_enrichment import ContextEnrichmentResult
from app.workflows.diagnosis_workflow import (
    build_diagnosis_workflow,
    diagnosis_initial_state,
)
from app.workflows.generation_context import (
    GenerationContext,
    TestStrategy,
    assess_strategy,
    build_generation_context,
)
from app.workflows.runtime_control import checkpoint_config
from app.workflows.stage20_execution import RunnerReadbackPolicy, Stage20ExecutionWorkflow
from app.workflows.state import APIOpsAgentState, ContextEnrichmentStatus, WorkflowPhase
from app.workflows.testcase_generation_graph import build_testcase_generation_graph
from app.workflows.tool_planning import (
    EvidenceSufficiency,
    ToolPlanningDecision,
    ToolPlanningError,
    ToolRequirement,
    assess_evidence_sufficiency,
    build_tool_intent,
    decide_tool_requirement,
)

from .auth_profiles import Stage21Prerequisite, load_stage21_prerequisites
from .generation_inputs import (
    GenerationInputResolutionError,
    is_local_generation_reference,
    resolve_generation_metadata_input,
)
from .models import BenchmarkTask, TaskType
from .outcome_projection import (
    assemble_outcome_facts,
    merge_evaluation_facts,
    project_generation_facts,
    project_safety_outcome,
)
from .report_runtime_recipes import (
    ReportRuntimeRecipeResolutionError,
    is_report_runtime_recipe_task,
    resolve_report_runtime_recipe,
)
from .runner import (
    BenchmarkExecutionMode,
    BenchmarkExecutionOutcome,
    BenchmarkFailureCategory,
    BenchmarkTaskFailure,
    FixtureSetup,
    JavaExecutionStatus,
    project_tool_result_observations,
)
from .stage21_initial_report_resources import (
    Stage21InitialReportReferenceError,
    is_stage21_initial_report_task,
    resolve_stage21_initial_report_reference,
)
from .stage21_rag_runtime_recipes import (
    Stage21RagRuntimeRecipeResolutionError,
    resolve_stage21_rag_runtime_recipe,
)
from .stage21_runner_runtime_recipes import (
    Stage21RunnerRuntimeRecipeResolutionError,
    is_stage21_runner_runtime_recipe_task,
    resolve_stage21_runner_runtime_recipe,
)

_RUN_REF_RE = re.compile(r"(?:^|/)run-(?P<run>[0-9]+)(?:/|$)")
_DEFAULT_REPORT_FIXTURE = (
    Path(__file__).resolve().parents[2]
    / "tests"
    / "benchmark"
    / "fixtures"
    / "support"
    / "real-model-test-report.json"
)

_GENERATION_METRICS = frozenset(
    {
        MetricName.VALID_JSON,
        MetricName.SCHEMA_VALID,
        MetricName.CONTRACT_ACCEPTED,
        MetricName.EXACT_MATCH,
    }
)
_DIAGNOSIS_METRICS = frozenset(
    {
        MetricName.TOOL_PRECISION,
        MetricName.TOOL_RECALL,
        MetricName.TOOL_EXACT_SET_MATCH,
        MetricName.PARAMETER_ACCURACY,
        MetricName.EVIDENCE_HIT,
        MetricName.DIAGNOSIS_ACCURACY,
        MetricName.SAFETY_ACCURACY,
    }
)


@dataclass(frozen=True, slots=True)
class _JavaRequirements:
    """Requirements inferred only from typed task resources and selections."""

    metadata: bool = False
    runner: bool = False
    initial_report: bool = False
    tool_gateway: bool = False
    rag: bool = False

    @property
    def required(self) -> bool:
        return self.metadata or self.runner or self.initial_report or self.tool_gateway or self.rag


@dataclass(frozen=True, slots=True)
class _ExecutionPlan:
    generate: bool
    diagnose: bool
    java: _JavaRequirements
    fixture_report_allowed: bool


class _TaskContextEnricher:
    """Add only task instructions to an existing workflow ContextPack."""

    def __init__(self, task: BenchmarkTask, project_id: int) -> None:
        self._task = task
        self._project_id = project_id

    async def enrich(
        self,
        *,
        project_id: int,
        generation_context: object,
    ) -> ContextEnrichmentResult:
        del generation_context
        if project_id != self._project_id:
            raise ValueError("task context project does not match workflow project")
        items = [
            ContextItem(
                source_type=ContextSource.USER_INTENT,
                source_id=f"task-instruction:{self._task.benchmark_task_id}",
                project_scope=project_id,
                content=self._task.instruction,
                priority=100,
            )
        ]
        for entry in self._task.initial_state.entries:
            if entry.key == "taskFocus" and hasattr(entry, "value"):
                value = getattr(entry, "value")
                if isinstance(value, str) and value.strip():
                    items.append(
                        ContextItem(
                            source_type=ContextSource.SHORT_TERM_CONTEXT,
                            source_id=f"task-focus:{self._task.benchmark_task_id}",
                            project_scope=project_id,
                            content=value,
                            priority=90,
                        )
                    )
        policy = ContextPolicy(
            source_precedence=(
                ContextSource.USER_INTENT,
                ContextSource.SHORT_TERM_CONTEXT,
                ContextSource.API_METADATA,
                ContextSource.EXECUTION_FACT,
                ContextSource.RAG_EVIDENCE,
                ContextSource.HISTORICAL_MEMORY,
            ),
            per_item_char_budget=4_096,
            total_char_budget=8_192,
        )
        return ContextEnrichmentResult(
            status=ContextEnrichmentStatus.READY,
            context_pack=ContextPackBuilder(policy, project_scope=project_id).build(items),
        )


class RealModelStage20WorkflowAdapter:
    """Execute each task through an existing AgentLab workflow boundary.

    Java is optional at construction time so model-only tasks can be measured
    when the local Java service is unavailable.  When a task has a Java
    boundary and a token provider is supplied, the existing Stage 20 workflow
    is used unchanged and Java-owned references are retained.
    """

    def __init__(
        self,
        llm: LLMClient,
        *,
        java_client: JavaApiOpsClient | None = None,
        token_provider: Callable[[], str] | None = None,
        repository_root: Path | None = None,
        diagnosis_observer: Callable[..., None] | None = None,
    ) -> None:
        if not isinstance(llm, LLMClient):
            raise TypeError("llm must implement LLMClient")
        if java_client is not None and not isinstance(java_client, JavaApiOpsClient):
            raise TypeError("java_client must be a JavaApiOpsClient")
        if java_client is not None and not callable(token_provider):
            raise TypeError("token_provider is required when java_client is configured")
        self._llm = llm
        self._diagnosis_observer = diagnosis_observer
        self._java_client = java_client
        self._token_provider = token_provider
        self._repository_root = (repository_root or Path(__file__).resolve().parents[2]).resolve()
        self._execution_prerequisites = load_stage21_prerequisites()

    @property
    def java_enabled(self) -> bool:
        return self._java_client is not None and self._token_provider is not None

    async def execute(
        self,
        task: BenchmarkTask,
        setup: FixtureSetup,
        *,
        trace_id: str,
        agent_run_id: str,
    ) -> BenchmarkExecutionOutcome:
        del setup
        recorder = TraceRecorder()
        self._require_project_id(task)
        plan = self._execution_plan(task)
        if plan.java.required and not self.java_enabled:
            if plan.java.tool_gateway:
                self._record_unavailable_tool_planning(
                    task,
                    trace_id=trace_id,
                    agent_run_id=agent_run_id,
                    recorder=recorder,
                )
            return self._outcome(
                trace_id=trace_id,
                agent_run_id=agent_run_id,
                recorder=recorder,
                execution_mode=BenchmarkExecutionMode.UNKNOWN,
                java_execution_status=JavaExecutionStatus.REQUIRED_BUT_UNAVAILABLE,
            )
        try:
            if task.task_type is TaskType.TESTCASE_GENERATION:
                return await self._execute_generation(task, trace_id, agent_run_id, recorder)
            if task.task_type is TaskType.E2E_APIOPS:
                return await self._execute_e2e(task, trace_id, agent_run_id, recorder)
            return await self._execute_diagnosis_family(
                task,
                trace_id,
                agent_run_id,
                recorder,
            )
        except BenchmarkTaskFailure:
            raise
        except (DiagnosisCandidateParseError, DiagnosisIdentityError) as exc:
            raise BenchmarkTaskFailure(
                str(exc),
                category=BenchmarkFailureCategory.AGENT_FAILURE,
                code="MODEL_OUTPUT_FAILURE",
                partial_outcome=self._outcome(
                    trace_id=trace_id,
                    agent_run_id=agent_run_id,
                    recorder=recorder,
                    execution_mode=(
                        BenchmarkExecutionMode.REAL_MODEL
                        if recorder.typed_records
                        else BenchmarkExecutionMode.UNKNOWN
                    ),
                    java_execution_status=(
                        JavaExecutionStatus.EXECUTED
                        if plan.java.required and self.java_enabled
                        else JavaExecutionStatus.NOT_APPLICABLE
                    ),
                ),
            ) from exc
        except JavaApiOpsError as exc:
            if plan.java.required and self.java_enabled:
                raise BenchmarkTaskFailure(
                    f"required Java execution path failed: {exc}",
                    category=BenchmarkFailureCategory.INFRASTRUCTURE_FAILURE,
                    code="JAVA_REQUIRED_PATH_FAILED",
                    partial_outcome=self._outcome(
                        trace_id=trace_id,
                        agent_run_id=agent_run_id,
                        recorder=recorder,
                        execution_mode=(
                            BenchmarkExecutionMode.REAL_MODEL
                            if recorder.typed_records
                            else BenchmarkExecutionMode.UNKNOWN
                        ),
                        java_execution_status=JavaExecutionStatus.EXECUTION_FAILED,
                    ),
                ) from exc
            raise

    async def _execute_generation(
        self,
        task: BenchmarkTask,
        trace_id: str,
        agent_run_id: str,
        recorder: TraceRecorder,
    ) -> BenchmarkExecutionOutcome:
        project_id = self._require_project_id(task)
        strategy = self._strategy(task)
        metadata = await self._metadata_for_task_async(task, project_id, trace_id)
        assessment = assess_strategy(metadata, strategy)
        if not assessment.applicable:
            raise BenchmarkTaskFailure(
                f"strategy {strategy.value} is not supported by the task metadata",
                category=BenchmarkFailureCategory.CONTRACT_FAILURE,
                code="TASK_STRATEGY_NOT_APPLICABLE",
            )
        generation_context = build_generation_context(metadata, strategy)
        prerequisite = self._execution_prerequisites.get(task.benchmark_task_id)
        intentional_invalidity = self._intentional_invalidity_spec(
            task,
            prerequisite=prerequisite,
            project_id=project_id,
            generation_context=generation_context,
        )
        graph = build_testcase_generation_graph(
            TestCaseGenerator(self._llm),
            context_enricher=_TaskContextEnricher(task, project_id),
            trace_recorder=recorder,
            preserve_intentional_invalidity=(
                prerequisite is not None
                and prerequisite.candidate_validation_policy
                == "PRESERVE_INTENTIONAL_INVALIDITY"
            ),
            intentional_invalidity=intentional_invalidity,
        )
        state: APIOpsAgentState = {
            "trace_id": trace_id,
            "agent_run_id": agent_run_id,
            "phase": WorkflowPhase.INITIAL,
            "route": None,
            "error": None,
            "attempt_count": 0,
            "max_attempts": 0,
            "project_id": project_id,
            "api_id": metadata.api_id,
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
        generated = await graph.ainvoke(state)
        candidate = generated.get("candidate")
        validation = generated.get("validation_result")
        requirements = self._java_requirements(task)
        java_runner_status: str | None = None
        report: TestReport | None = None
        run_id: int | None = None
        report_id: str | None = None
        authority_references: tuple[str, ...] = ()
        if requirements.runner:
            workflow = Stage20ExecutionWorkflow(
                self._java_client,  # type: ignore[arg-type]
                TestCaseGenerator(self._llm),
                token_provider=self._token_provider,  # type: ignore[arg-type]
                trace_recorder=recorder,
            )
            testcase = workflow.accepted_testcase(generated)
            execution = await workflow.execute_prepared_testcase(
                project_id=project_id,
                testcase=testcase,
                trace_id=trace_id,
                agent_run_id=agent_run_id,
            )
            report = execution.report
            java_runner_status = report.status
            run_id = report.run_id
            report_id = report.report_id
            authority_references = self._java_references(execution)
        facts = self._generation_facts(
            candidate,
            validation,
            strategy,
            generation_status=generated.get("generation_status"),
            metadata=metadata,
            generation_context=generation_context,
            metadata_authority=("JAVA_OPENAPI_BASELINE" if requirements.metadata else None),
            java_runner_status=java_runner_status,
            runner_authority=requirements.runner,
            task_focus=self._task_focus(task),
        )
        if report is not None:
            # Runner-required generation is complete only after the Java report
            # has been projected.  Keeping just its terminal status loses
            # authoritative response/assertion facts (for example a proven 409
            # business outcome) even though the report was already read.
            facts = assemble_outcome_facts(
                base=facts,
                report=report,
                report_java_authority=True,
            )
        return self._outcome(
            trace_id=trace_id,
            agent_run_id=agent_run_id,
            recorder=recorder,
            facts=facts,
            run_id=run_id,
            report_id=report_id,
            authority_references=authority_references,
            java_execution_status=(
                JavaExecutionStatus.EXECUTED
                if requirements.metadata or requirements.runner
                else JavaExecutionStatus.NOT_APPLICABLE
            ),
        )

    @staticmethod
    def _json_pointer_value(root: object, pointer: str) -> tuple[bool, object | None]:
        current = root
        if not pointer.startswith("/"):
            return False, None
        for raw_token in pointer[1:].split("/"):
            token = raw_token.replace("~1", "/").replace("~0", "~")
            if isinstance(current, dict) and token in current:
                current = current[token]
            elif isinstance(current, list) and token.isdigit() and int(token) < len(current):
                current = current[int(token)]
            else:
                return False, None
        return True, current

    @classmethod
    def _specific_invalidity_path(
        cls,
        candidate: dict[str, object],
        path: str,
    ) -> str:
        """Refine assertion oneOf errors using only the input-side candidate shape."""

        present, node = cls._json_pointer_value(candidate, path)
        if not present or not isinstance(node, dict):
            return path
        assertion_type = node.get("type")
        supported = {"STATUS_CODE", "HEADER", "JSON_PATH", "RESPONSE_TIME"}
        if isinstance(assertion_type, str) and assertion_type not in supported:
            return f"{path}/type"
        if assertion_type == "STATUS_CODE" and "expected" not in node:
            return f"{path}/expected"
        if (
            assertion_type == "JSON_PATH"
            and node.get("operator") == "EQUALS"
            and "expected" not in node
        ):
            return f"{path}/expected"
        return path

    def _intentional_invalidity_spec(
        self,
        task: BenchmarkTask,
        *,
        prerequisite: Stage21Prerequisite | None,
        project_id: int,
        generation_context: GenerationContext,
    ) -> IntentionalInvaliditySpec | None:
        if (
            prerequisite is None
            or prerequisite.candidate_validation_policy
            != "PRESERVE_INTENTIONAL_INVALIDITY"
        ):
            return None
        fixture_refs = tuple(
            str(getattr(entry, "ref", ""))
            for entry in task.initial_state.entries
            if entry.kind == "PYTHON_FIXTURE"
            and entry.key in {"taskFixture", "candidateFixture"}
        )
        if len(fixture_refs) != 1:
            raise BenchmarkTaskFailure(
                "intentional-invalidity policy requires exactly one input-side candidate fixture",
                category=BenchmarkFailureCategory.CONTRACT_FAILURE,
                code="INTENTIONAL_INVALIDITY_FIXTURE_AMBIGUOUS",
            )
        payload = self._read_json_ref(fixture_refs[0])
        if payload is None:
            raise BenchmarkTaskFailure(
                "intentional-invalidity input-side candidate fixture is unavailable",
                category=BenchmarkFailureCategory.CONTRACT_FAILURE,
                code="INTENTIONAL_INVALIDITY_FIXTURE_UNAVAILABLE",
            )
        validation = validate_candidate(
            Candidate(raw=json.dumps(payload, ensure_ascii=False), structured=payload),
            project_id=project_id,
            generation_context=generation_context,
        )
        schema_issues = tuple(issue for issue in validation.issues if issue.layer == "SCHEMA")
        if len(schema_issues) != 1:
            raise BenchmarkTaskFailure(
                "intentional-invalidity fixture must expose exactly one schema issue",
                category=BenchmarkFailureCategory.CONTRACT_FAILURE,
                code="INTENTIONAL_INVALIDITY_SPEC_UNRESOLVED",
            )
        issue = schema_issues[0]
        path = self._specific_invalidity_path(payload, issue.path)
        present, invalid_value = self._json_pointer_value(payload, path)
        if present and path == issue.path and issue.code == "SHARED_SCHEMA_ONE_OF":
            raise BenchmarkTaskFailure(
                "intentional-invalidity assertion issue is not specific enough to preserve",
                category=BenchmarkFailureCategory.CONTRACT_FAILURE,
                code="INTENTIONAL_INVALIDITY_SPEC_UNRESOLVED",
            )
        return IntentionalInvaliditySpec(
            issue_code=issue.code,
            path=path,
            preservation="VALUE" if present else "MISSING",
            invalid_value=invalid_value,
        )

    async def _execute_e2e(
        self,
        task: BenchmarkTask,
        trace_id: str,
        agent_run_id: str,
        recorder: TraceRecorder,
    ) -> BenchmarkExecutionOutcome:
        project_id = self._require_project_id(task)
        plan = self._execution_plan(task)
        facts = EvaluationFacts()
        report: TestReport | None = None
        java_report = False
        run_id: int | None = None
        report_id: str | None = None
        authority_references: tuple[str, ...] = ()
        mapping_status: str | None = None
        mapping_error_code: str | None = None
        if plan.generate and plan.java.runner:
            workflow = Stage20ExecutionWorkflow(
                self._java_client,  # type: ignore[arg-type]
                TestCaseGenerator(self._llm),
                token_provider=self._token_provider,  # type: ignore[arg-type]
                context_enricher=_TaskContextEnricher(task, project_id),
                trace_recorder=recorder,
            )
            execution = await workflow.execute(
                project_id=project_id,
                api_id=self._api_id(task),
                strategy=self._strategy(task),
                trace_id=trace_id,
                agent_run_id=agent_run_id,
            )
            report = execution.report
            facts = self._generation_facts(
                execution.testcase,
                None,
                self._strategy(task),
                generation_status="ACCEPTED",
                java_runner_status=execution.report.status,
                metadata=execution.metadata,
                metadata_authority="JAVA_OPENAPI_BASELINE",
                runner_authority=True,
                # Stage20 returns this value only after its existing
                # _accepted_testcase contract gate has succeeded.
                schema_authority=True,
                contract_authority=True,
                task_focus=self._task_focus(task),
            )
            java_report = True
            run_id = report.run_id
            report_id = report.report_id
            authority_references = self._java_references(execution)
        elif plan.generate:
            generation_outcome = await self._execute_generation(
                task,
                trace_id,
                agent_run_id,
                recorder,
            )
            facts = generation_outcome.facts
        if plan.diagnose:
            if report is None:
                report, java_report = await self._report_for_task(
                    task,
                    project_id=project_id,
                    trace_id=trace_id,
                    agent_run_id=agent_run_id,
                    recorder=recorder,
                )
                if java_report:
                    run_id = report.run_id
                    report_id = report.report_id
                    authority_references = (
                        f"java:run:{report.run_id}",
                        f"java:report:{report.report_id}",
                    )
                elif not plan.fixture_report_allowed:
                    raise BenchmarkTaskFailure(
                        "E2E diagnosis requires an execution/report boundary",
                        category=BenchmarkFailureCategory.CONTRACT_FAILURE,
                        code="E2E_REPORT_BOUNDARY_REQUIRED",
                    )
            diagnosis_facts, diagnosis_state = await self._run_diagnosis(
                task,
                report,
                project_id,
                trace_id,
                agent_run_id,
                recorder,
                report_java_authority=java_report,
            )
            facts = self._merge_facts(facts, diagnosis_facts)
            mapping_status = diagnosis_state.get("tool_result_mapping_status")
            mapping_error_code = diagnosis_state.get("tool_result_mapping_error_code")
        target_project_id = self._runtime_tool_contract(task)[3]
        facts = assemble_outcome_facts(
            base=facts,
            report=report,
            report_java_authority=java_report,
            records=recorder.typed_records,
            trusted_project_id=target_project_id or project_id,
            safe_tool_names=task.allowed_tools,
            trace_complete=True,
        )
        return self._outcome(
            trace_id=trace_id,
            agent_run_id=agent_run_id,
            recorder=recorder,
            facts=facts,
            run_id=run_id,
            report_id=report_id,
            authority_references=authority_references,
            mapping_status=mapping_status,
            mapping_error_code=mapping_error_code,
            java_execution_status=(
                JavaExecutionStatus.EXECUTED
                if plan.java.required
                else JavaExecutionStatus.NOT_APPLICABLE
            ),
        )

    async def _execute_diagnosis_family(
        self,
        task: BenchmarkTask,
        trace_id: str,
        agent_run_id: str,
        recorder: TraceRecorder,
    ) -> BenchmarkExecutionOutcome:
        project_id = self._require_project_id(task)
        report, java_report = await self._report_for_task(
            task,
            project_id=project_id,
            trace_id=trace_id,
            agent_run_id=agent_run_id,
            recorder=recorder,
        )
        facts, diagnosis_state = await self._run_diagnosis(
            task,
            report,
            project_id,
            trace_id,
            agent_run_id,
            recorder,
            report_java_authority=java_report,
        )
        return self._outcome(
            trace_id=trace_id,
            agent_run_id=agent_run_id,
            recorder=recorder,
            facts=facts,
            run_id=report.run_id if java_report else None,
            report_id=report.report_id if java_report else None,
            authority_references=(
                (f"java:run:{report.run_id}", f"java:report:{report.report_id}")
                if java_report
                else ()
            ),
            mapping_status=diagnosis_state.get("tool_result_mapping_status"),
            mapping_error_code=diagnosis_state.get("tool_result_mapping_error_code"),
            java_execution_status=(
                JavaExecutionStatus.EXECUTED
                if self._java_requirements(task).required
                else JavaExecutionStatus.NOT_APPLICABLE
            ),
        )

    async def _run_diagnosis(
        self,
        task: BenchmarkTask,
        report: TestReport,
        project_id: int,
        trace_id: str,
        agent_run_id: str,
        recorder: TraceRecorder,
        *,
        report_java_authority: bool = False,
    ) -> tuple[EvaluationFacts, dict[str, object]]:
        adapters: dict[str, object] = {}
        if self.java_enabled:
            from app.clients.java_apiops import JavaApiOpsToolGatewayAdapter

            java_gateway = JavaApiOpsToolGatewayAdapter(
                self._java_client,  # type: ignore[arg-type]
                project_id=project_id,
                token_provider=self._token_provider,  # type: ignore[arg-type]
            )
        else:
            java_gateway = None
        approved_catalog = ToolCatalog()
        allowed_tools = set(task.allowed_tools)
        catalog = ToolCatalog(
            descriptor
            for descriptor in approved_catalog.list_descriptors()
            if descriptor.name in allowed_tools
        )
        if java_gateway is not None:
            adapters = {descriptor.name: java_gateway for descriptor in catalog.list_descriptors()}
        router = ToolRouter(catalog, adapters)
        supporting_context = self._diagnosis_context(task, project_id)
        contract = self._runtime_tool_contract(task)
        selected_tool = contract[1]
        planning_decision = self._tool_planning_decision(
            task,
            report,
            supporting_context,
            project_id=project_id,
            capability_available=(
                selected_tool is not None
                and java_gateway is not None
                and catalog.contains(selected_tool)
                and selected_tool in adapters
            ),
        )
        prerequisite = self._execution_prerequisites.get(task.benchmark_task_id)
        terminal_execution = prerequisite is not None and (
            prerequisite.terminal_safety_decision is not None
            or "NO_TOOL_CALL" in prerequisite.required_operations
        )
        if terminal_execution:
            denied = planning_decision.requirement is ToolRequirement.DENY
            recorder.record(
                ToolPlanningRecord(
                    trace_id=trace_id,
                    agent_run_id=agent_run_id,
                    workflow_id=f"diagnosis:{agent_run_id}",
                    project_id=project_id,
                    event=TraceEvent.DECISION,
                    status=TraceStatus.DENIED if denied else TraceStatus.SUCCESS,
                    failure=(
                        failure_detail(
                            "TOOL_PLANNING_DENIED",
                            planning_decision.reason,
                            code="RUNTIME_POLICY_DENY",
                        )
                        if denied
                        else None
                    ),
                    requirement=planning_decision.requirement,
                    selected_tool=planning_decision.selected_tool,
                    reason=planning_decision.reason,
                    evidence_sufficiency=planning_decision.evidence_sufficiency,
                    authority_source=planning_decision.authority_source,
                    allowed=planning_decision.allowed,
                    capability_available=planning_decision.capability_available,
                )
            )
            self._record_prerequisite_safety_authority(
                task,
                project_id=project_id,
                trace_id=trace_id,
                agent_run_id=agent_run_id,
                recorder=recorder,
            )
            projected = assemble_outcome_facts(
                report=report,
                report_java_authority=report_java_authority,
                records=recorder.typed_records,
                trusted_project_id=contract[3] or project_id,
                safe_tool_names=task.allowed_tools,
                trace_complete=True,
            )
            return projected, {
                "tool_result_mapping_status": "NOT_APPLICABLE",
                "tool_result_mapping_error_code": None,
                "rag_evidence_count": 0,
            }
        required_tool_intent = self._required_tool_intent(
            task,
            planning_decision,
        )
        workflow = build_diagnosis_workflow(
            self._llm,
            router,
            project_id=project_id,
            catalog=catalog,
            checkpointer=InMemorySaver(),
            trace_recorder=recorder,
            planning_decision=planning_decision,
            required_tool_intent=required_tool_intent,
            retrieval_only=task.task_type is TaskType.RAG_EVIDENCE_RETRIEVAL,
        )
        state = diagnosis_initial_state(
            report,
            trace_id=trace_id,
            agent_run_id=agent_run_id,
            workflow_id=f"diagnosis:{agent_run_id}",
            supporting_context=supporting_context,
        )
        config = checkpoint_config(f"diagnosis:{agent_run_id}")
        result = await workflow.ainvoke(
            state,
            config=config,
        )
        if prerequisite is not None and prerequisite.approval_decision is not None:
            result = await workflow.ainvoke(
                self._approved_resume_command(result, prerequisite),
                config=config,
            )
        diagnosis = result.get("diagnosis_report")
        tool_call = result.get("tool_call")
        observed_tools: tuple[ObservedToolArguments, ...] = ()
        if isinstance(tool_call, ToolCall):
            observed_tools = (
                ObservedToolArguments(
                    tool_name=tool_call.tool_name,
                    arguments=tool_call.params,
                    tool_intent_id=(
                        result.get("intent_id")
                        if isinstance(result.get("intent_id"), str)
                        else None
                    ),
                ),
            )
        projected_diagnosis = diagnosis if isinstance(diagnosis, DiagnosisReport) else None
        target_project_id = contract[3]
        projected = assemble_outcome_facts(
            report=report,
            report_java_authority=report_java_authority,
            diagnosis=projected_diagnosis,
            records=recorder.typed_records,
            trusted_project_id=target_project_id or project_id,
            safe_tool_names=task.allowed_tools,
            trace_complete=True,
        )
        contract_facts = ()
        final_context = result.get("context_pack")
        if self._diagnosis_observer is not None and projected_diagnosis is not None:
            self._diagnosis_observer(
                task, projected_diagnosis, final_context, recorder.typed_records,
            )
        if (
            MetricName.DIAGNOSIS_CONTRACT in task.evaluation_spec.selected_metrics
            and projected_diagnosis is not None and isinstance(final_context, ContextPack)
        ):
            contract_facts = (StructuredFact(
                name="diagnosis_contract_observation",
                value=observe_diagnosis_contract(
                    projected_diagnosis.model_dump(mode="json"), context_payload(final_context)
                ),
            ),)
        return merge_evaluation_facts(
            projected,
            EvaluationFacts(tool_arguments=observed_tools, structured_facts=contract_facts),
        ), result

    @staticmethod
    def _literal_int(task: BenchmarkTask, key: str) -> int | None:
        for entry in task.initial_state.entries:
            value = getattr(entry, "value", None)
            if (
                entry.kind == "LITERAL"
                and entry.key == key
                and isinstance(value, int)
                and not isinstance(value, bool)
                and value > 0
            ):
                return value
        return None

    def _runtime_diagnosis_facts(self, task: BenchmarkTask) -> dict[str, object]:
        """Read only allow-listed structured runtime facts from task fixtures."""

        allowed_keys = {
            "failuretype",
            "responsesnapshotpresent",
            "responsebodypresent",
            "assertioncount",
            "diagnosisboundary",
            "runnerstatus",
            "missingevidence",
            "conflicttype",
        }
        facts: dict[str, object] = {}
        for entry in task.initial_state.entries:
            if entry.kind != "PYTHON_FIXTURE" or entry.key not in {
                "diagnosisContext",
                "taskFixture",
            }:
                continue
            payload = self._read_json_ref(str(getattr(entry, "ref", "")))
            if not isinstance(payload, dict):
                continue
            candidate = payload.get("facts")
            candidate = candidate if isinstance(candidate, dict) else payload
            for key, value in candidate.items():
                normalized = re.sub(r"[^a-z0-9]", "", str(key).lower())
                if normalized in allowed_keys:
                    facts[key] = value
        return facts

    def _require_project_id(self, task: BenchmarkTask) -> int:
        project_id = RealModelStage20WorkflowAdapter._project_id(task)
        prerequisite = self._execution_prerequisites.get(task.benchmark_task_id)
        if (
            project_id is None
            and prerequisite is not None
            and prerequisite.current_project_id is not None
            and set(prerequisite.required_operations) == {"NO_JAVA_ACCESS"}
        ):
            # Benchmark-local generation still needs a deterministic DSL/context
            # namespace.  The input-side prerequisite supplies it without granting
            # or invoking Java access.
            project_id = prerequisite.current_project_id
        if project_id is None:
            raise BenchmarkTaskFailure(
                "trusted canonical project identity is required before execution",
                category=BenchmarkFailureCategory.CONTRACT_FAILURE,
                code="PROJECT_IDENTITY_MISSING",
            )
        return project_id

    def _tool_planning_decision(
        self,
        task: BenchmarkTask,
        report: TestReport,
        context_items: tuple[ContextItem, ...],
        *,
        project_id: int,
        capability_available: bool,
    ) -> ToolPlanningDecision:
        observed_facts = self._runtime_diagnosis_facts(task)
        sufficiency = assess_evidence_sufficiency(
            report,
            context_items,
            observed_facts=observed_facts,
        )
        runtime_requirement, selected_tool, query_source, _ = self._runtime_tool_contract(task)
        return decide_tool_requirement(
            task.task_type,
            evidence_sufficiency=sufficiency,
            allowed_tools=task.allowed_tools,
            instruction=task.instruction,
            context=context_items,
            project_id=project_id,
            query_source=query_source,
            capability_available=capability_available,
            runtime_requirement=runtime_requirement,
            selected_tool=selected_tool,
        )

    def _record_unavailable_tool_planning(
        self,
        task: BenchmarkTask,
        *,
        trace_id: str,
        agent_run_id: str,
        recorder: TraceRecorder,
    ) -> None:
        project_id = self._require_project_id(task)
        if project_id is None:
            return
        runtime_requirement, selected_tool, query_source, _ = self._runtime_tool_contract(task)
        decision = decide_tool_requirement(
            task.task_type,
            evidence_sufficiency=EvidenceSufficiency.UNRESOLVED,
            allowed_tools=task.allowed_tools,
            instruction=task.instruction,
            context=(self._task_focus(task) or "",),
            project_id=project_id,
            query_source=query_source,
            capability_available=False,
            runtime_requirement=runtime_requirement,
            selected_tool=selected_tool,
        )
        recorder.record(
            ToolPlanningRecord(
                trace_id=trace_id,
                agent_run_id=agent_run_id,
                workflow_id=f"diagnosis:{agent_run_id}",
                project_id=project_id,
                event=TraceEvent.DECISION,
                status=TraceStatus.FAILED,
                failure=failure_detail(
                    "TOOL_PLANNING_UNRESOLVED",
                    "required runtime tool capability is unavailable before execution.",
                    code="RUNTIME_TOOL_CAPABILITY_UNAVAILABLE",
                ),
                requirement=decision.requirement,
                selected_tool=decision.selected_tool,
                reason=decision.reason,
                evidence_sufficiency=decision.evidence_sufficiency,
                authority_source=decision.authority_source,
                allowed=decision.allowed,
                capability_available=decision.capability_available,
            )
        )

    def _required_tool_intent(
        self,
        task: BenchmarkTask,
        decision: ToolPlanningDecision,
    ) -> ToolIntent | None:
        if decision.requirement is not ToolRequirement.REQUIRED:
            return None
        _, _, query_source, target_project_id = self._runtime_tool_contract(task)
        prerequisite = self._execution_prerequisites.get(task.benchmark_task_id)
        try:
            return build_tool_intent(
                decision,
                query_source=(query_source if decision.selected_tool == "rag.search" else None),
                arguments=(
                    prerequisite.approved_tool_arguments
                    if prerequisite is not None and decision.selected_tool != "rag.search"
                    else None
                ),
                target_project_id=target_project_id,
                top_k=self._rag_top_k(task),
            )
        except ToolPlanningError as exc:
            raise BenchmarkTaskFailure(
                str(exc),
                category=BenchmarkFailureCategory.CONTRACT_FAILURE,
                code="TOOL_ARGUMENT_SOURCE_INVALID",
            ) from exc

    @staticmethod
    def _approved_resume_command(
        interrupted: dict[str, object],
        prerequisite: Stage21Prerequisite,
    ) -> Command:
        """Bind one input-side approval to the workflow's exact interrupted intent."""

        interrupts = interrupted.get("__interrupt__")
        if not isinstance(interrupts, (tuple, list)) or len(interrupts) != 1:
            raise BenchmarkTaskFailure(
                "approved execution prerequisite did not produce one approval request",
                category=BenchmarkFailureCategory.CONTRACT_FAILURE,
                code="EXECUTION_APPROVAL_REQUEST_MISSING",
            )
        raw_request = getattr(interrupts[0], "value", None)
        try:
            request = ApprovalRequest.model_validate(raw_request)
        except Exception as exc:
            raise BenchmarkTaskFailure(
                "workflow approval request did not match the intent-bound contract",
                category=BenchmarkFailureCategory.CONTRACT_FAILURE,
                code="EXECUTION_APPROVAL_REQUEST_INVALID",
            ) from exc
        approved_arguments = prerequisite.approved_tool_arguments
        if (
            prerequisite.approval_decision != ApprovalAction.APPROVE.value
            or prerequisite.approval_authority
            != "BENCHMARK_EXECUTION_PREREQUISITE"
            or prerequisite.selected_tool != request.tool_name
            or approved_arguments is None
            or request.arguments_fingerprint
            != fingerprint_arguments(approved_arguments)
        ):
            raise BenchmarkTaskFailure(
                "execution prerequisite approval is not bound to the interrupted intent",
                category=BenchmarkFailureCategory.CONTRACT_FAILURE,
                code="EXECUTION_APPROVAL_BINDING_MISMATCH",
            )
        decision = ApprovalDecision.model_validate(
            request.model_dump(mode="json")
            | {
                "decision": ApprovalAction.APPROVE,
                "edited_arguments": None,
            }
        )
        return Command(resume=decision.model_dump(mode="json"))

    def _runtime_tool_contract(
        self,
        task: BenchmarkTask,
    ) -> tuple[ToolRequirement | None, str | None, str, int | None]:
        """Resolve the checked-in execution prerequisite without expected-side data."""

        prerequisite = self._execution_prerequisites.get(task.benchmark_task_id)
        if prerequisite is None:
            return None, None, self._canonical_query(task), None
        project_id = self._require_project_id(task)
        if project_id != prerequisite.current_project_id:
            raise BenchmarkTaskFailure(
                "task project does not match the Stage 21 execution prerequisite",
                category=BenchmarkFailureCategory.CONTRACT_FAILURE,
                code="EXECUTION_PREREQUISITE_PROJECT_MISMATCH",
            )
        operations = set(prerequisite.required_operations)
        if prerequisite.terminal_safety_decision in {
            "FORBIDDEN_INTENT_DENIED",
            "PROMPT_INJECTION_DENIED",
        }:
            return (
                ToolRequirement.DENY,
                prerequisite.selected_tool,
                self._canonical_query(task),
                prerequisite.target_project_id,
            )
        if "TOOL_CALL" in operations:
            requirement = ToolRequirement.REQUIRED
        elif "NO_JAVA_ACCESS" in operations or "NO_TOOL_CALL" in operations:
            requirement = ToolRequirement.NOT_REQUIRED
        elif operations and operations <= {
            "READ_REPORT",
            "RUNNER_SUBMIT",
            "RUNNER_STATUS",
            "OPENAPI_METADATA_READ",
        }:
            # These operations are Java execution/read authorities, not Agent
            # tool requests.  A complete prerequisite with no TOOL_CALL must
            # let diagnosis run against the returned Java facts instead of
            # manufacturing an unresolved tool-policy blocker.
            requirement = ToolRequirement.NOT_REQUIRED
        else:
            return None, None, self._canonical_query(task), prerequisite.target_project_id
        if requirement is ToolRequirement.NOT_REQUIRED:
            return (
                requirement,
                None,
                self._canonical_query(task),
                prerequisite.target_project_id,
            )
        if prerequisite.selected_tool is not None:
            selected_tool = prerequisite.selected_tool
        elif "RAG_SEARCH" in operations:
            selected_tool = "rag.search"
        elif len(task.allowed_tools) == 1:
            selected_tool = task.allowed_tools[0]
        else:
            selected_tool = None
        return (
            requirement,
            selected_tool,
            self._canonical_query(task),
            prerequisite.target_project_id,
        )

    def _record_prerequisite_safety_authority(
        self,
        task: BenchmarkTask,
        *,
        project_id: int,
        trace_id: str,
        agent_run_id: str,
        recorder: TraceRecorder,
    ) -> None:
        """Retain typed terminal authority supplied by deterministic safety fixtures."""

        prerequisite = self._execution_prerequisites.get(task.benchmark_task_id)
        if prerequisite is None or prerequisite.terminal_safety_decision is None:
            return
        terminal = prerequisite.terminal_safety_decision
        tool_name = prerequisite.selected_tool or (
            task.allowed_tools[0] if len(task.allowed_tools) == 1 else "untrusted.result"
        )
        workflow_id = f"diagnosis:{agent_run_id}"
        intent_id = f"fixture-intent:{task.benchmark_task_id}"
        fingerprint = hashlib.sha256(intent_id.encode("utf-8")).hexdigest()
        if terminal == "APPROVAL_REQUIRED":
            recorder.record(
                ApprovalFact(
                    trace_id=trace_id,
                    agent_run_id=agent_run_id,
                    workflow_id=workflow_id,
                    project_id=project_id,
                    status=TraceStatus.INTERRUPTED,
                    intent_id=intent_id,
                    tool_name=tool_name,
                    arguments_fingerprint=fingerprint,
                )
            )
        elif terminal == "HUMAN_REJECTED":
            recorder.record(
                ApprovalFact(
                    trace_id=trace_id,
                    agent_run_id=agent_run_id,
                    workflow_id=workflow_id,
                    project_id=project_id,
                    event=TraceEvent.DECISION,
                    status=TraceStatus.REJECTED,
                    failure=failure_detail(
                        "HUMAN_REJECTED",
                        "deterministic benchmark approval fixture rejected the tool intent.",
                    ),
                    intent_id=intent_id,
                    tool_name=tool_name,
                    arguments_fingerprint=fingerprint,
                    decision=ApprovalAction.REJECT,
                )
            )
        elif terminal == "PROMPT_INJECTION_DENIED":
            recorder.record(
                SafetyViolationFact(
                    trace_id=trace_id,
                    agent_run_id=agent_run_id,
                    project_id=project_id,
                    status=TraceStatus.DENIED,
                    failure=failure_detail(
                        "SAFETY_VIOLATION",
                        "deterministic prompt-injection fixture was rejected.",
                        code="PROMPT_INJECTION_DETECTED",
                    ),
                    code=ViolationCode.PROMPT_INJECTION_DETECTED,
                    source=EvidenceSource.TOOL_RESULT,
                    tool_name=tool_name,
                    summary="prompt-injection content rejected before tool routing",
                )
            )

    def _canonical_query(self, task: BenchmarkTask) -> str:
        """Return bounded retrieval intent, never the whole task instruction."""

        try:
            recipe = resolve_stage21_rag_runtime_recipe(task)
        except Stage21RagRuntimeRecipeResolutionError as exc:
            raise BenchmarkTaskFailure(
                str(exc),
                category=BenchmarkFailureCategory.CONTRACT_FAILURE,
                code=exc.code,
            ) from exc
        if recipe is not None:
            return recipe.query
        focus = self._task_focus(task)
        return focus or "project-scoped diagnostic evidence"

    @staticmethod
    def _rag_top_k(task: BenchmarkTask) -> int:
        try:
            recipe = resolve_stage21_rag_runtime_recipe(task)
        except Stage21RagRuntimeRecipeResolutionError as exc:
            raise BenchmarkTaskFailure(
                str(exc),
                category=BenchmarkFailureCategory.CONTRACT_FAILURE,
                code=exc.code,
            ) from exc
        return recipe.top_k if recipe is not None else 5

    def _diagnosis_context(
        self,
        task: BenchmarkTask,
        project_id: int,
    ) -> tuple[ContextItem, ...]:
        items = [
            ContextItem(
                source_type=ContextSource.USER_INTENT,
                source_id=f"task-instruction:{task.benchmark_task_id}",
                project_scope=project_id,
                content=task.instruction,
                priority=100,
            )
        ]
        for entry in task.initial_state.entries:
            if entry.key == "taskFocus" and hasattr(entry, "value"):
                value = getattr(entry, "value")
                if isinstance(value, str) and value.strip():
                    items.append(
                        ContextItem(
                            source_type=ContextSource.SHORT_TERM_CONTEXT,
                            source_id=f"task-focus:{task.benchmark_task_id}",
                            project_scope=project_id,
                            content=value,
                            priority=90,
                        )
                    )
        runtime_facts = self._runtime_diagnosis_facts(task)
        if runtime_facts:
            items.append(
                ContextItem(
                    source_type=ContextSource.SHORT_TERM_CONTEXT,
                    source_id=f"runtime-facts:{task.benchmark_task_id}",
                    project_scope=project_id,
                    content=json.dumps(
                        runtime_facts,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                    priority=95,
                )
            )
        return tuple(items)

    async def _report_for_task(
        self,
        task: BenchmarkTask,
        *,
        project_id: int,
        trace_id: str,
        agent_run_id: str,
        recorder: TraceRecorder,
    ) -> tuple[TestReport, bool]:
        if is_stage21_initial_report_task(task):
            if not self.java_enabled:
                raise BenchmarkTaskFailure(
                    "Java initial TestReport is required for this input",
                    category=BenchmarkFailureCategory.INFRASTRUCTURE_FAILURE,
                    code="JAVA_INITIAL_REPORT_UNAVAILABLE",
                )
            try:
                reference = resolve_stage21_initial_report_reference(task)
            except Stage21InitialReportReferenceError as exc:
                raise BenchmarkTaskFailure(
                    str(exc),
                    category=BenchmarkFailureCategory.CONTRACT_FAILURE,
                    code=exc.code,
                ) from exc
            if reference is None or reference.project_id != project_id:
                raise BenchmarkTaskFailure(
                    "Java initial TestReport reference does not match the trusted project",
                    category=BenchmarkFailureCategory.CONTRACT_FAILURE,
                    code="JAVA_INITIAL_REPORT_PROJECT_MISMATCH",
                )
            current = await self._java_client.find_latest_test_run(  # type: ignore[union-attr]
                project_id=project_id,
                case_id=reference.case_id,
                token=self._token_provider(),  # type: ignore[misc]
                trace_id=trace_id,
            )
            if current is None:
                raise JavaApiOpsError(
                    f"Java initial TestReport setup is missing: {reference.case_id}"
                )
            report = await self._java_client.get_test_report(  # type: ignore[union-attr]
                project_id=project_id,
                run_id=current.run_id,
                token=self._token_provider(),  # type: ignore[misc]
                trace_id=trace_id,
            )
            return report, True

        if is_report_runtime_recipe_task(task) or is_stage21_runner_runtime_recipe_task(task):
            if not self.java_enabled:
                raise BenchmarkTaskFailure(
                    "Java Runner is required for the report runtime recipe",
                    category=BenchmarkFailureCategory.INFRASTRUCTURE_FAILURE,
                    code="JAVA_REPORT_RUNTIME_RECIPE_UNAVAILABLE",
                )
            try:
                if is_report_runtime_recipe_task(task):
                    recipe = resolve_report_runtime_recipe(task)
                else:
                    recipe = resolve_stage21_runner_runtime_recipe(task)
            except (
                ReportRuntimeRecipeResolutionError,
                Stage21RunnerRuntimeRecipeResolutionError,
            ) as exc:
                raise BenchmarkTaskFailure(
                    str(exc),
                    category=BenchmarkFailureCategory.CONTRACT_FAILURE,
                    code=exc.code,
                ) from exc
            workflow = Stage20ExecutionWorkflow(
                self._java_client,  # type: ignore[arg-type]
                TestCaseGenerator(self._llm),
                token_provider=self._token_provider,  # type: ignore[arg-type]
                trace_recorder=recorder,
                readback_policy=RunnerReadbackPolicy(
                    overall_deadline_seconds=recipe.readback_deadline_seconds,
                ),
            )
            execution = await workflow.execute_prepared_testcase(
                project_id=project_id,
                testcase=recipe.testcase,
                trace_id=trace_id,
                agent_run_id=agent_run_id,
            )
            return execution.report, True
        if self.java_enabled:
            for entry in task.initial_state.entries:
                ref = getattr(entry, "ref", "")
                if entry.key not in {"testReport", "authorityFixture"}:
                    continue
                match = _RUN_REF_RE.search(ref)
                if match is None:
                    continue
                report = await self._java_client.get_test_report(  # type: ignore[union-attr]
                    project_id=project_id,
                    run_id=int(match.group("run")),
                    token=self._token_provider(),  # type: ignore[misc]
                    trace_id=trace_id,
                )
                return report, True
        if any(
            entry.kind == "JAVA_RESOURCE"
            and entry.key == "testReport"
            and not str(getattr(entry, "ref", "")).startswith("java://rag/")
            for entry in task.initial_state.entries
        ):
            raise BenchmarkTaskFailure(
                "Java TestReport resource could not be resolved through the public boundary",
                category=BenchmarkFailureCategory.CONTRACT_FAILURE,
                code="JAVA_REPORT_REFERENCE_UNRESOLVED",
            )
        return self._fixture_report(task, project_id), False

    def _fixture_report(self, task: BenchmarkTask, project_id: int) -> TestReport:
        raw = json.loads(_DEFAULT_REPORT_FIXTURE.read_text(encoding="utf-8"))
        task_text = task.instruction.lower()
        if "timeout" in task_text:
            status, failure_type, response_status = "TIMEOUT", "TIMEOUT", None
        elif "dns" in task_text:
            status, failure_type, response_status = "EXECUTION_FAILED", "DNS_ERROR", None
        elif "transport" in task_text or "connect" in task_text:
            status, failure_type, response_status = "EXECUTION_FAILED", "CONNECT_ERROR", None
        elif "http 500" in task_text or "http500" in task_text:
            status, failure_type, response_status = (
                "ASSERTION_FAILED",
                "HTTP_STATUS_ERROR",
                500,
            )
        else:
            status, failure_type, response_status = (
                "ASSERTION_FAILED",
                "ASSERTION_MISMATCH",
                500,
            )
        run_id = 700 + int(hashlib.sha256(task.benchmark_task_id.encode()).hexdigest()[:6], 16)
        raw.update(
            {
                "projectId": project_id,
                "taskId": 300,
                "runId": run_id,
                "reportId": f"fixture:report:{task.benchmark_task_id}",
                "status": status,
            }
        )
        raw["summary"] = dict(raw["summary"])
        raw["summary"]["failureType"] = failure_type
        raw["cases"] = [dict(raw["cases"][0])]
        raw["cases"][0]["status"] = status
        raw["cases"][0]["failureType"] = failure_type
        raw["cases"][0]["steps"] = [dict(raw["cases"][0]["steps"][0])]
        raw["cases"][0]["steps"][0]["status"] = status
        raw["cases"][0]["steps"][0]["failureType"] = failure_type
        raw["cases"][0]["steps"][0]["responseStatusCode"] = response_status
        return TestReport.model_validate(raw)

    async def _metadata_for_task_async(
        self,
        task: BenchmarkTask,
        project_id: int,
        trace_id: str,
    ) -> OpenApiMetadataDetail:
        """Resolve Java metadata or the declared local generation input."""

        for entry in task.initial_state.entries:
            ref = getattr(entry, "ref", "")
            if entry.kind != "JAVA_RESOURCE" or not str(ref).startswith("java://metadata/"):
                continue
            if not self.java_enabled:
                raise BenchmarkTaskFailure(
                    "Java metadata is required but the Java boundary is unavailable",
                    category=BenchmarkFailureCategory.INFRASTRUCTURE_FAILURE,
                    code="JAVA_METADATA_UNAVAILABLE",
                )
            return await self._java_client.get_api_metadata(  # type: ignore[union-attr]
                project_id=project_id,
                api_id=self._api_id(task),
                token=self._token_provider(),  # type: ignore[misc]
                trace_id=trace_id,
            )
        return self._metadata_for_task(task, project_id)

    def _metadata_for_task(self, task: BenchmarkTask, project_id: int) -> OpenApiMetadataDetail:
        try:
            local_input = resolve_generation_metadata_input(task)
        except GenerationInputResolutionError as exc:
            raise BenchmarkTaskFailure(
                str(exc),
                category=BenchmarkFailureCategory.CONTRACT_FAILURE,
                code=exc.code,
            ) from exc
        if local_input is not None:
            return local_input.metadata

        for entry in task.initial_state.entries:
            if entry.key not in {"apiMetadata", "metadataEvidence", "taskFixture"}:
                continue
            ref = getattr(entry, "ref", "")
            payload = self._read_json_ref(ref)
            if payload is None:
                continue
            try:
                return OpenApiMetadataDetail.model_validate(payload)
            except Exception:
                boundary = self._metadata_from_boundary_evidence(payload, project_id)
                if boundary is not None:
                    return boundary
        if any(entry.kind == "JAVA_RESOURCE" for entry in task.initial_state.entries):
            raise BenchmarkTaskFailure(
                "generation metadata could not be resolved from the declared Java resource",
                category=BenchmarkFailureCategory.CONTRACT_FAILURE,
                code="GENERATION_METADATA_REFERENCE_UNRESOLVED",
            )
        fallback = self._repository_root / "examples" / "openapi-metadata-valid.json"
        return OpenApiMetadataDetail.model_validate_json(fallback.read_text(encoding="utf-8"))

    def _metadata_from_boundary_evidence(
        self,
        payload: dict[str, object],
        project_id: int,
    ) -> OpenApiMetadataDetail | None:
        operation = payload.get("operation")
        if not isinstance(operation, dict):
            return None
        parameters = operation.get("parameters")
        if not isinstance(parameters, dict):
            return None
        operation_id = operation.get("operationId")
        method = operation.get("method")
        path = operation.get("path")
        if not all(isinstance(value, str) and value for value in (operation_id, method, path)):
            return None
        parameter_values = []
        for name, constraints in parameters.items():
            if not isinstance(name, str) or not isinstance(constraints, dict):
                continue
            parameter_values.append(
                {
                    "name": name,
                    "location": "query",
                    "required": False,
                    "description": "Java OpenAPI metadata constraint",
                    "schema": {"type": "integer", **constraints},
                    "example": 1,
                }
            )
        return OpenApiMetadataDetail.model_validate(
            {
                "apiId": f"api-{operation_id}",
                "apiDocId": f"doc-{project_id}-stage21",
                "operationId": operation_id,
                "method": method,
                "path": path,
                "summary": "Metadata-backed benchmark operation",
                "description": "Derived only from the checked-in Java metadata evidence.",
                "tags": ["benchmark"],
                "servers": [{"url": "http://localhost"}],
                "security": [],
                "deprecated": False,
                "parameters": parameter_values,
                "requestSchemas": [],
                "responseSchemas": [
                    {
                        "statusCode": "200",
                        "description": "documented response",
                        "mediaType": "application/json",
                        "schema": {"type": "object"},
                    }
                ],
                "examples": [],
            }
        )

    def _read_json_ref(self, ref: str) -> dict[str, object] | None:
        if not ref or ref.startswith("java://"):
            return None
        path = (self._repository_root / ref).resolve()
        try:
            path.relative_to(self._repository_root)
        except ValueError:
            return None
        if not path.is_file():
            return None
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError):
            return None
        return value if isinstance(value, dict) else None

    @staticmethod
    def _project_id(task: BenchmarkTask) -> int | None:
        candidates: list[int] = []
        for entry in task.initial_state.entries:
            if entry.kind != "LITERAL" or entry.key not in {"projectId", "sourceProjectId"}:
                continue
            value = getattr(entry, "value", None)
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                return None
            candidates.append(value)
        if not candidates or len(set(candidates)) != 1:
            return None
        return candidates[0]

    @staticmethod
    def _api_id(task: BenchmarkTask) -> str:
        for entry in task.initial_state.entries:
            value = getattr(entry, "value", None)
            if entry.key == "apiId" and isinstance(value, str) and value.strip():
                return value
            ref = getattr(entry, "ref", "")
            if entry.key in {"apiMetadata", "authorityFixture"} and "/" in ref:
                candidate = ref.rsplit("/", 1)[-1].strip()
                if candidate:
                    return candidate
        return "api-1"

    @staticmethod
    def _strategy(task: BenchmarkTask) -> TestStrategy:
        """Resolve the strategy only from typed initial-state setup."""

        candidates: list[object] = []
        for entry in task.initial_state.entries:
            if entry.kind == "LITERAL" and entry.key in {"strategy", "generationStrategy"}:
                candidates.append(getattr(entry, "value", None))
        for candidate in candidates:
            if candidate is None:
                continue
            if not isinstance(candidate, str):
                raise BenchmarkTaskFailure(
                    "structured generation strategy must be a string",
                    category=BenchmarkFailureCategory.CONTRACT_FAILURE,
                    code="TASK_STRATEGY_INVALID",
                )
            try:
                return TestStrategy(candidate)
            except ValueError as exc:
                raise BenchmarkTaskFailure(
                    f"unknown structured generation strategy: {candidate}",
                    category=BenchmarkFailureCategory.CONTRACT_FAILURE,
                    code="TASK_STRATEGY_INVALID",
                ) from exc
        raise BenchmarkTaskFailure(
            "generation task has no structured strategy",
            category=BenchmarkFailureCategory.CONTRACT_FAILURE,
            code="TASK_STRATEGY_UNSPECIFIED",
        )

    @classmethod
    def _execution_plan(cls, task: BenchmarkTask) -> _ExecutionPlan:
        """Build routing only from typed task fields, never instruction prose."""

        selected = set(task.evaluation_spec.selected_metrics)
        if task.task_type is TaskType.TESTCASE_GENERATION:
            generate, diagnose = True, False
        elif task.task_type is TaskType.FAILURE_DIAGNOSIS:
            generate, diagnose = False, True
        elif task.task_type is TaskType.TOOL_SAFETY:
            generate, diagnose = False, True
        elif task.task_type is TaskType.RAG_EVIDENCE_RETRIEVAL:
            generate, diagnose = False, True
        else:
            generate = bool(selected & _GENERATION_METRICS)
            diagnose = bool(selected & _DIAGNOSIS_METRICS)
            if not generate and not diagnose:
                raise BenchmarkTaskFailure(
                    "E2E task has no structured generation or diagnosis execution phase",
                    category=BenchmarkFailureCategory.CONTRACT_FAILURE,
                    code="E2E_EXECUTION_PLAN_EMPTY",
                )

        requirements = cls._java_requirements(task, generate=generate)
        fixture_report_allowed = (
            task.task_type is TaskType.FAILURE_DIAGNOSIS
            and not requirements.required
            and any(
                entry.kind == "PYTHON_FIXTURE" and entry.key in {"diagnosisContext", "taskFixture"}
                for entry in task.initial_state.entries
            )
        )
        return _ExecutionPlan(
            generate=generate,
            diagnose=diagnose,
            java=requirements,
            fixture_report_allowed=fixture_report_allowed,
        )

    @staticmethod
    def _generation_facts(
        candidate: object,
        validation: object | None,
        strategy: TestStrategy,
        *,
        generation_status: object | None = None,
        java_runner_status: str | None = None,
        metadata: OpenApiMetadataDetail | None = None,
        generation_context: GenerationContext | None = None,
        metadata_authority: str | None = None,
        runner_authority: bool | None = None,
        schema_authority: bool | None = None,
        contract_authority: bool | None = None,
        task_focus: str | None = None,
    ) -> EvaluationFacts:
        """Map actual Stage 16/20 authority into one Stage 19 view."""

        return project_generation_facts(
            candidate,
            validation,
            strategy,
            generation_status=generation_status,
            metadata=metadata,
            generation_context=generation_context,
            metadata_authority=metadata_authority,
            java_runner_status=java_runner_status,
            runner_authority=runner_authority,
            schema_authority=schema_authority,
            contract_authority=contract_authority,
            task_focus=task_focus,
        )

    @staticmethod
    def _merge_facts(first: EvaluationFacts, second: EvaluationFacts) -> EvaluationFacts:
        """Compose phase facts while preserving one Stage 19 actual view."""
        return merge_evaluation_facts(first, second)

    @staticmethod
    def _task_focus(task: BenchmarkTask) -> str | None:
        for entry in task.initial_state.entries:
            value = getattr(entry, "value", None)
            if entry.key == "taskFocus" and isinstance(value, str) and value.strip():
                return value
        instruction = task.instruction.strip()
        return instruction or None

    @staticmethod
    def _has_java_metadata(task: BenchmarkTask) -> bool:
        return RealModelStage20WorkflowAdapter._java_requirements(task).metadata

    @classmethod
    def _java_requirements(
        cls,
        task: BenchmarkTask,
        *,
        generate: bool | None = None,
    ) -> _JavaRequirements:
        """Resolve Java prerequisites from runtime resources and planning only."""

        java_entries = tuple(
            entry for entry in task.initial_state.entries if entry.kind == "JAVA_RESOURCE"
        )
        refs = tuple(str(getattr(entry, "ref", "")) for entry in java_entries)
        metadata = any(ref.startswith("java://metadata/") for ref in refs)
        initial_report = is_stage21_initial_report_task(task)
        runner = any(
            is_report_runtime_recipe_task(task)
            or entry.key == "runnerFixture"
            or ref.startswith("java://runner-testcase-dsl/")
            or (entry.key == "testReport" and _RUN_REF_RE.search(ref) is not None)
            for entry, ref in zip(java_entries, refs, strict=True)
        )
        if is_local_generation_reference(task):
            runner = False
        e2e_generates = (
            generate
            if generate is not None
            else bool(set(task.evaluation_spec.selected_metrics) & _GENERATION_METRICS)
        )
        if task.task_type is TaskType.E2E_APIOPS and e2e_generates and java_entries:
            runner = True
        prerequisite = load_stage21_prerequisites().get(task.benchmark_task_id)
        runtime_requirement: ToolRequirement | None = None
        selected_tool: str | None = None
        if prerequisite is not None:
            operations = set(prerequisite.required_operations)
            if "RUNNER_SUBMIT" in operations:
                runner = True
            if prerequisite.terminal_safety_decision in {
                "FORBIDDEN_INTENT_DENIED",
                "PROMPT_INJECTION_DENIED",
            }:
                runtime_requirement = ToolRequirement.DENY
                selected_tool = prerequisite.selected_tool
            elif "TOOL_CALL" in operations:
                runtime_requirement = ToolRequirement.REQUIRED
                selected_tool = (
                    "rag.search"
                    if "RAG_SEARCH" in operations
                    else task.allowed_tools[0] if len(task.allowed_tools) == 1 else None
                )
            elif "NO_JAVA_ACCESS" in operations or "NO_TOOL_CALL" in operations:
                runtime_requirement = ToolRequirement.NOT_REQUIRED
        planning = decide_tool_requirement(
            task.task_type,
            evidence_sufficiency=EvidenceSufficiency.UNRESOLVED,
            allowed_tools=task.allowed_tools,
            instruction=task.instruction,
            context=(cls._task_focus(task) or "",),
            project_id=cls._project_id(task),
            query_source=task.instruction,
            # This is only the static Java-required probe.  The executable
            # decision is rebuilt in _run_diagnosis with the real adapter.
            capability_available=True,
            runtime_requirement=runtime_requirement,
            selected_tool=selected_tool,
        )
        tool_gateway = planning.requirement is ToolRequirement.REQUIRED
        rag = tool_gateway and planning.selected_tool == "rag.search"
        return _JavaRequirements(
            metadata=metadata,
            runner=runner,
            initial_report=initial_report,
            tool_gateway=tool_gateway,
            rag=rag,
        )

    @staticmethod
    def _observed_safety(records: tuple[TraceRecord, ...]) -> SafetyOutcome | None:
        return project_safety_outcome(records)

    @staticmethod
    def _java_references(execution: object) -> tuple[str, ...]:
        report = getattr(execution, "report")
        submission = getattr(execution, "submission")
        return (
            f"java:batch:{submission.batch_id}",
            f"java:task:{submission.task_ids[0]}",
            f"java:run:{report.run_id}",
            f"java:report:{report.report_id}",
        )

    @staticmethod
    def _outcome(
        *,
        trace_id: str,
        agent_run_id: str,
        recorder: TraceRecorder,
        facts: EvaluationFacts | None = None,
        run_id: int | None = None,
        report_id: str | None = None,
        authority_references: tuple[str, ...] = (),
        mapping_status: str | None = None,
        mapping_error_code: str | None = None,
        execution_mode: BenchmarkExecutionMode = BenchmarkExecutionMode.REAL_MODEL,
        java_execution_status: JavaExecutionStatus = JavaExecutionStatus.NOT_APPLICABLE,
    ) -> BenchmarkExecutionOutcome:
        records = recorder.typed_records
        model_call_ids: list[str] = []
        tool_call_ids: list[str] = []
        rag_query_ids: list[str] = []
        observed_run_id = run_id
        observed_report_id = report_id
        for record in records:
            if isinstance(record, ModelCall) and record.model_call_id not in model_call_ids:
                model_call_ids.append(record.model_call_id)
            if isinstance(record, ToolResultRecord) and record.java_tool_call_id:
                if record.java_tool_call_id not in tool_call_ids:
                    tool_call_ids.append(record.java_tool_call_id)
            if isinstance(record, RetrievalFact):
                reference = record.reference
                if reference.rag_query_id and reference.rag_query_id not in rag_query_ids:
                    rag_query_ids.append(reference.rag_query_id)
                # The diagnosis workflow also records the controlled initial
                # TestReport as a retrieval fact.  Its ``fixture:`` identity
                # is input state, not a Java Runner authority reference.
                if (
                    reference.report_id
                    and not reference.report_id.startswith("fixture:")
                    and observed_report_id is None
                ):
                    observed_report_id = reference.report_id
                    if observed_run_id is None and isinstance(reference.run_id, int):
                        observed_run_id = reference.run_id
            if isinstance(record, JavaRunReferenceFact):
                observed_run_id = record.java_run_id
        tool_result_observations = project_tool_result_observations(
            records,
            mapping_status=mapping_status,
            mapping_error_code=mapping_error_code,
        )
        return BenchmarkExecutionOutcome(
            trace_id=trace_id,
            agent_run_id=agent_run_id,
            facts=facts or EvaluationFacts(),
            trace_records=records,
            run_id=observed_run_id,
            report_id=observed_report_id,
            tool_call_ids=tuple(tool_call_ids),
            rag_query_ids=tuple(rag_query_ids),
            model_call_ids=tuple(model_call_ids),
            authority_references=authority_references,
            tool_result_observations=tool_result_observations,
            execution_mode=execution_mode,
            java_execution_status=java_execution_status,
        )


__all__ = ["RealModelStage20WorkflowAdapter"]
