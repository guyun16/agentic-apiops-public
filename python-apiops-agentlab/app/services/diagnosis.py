"""Real Java TestReport to DeepSeek diagnosis orchestration.

This service intentionally has one external data boundary: ``JavaApiOpsClient``.
The Python process does not own or inspect the Java databases, queues, caches, or
raw log stores.  SQLite owns the DiagnosisRun identity and LangGraph checkpoint
state so a bounded HITL workflow can resume after the Python process restarts.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

import httpx
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.types import Command

from app.agents.diagnosis import DiagnosisInferenceError
from app.clients.deepseek import DeepSeekError
from app.clients.diagnosis_llm import (
    build_diagnosis_llm,
    diagnosis_llm_identity,
    require_diagnosis_llm_credentials,
)
from app.clients.java_apiops import (
    JavaApiOpsAuthenticationError,
    JavaApiOpsAuthorizationError,
    JavaApiOpsClient,
    JavaApiOpsClientError,
    JavaApiOpsError,
    JavaApiOpsMalformedResponseError,
    JavaApiOpsNotFoundError,
    JavaApiOpsResponseValidationError,
    JavaApiOpsServerError,
    JavaApiOpsTimeoutError,
    JavaApiOpsToolGatewayAdapter,
    JavaApiOpsTransportError,
)
from app.clients.qwen import QwenError
from app.core.errors import ApplicationError
from app.core.settings import AppSettings, get_settings
from app.memory import (
    HistoricalFailureMemoryCandidate,
    MemoryRetriever,
    MemoryWritePolicy,
    VerificationStatus,
)
from app.rag.context import ContextPack
from app.schemas.diagnosis_api import (
    DiagnosisContextSummary,
    DiagnosisExecutionResponse,
    DiagnosisExecutionStep,
    DiagnosisFailure,
    DiagnosisMemoryWriteResponse,
)
from app.schemas.diagnosis_report import DiagnosisReport
from app.schemas.runner import TestReport
from app.services.diagnosis_repository import (
    SQLiteDiagnosisRunRepository,
    StoredDiagnosisRun,
)
from app.services.runtime_evaluation import runtime_evaluation_store
from app.tools import ToolCatalog, ToolIntent, ToolRouter
from app.tracing import TraceEvent, TraceRecorder, create_trace_recorder, new_identity
from app.workflows.approval import ApprovalAction, ApprovalDecision, ApprovalRequest
from app.workflows.diagnosis_memory_query import build_memory_symptoms
from app.workflows.diagnosis_workflow import (
    build_diagnosis_workflow,
    diagnosis_initial_state,
)
from app.workflows.runtime_control import checkpoint_config
from app.workflows.tool_use_state import ToolFailure

_FAILED_RUN_STATUSES = frozenset({"ASSERTION_FAILED", "EXECUTION_FAILED", "TIMEOUT"})
_DIRECT_JAVA_TOOL_FAILURES: dict[str, tuple[int, str]] = {
    "JAVA_AUTHENTICATION_FAILED": (401, "Java rejected the supplied credential."),
    "JAVA_AUTHORIZATION_DENIED": (403, "Java denied access to the requested project resource."),
    "JAVA_RESOURCE_NOT_FOUND": (404, "The requested Java project resource was not found."),
    "JAVA_TIMEOUT": (503, "Java API Ops did not respond within its configured timeout."),
    "JAVA_TRANSPORT_UNAVAILABLE": (503, "Java API Ops is unavailable."),
}


@dataclass(slots=True)
class _DiagnosisRun:
    agent_run_id: str
    workflow_id: str
    trace_id: str
    project_id: int
    run_id: int
    api_id: str | None
    test_report: TestReport
    trace_recorder: TraceRecorder
    model: str
    provider: str = "DeepSeek"
    status: str = "RUNNING"
    diagnosis_report: DiagnosisReport | None = None
    latest_state: dict[str, object] = field(default_factory=dict)
    approval_request: ApprovalRequest | None = None
    tool_intent_id: str | None = None
    tool_call_id: str | None = None
    failure: DiagnosisFailure | None = None


class DiagnosisExecutionService:
    """Own real diagnosis execution records and the existing workflow runtime."""

    def __init__(
        self,
        settings: AppSettings | None = None,
        *,
        memory_retriever: MemoryRetriever | None = None,
        memory_write_policy: MemoryWritePolicy | None = None,
        run_repository: SQLiteDiagnosisRunRepository | None = None,
        checkpoint_db_path: str | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        if memory_retriever is not None and not isinstance(memory_retriever, MemoryRetriever):
            raise TypeError("memory_retriever must be a MemoryRetriever")
        if memory_write_policy is not None and not isinstance(
            memory_write_policy,
            MemoryWritePolicy,
        ):
            raise TypeError("memory_write_policy must be a MemoryWritePolicy")
        self._memory_retriever = memory_retriever
        self._memory_write_policy = memory_write_policy
        if run_repository is not None and not isinstance(
            run_repository,
            SQLiteDiagnosisRunRepository,
        ):
            raise TypeError("run_repository must be a SQLiteDiagnosisRunRepository")
        if checkpoint_db_path is None:
            checkpoint_db_path = (
                run_repository.database_path
                if run_repository is not None
                else self._settings.runtime_db_path
            )
        self._checkpoint_db_path = os.fspath(checkpoint_db_path)
        if not self._checkpoint_db_path:
            raise ValueError("checkpoint_db_path must not be empty")
        self._run_repository = run_repository or SQLiteDiagnosisRunRepository(
            self._checkpoint_db_path
        )
        if self._run_repository.database_path != self._checkpoint_db_path:
            raise ValueError(
                "run_repository and checkpoint_db_path must use the same database path"
            )
        self._trace_recorders: dict[str, TraceRecorder] = {}

    async def start(
        self,
        *,
        project_id: int,
        run_id: int,
        token: str,
        trace_id: str,
        settings: AppSettings | None = None,
    ) -> DiagnosisExecutionResponse:
        """Fetch one failed Java report, then invoke the real Python workflow."""

        effective_settings = settings or self._settings
        report = await self._fetch_report(
            project_id=project_id,
            run_id=run_id,
            token=token,
            trace_id=trace_id,
            settings=effective_settings,
        )
        if report.status not in _FAILED_RUN_STATUSES:
            raise ApplicationError(
                "RUN_NOT_FAILED",
                "Diagnosis requires a failed or timed-out Java run.",
                409,
            )
        require_diagnosis_llm_credentials(effective_settings)
        identity = diagnosis_llm_identity(effective_settings)
        api_id = (
            await self._resolve_api_id(
                project_id=project_id,
                run_id=run_id,
                token=token,
                trace_id=trace_id,
                settings=effective_settings,
            )
            if self._memory_retriever is not None
            else None
        )

        record = _DiagnosisRun(
            agent_run_id=new_identity("agent_run"),
            workflow_id=new_identity("diagnosis_workflow"),
            trace_id=trace_id,
            project_id=project_id,
            run_id=run_id,
            api_id=api_id,
            test_report=report,
            trace_recorder=create_trace_recorder(effective_settings),
            provider=identity.provider,
            model=identity.model,
        )
        self._trace_recorders[record.agent_run_id] = record.trace_recorder
        self._persist_record(record)
        runtime_evaluation_store.begin(
            agent_run_id=record.agent_run_id,
            trace_id=record.trace_id,
            execution_type="DIAGNOSIS",
            provider=record.provider,
            model=record.model,
            project_id=record.project_id,
            run_id=record.run_id,
            report_id=record.test_report.report_id,
            validation_applicable=False,
        )

        try:
            result = await self._invoke(
                record=record,
                token=token,
                settings=effective_settings,
                resume_decision=None,
            )
            self._apply_graph_result(record, result)
            self._persist_record(record)
            self._sync_runtime(record)
        except ApplicationError as exc:
            self._mark_failure(record, exc.code, exc.message)
            raise
        except (DeepSeekError, QwenError, DiagnosisInferenceError) as exc:
            self._mark_failure(record, "DIAGNOSIS_FAILED", "The diagnosis workflow failed.")
            raise ApplicationError(
                "DIAGNOSIS_FAILED",
                "The diagnosis workflow failed.",
                502,
            ) from exc
        except Exception as exc:  # noqa: BLE001 - public boundary must be stable and fail closed
            self._mark_failure(record, "DIAGNOSIS_FAILED", "The diagnosis workflow failed.")
            raise ApplicationError(
                "DIAGNOSIS_FAILED",
                "The diagnosis workflow failed.",
                502,
            ) from exc
        return self._snapshot(record)

    async def resume(
        self,
        *,
        agent_run_id: str,
        token: str,
        decision: ApprovalAction,
        edited_arguments: dict[str, Any] | None,
        trace_id: str,
        settings: AppSettings | None = None,
    ) -> DiagnosisExecutionResponse:
        """Re-authorize the Java report and resume the exact stored HITL thread."""

        effective_settings = settings or self._settings
        record = self._get_record(agent_run_id, settings=effective_settings)
        if record.status != "APPROVAL_REQUIRED" or record.approval_request is None:
            raise ApplicationError(
                "APPROVAL_NOT_PENDING",
                "This diagnosis execution has no pending approval request.",
                409,
            )
        require_diagnosis_llm_credentials(effective_settings)
        identity = diagnosis_llm_identity(effective_settings)
        if (record.provider, record.model) != (identity.provider, identity.model):
            raise ApplicationError(
                "DIAGNOSIS_PROVIDER_MISMATCH",
                "The Diagnosis provider and model cannot change while resuming.",
                409,
            )
        refreshed = await self._fetch_report(
            project_id=record.project_id,
            run_id=record.run_id,
            token=token,
            trace_id=record.trace_id,
            settings=effective_settings,
        )
        if refreshed.report_id != record.test_report.report_id:
            self._mark_failure(
                record,
                "TEST_REPORT_CHANGED",
                "The Java TestReport changed while approval was pending.",
            )
            raise ApplicationError(
                "TEST_REPORT_CHANGED",
                "The Java TestReport changed while approval was pending.",
                409,
        )
        record.test_report = refreshed
        self._persist_record(record)

        approval = ApprovalDecision(
            workflow_id=record.approval_request.workflow_id,
            project_id=record.approval_request.project_id,
            intent_id=record.approval_request.intent_id,
            tool_name=record.approval_request.tool_name,
            arguments_fingerprint=record.approval_request.arguments_fingerprint,
            decision=decision,
            edited_arguments=edited_arguments,
        )
        try:
            result = await self._invoke(
                record=record,
                token=token,
                settings=effective_settings,
                resume_decision=approval,
            )
            self._apply_graph_result(record, result)
            self._persist_record(record)
            self._sync_runtime(record)
        except ApplicationError as exc:
            self._mark_failure(record, exc.code, exc.message)
            raise
        except (DeepSeekError, QwenError, DiagnosisInferenceError) as exc:
            self._mark_failure(record, "DIAGNOSIS_FAILED", "The diagnosis workflow failed.")
            raise ApplicationError(
                "DIAGNOSIS_FAILED",
                "The diagnosis workflow failed.",
                502,
            ) from exc
        except Exception as exc:  # noqa: BLE001 - public boundary must be stable and fail closed
            self._mark_failure(record, "DIAGNOSIS_FAILED", "The diagnosis workflow failed.")
            raise ApplicationError(
                "DIAGNOSIS_FAILED",
                "The diagnosis workflow failed.",
                502,
            ) from exc
        return self._snapshot(record)

    async def get(
        self,
        *,
        agent_run_id: str,
        token: str,
        settings: AppSettings | None = None,
    ) -> DiagnosisExecutionResponse:
        """Read a result only after re-reading its Java-owned TestReport."""

        effective_settings = settings or self._settings
        record = self._get_record(agent_run_id, settings=effective_settings)
        refreshed = await self._fetch_report(
            project_id=record.project_id,
            run_id=record.run_id,
            token=token,
            trace_id=record.trace_id,
            settings=effective_settings,
        )
        if refreshed.report_id != record.test_report.report_id:
            raise ApplicationError(
                "TEST_REPORT_CHANGED",
                "The Java TestReport no longer matches this diagnosis execution.",
                409,
            )
        record.test_report = refreshed
        self._persist_record(record)
        return self._snapshot(record)

    async def remember_verified_diagnosis(
        self,
        *,
        agent_run_id: str,
        hypothesis_index: int,
        token: str,
        settings: AppSettings | None = None,
    ) -> DiagnosisMemoryWriteResponse:
        """Write one selected final hypothesis through explicit human authority."""

        effective_settings = settings or self._settings
        record = self._get_record(agent_run_id, settings=effective_settings)
        if record.status != "COMPLETED":
            raise ApplicationError(
                "DIAGNOSIS_NOT_COMPLETED",
                "Only a completed Diagnosis execution can be verified.",
                409,
            )
        diagnosis_report = record.diagnosis_report
        if diagnosis_report is None:
            raise ApplicationError(
                "DIAGNOSIS_REPORT_MISSING",
                "The completed Diagnosis execution has no final DiagnosisReport.",
                409,
            )
        if self._memory_write_policy is None:
            raise ApplicationError(
                "MEMORY_WRITE_NOT_CONFIGURED",
                "Historical Memory writing is not configured.",
                503,
            )

        refreshed = await self._fetch_report(
            project_id=record.project_id,
            run_id=record.run_id,
            token=token,
            trace_id=record.trace_id,
            settings=effective_settings,
        )
        if refreshed.report_id != record.test_report.report_id:
            raise ApplicationError(
                "TEST_REPORT_CHANGED",
                "The Java TestReport no longer matches this diagnosis execution.",
                409,
            )
        if refreshed.project_id != record.project_id or refreshed.run_id != record.run_id:
            raise ApplicationError(
                "TEST_REPORT_IDENTITY_CHANGED",
                "The Java TestReport identity no longer matches this diagnosis execution.",
                409,
            )
        if (
            diagnosis_report.report_id != record.test_report.report_id
            or diagnosis_report.project_id != record.project_id
            or diagnosis_report.run_id != record.run_id
            or diagnosis_report.agent_run_id != record.agent_run_id
        ):
            raise ApplicationError(
                "DIAGNOSIS_IDENTITY_CHANGED",
                "The final DiagnosisReport identity no longer matches this execution.",
                409,
            )

        api_id = _string_value(record.api_id)
        if api_id is None:
            raise ApplicationError(
                "MEMORY_API_ID_UNAVAILABLE",
                "Historical Memory cannot be written without a trusted apiId.",
                409,
            )
        if isinstance(hypothesis_index, bool) or not isinstance(hypothesis_index, int):
            raise ApplicationError(
                "DIAGNOSIS_HYPOTHESIS_INVALID",
                "hypothesisIndex must select a final root-cause hypothesis.",
                422,
            )
        if hypothesis_index < 0 or hypothesis_index >= len(diagnosis_report.root_cause_hypotheses):
            raise ApplicationError(
                "DIAGNOSIS_HYPOTHESIS_NOT_FOUND",
                "The selected final root-cause hypothesis was not found.",
                422,
            )
        if not diagnosis_report.recommended_checks:
            raise ApplicationError(
                "DIAGNOSIS_RESOLUTION_MISSING",
                "Historical Memory requires at least one recommended check.",
                409,
            )

        hypothesis = diagnosis_report.root_cause_hypotheses[hypothesis_index]
        candidate = HistoricalFailureMemoryCandidate(
            project_id=record.project_id,
            api_id=api_id,
            summary=diagnosis_report.summary,
            symptoms=list(build_memory_symptoms(refreshed)),
            root_cause=hypothesis.statement,
            resolution="; ".join(diagnosis_report.recommended_checks),
            source_run_id=record.run_id,
            verification_status=VerificationStatus.VERIFIED,
        )
        decision = self._memory_write_policy.write(
            candidate,
            project_id=record.project_id,
        )
        return DiagnosisMemoryWriteResponse(
            agentRunId=record.agent_run_id,
            projectId=record.project_id,
            runId=record.run_id,
            outcome=decision.outcome,
            reason=decision.reason,
            memoryId=decision.entry.memory_id if decision.entry is not None else None,
            stored=decision.stored,
        )

    async def _fetch_report(
        self,
        *,
        project_id: int,
        run_id: int,
        token: str,
        trace_id: str,
        settings: AppSettings,
    ) -> TestReport:
        async with httpx.AsyncClient(trust_env=False) as http_client:
            client = JavaApiOpsClient(
                http_client,
                base_url=settings.java_apiops_base_url,
                timeout_seconds=settings.java_apiops_timeout_seconds,
            )
            try:
                return await client.get_test_report(
                    project_id=project_id,
                    run_id=run_id,
                    token=token,
                    trace_id=trace_id,
                )
            except JavaApiOpsError as exc:
                raise self._map_java_error(exc) from exc

    async def _resolve_api_id(
        self,
        *,
        project_id: int,
        run_id: int,
        token: str,
        trace_id: str,
        settings: AppSettings,
    ) -> str | None:
        """Resolve apiId only from one exact Java run-summary match."""

        try:
            async with httpx.AsyncClient(trust_env=False) as http_client:
                client = JavaApiOpsClient(
                    http_client,
                    base_url=settings.java_apiops_base_url,
                    timeout_seconds=settings.java_apiops_timeout_seconds,
                )
                summaries = await client.list_test_runs(
                    project_id=project_id,
                    token=token,
                    trace_id=trace_id,
                )
        except JavaApiOpsError:
            return None

        matches = tuple(summary for summary in summaries if summary.run_id == run_id)
        return matches[0].api_id if len(matches) == 1 else None

    @staticmethod
    def _to_stored_record(record: _DiagnosisRun) -> StoredDiagnosisRun:
        intent = record.latest_state.get("intent")
        approval_arguments = dict(intent.arguments) if isinstance(intent, ToolIntent) else None
        risk = record.latest_state.get("tool_risk")
        risk_value = getattr(risk, "value", risk)
        approval_risk = risk_value if isinstance(risk_value, str) else None
        return StoredDiagnosisRun(
            agent_run_id=record.agent_run_id,
            workflow_id=record.workflow_id,
            trace_id=record.trace_id,
            project_id=record.project_id,
            run_id=record.run_id,
            api_id=record.api_id,
            test_report=record.test_report,
            provider=record.provider,
            model=record.model,
            status=record.status,
            diagnosis_report=record.diagnosis_report,
            approval_request=record.approval_request,
            approval_arguments=approval_arguments,
            approval_risk=approval_risk,
            tool_intent_id=record.tool_intent_id,
            tool_call_id=record.tool_call_id,
            failure=record.failure,
        )

    @staticmethod
    def _from_stored_record(
        stored: StoredDiagnosisRun,
        *,
        trace_recorder: TraceRecorder,
    ) -> _DiagnosisRun:
        latest_state: dict[str, object] = {}
        if stored.approval_request is not None and stored.approval_arguments is not None:
            latest_state["intent"] = ToolIntent(
                tool_name=stored.approval_request.tool_name,
                arguments=stored.approval_arguments,
            )
        if stored.approval_risk is not None:
            latest_state["tool_risk"] = stored.approval_risk
        return _DiagnosisRun(
            agent_run_id=stored.agent_run_id,
            workflow_id=stored.workflow_id,
            trace_id=stored.trace_id,
            project_id=stored.project_id,
            run_id=stored.run_id,
            api_id=stored.api_id,
            test_report=stored.test_report,
            trace_recorder=trace_recorder,
            provider=stored.provider,
            model=stored.model,
            status=stored.status,
            diagnosis_report=stored.diagnosis_report,
            latest_state=latest_state,
            approval_request=stored.approval_request,
            tool_intent_id=stored.tool_intent_id,
            tool_call_id=stored.tool_call_id,
            failure=stored.failure,
        )

    def _persist_record(self, record: _DiagnosisRun) -> None:
        self._run_repository.save(self._to_stored_record(record))

    async def _invoke(
        self,
        *,
        record: _DiagnosisRun,
        token: str,
        settings: AppSettings,
        resume_decision: ApprovalDecision | None,
    ) -> Mapping[str, object]:
        async with AsyncSqliteSaver.from_conn_string(self._checkpoint_db_path) as checkpointer:
            async with httpx.AsyncClient(trust_env=False) as http_client:
                java_client = JavaApiOpsClient(
                    http_client,
                    base_url=settings.java_apiops_base_url,
                    timeout_seconds=settings.java_apiops_timeout_seconds,
                )
                gateway = JavaApiOpsToolGatewayAdapter(
                    java_client,
                    project_id=record.project_id,
                    token_provider=lambda: token,
                )
                catalog = ToolCatalog()
                router = ToolRouter(
                    catalog,
                    {
                        "rag.search": gateway,
                        "redis.read": gateway,
                    },
                )
                llm = build_diagnosis_llm(http_client, settings)
                graph = build_diagnosis_workflow(
                    llm,
                    router,
                    project_id=record.project_id,
                    catalog=catalog,
                    checkpointer=checkpointer,
                    trace_recorder=record.trace_recorder,
                    api_id=record.api_id,
                    memory_retriever=self._memory_retriever,
                )
                if resume_decision is None:
                    initial_state = diagnosis_initial_state(
                        record.test_report,
                        trace_id=record.trace_id,
                        agent_run_id=record.agent_run_id,
                        workflow_id=record.workflow_id,
                    )
                    result = await graph.ainvoke(
                        initial_state,
                        config=checkpoint_config(record.workflow_id),
                    )
                else:
                    result = await graph.ainvoke(
                        Command(resume=resume_decision.model_dump(mode="json")),
                        config=checkpoint_config(record.workflow_id),
                    )
        if not isinstance(result, Mapping):
            raise ApplicationError(
                "DIAGNOSIS_WORKFLOW_INVALID",
                "The diagnosis workflow returned an invalid state.",
                502,
            )
        return result

    def _apply_graph_result(self, record: _DiagnosisRun, result: Mapping[str, object]) -> None:
        state = dict(result)
        record.latest_state = state
        record.tool_intent_id = _string_value(state.get("intent_id"))
        tool_result = state.get("tool_result")
        record.tool_call_id = _string_value(getattr(tool_result, "tool_call_id", None))
        failure = state.get("failure")
        if isinstance(failure, ToolFailure):
            direct_failure = _DIRECT_JAVA_TOOL_FAILURES.get(failure.code.value)
            if direct_failure is not None:
                status_code, message = direct_failure
                raise ApplicationError(failure.code.value, message, status_code)

        interrupt_values = state.get("__interrupt__")
        if isinstance(interrupt_values, (list, tuple)) and interrupt_values:
            request_value = getattr(interrupt_values[0], "value", interrupt_values[0])
            try:
                request = ApprovalRequest.model_validate(request_value)
            except Exception as exc:  # noqa: BLE001 - invalid internal state is a boundary failure
                raise ApplicationError(
                    "DIAGNOSIS_WORKFLOW_INVALID",
                    "The diagnosis workflow returned an invalid approval request.",
                    502,
                ) from exc
            record.approval_request = request
            record.tool_intent_id = request.intent_id
            record.status = "APPROVAL_REQUIRED"
            record.failure = None
            return

        candidate = state.get("diagnosis_report")
        if not isinstance(candidate, DiagnosisReport):
            raise ApplicationError(
                "DIAGNOSIS_REPORT_MISSING",
                "The diagnosis workflow did not return a DiagnosisReport.",
                502,
            )
        record.diagnosis_report = candidate
        record.approval_request = None
        record.status = (
            "REJECTED"
            if isinstance(failure, ToolFailure) and failure.code.value == "HUMAN_REJECTED"
            else "COMPLETED"
        )
        record.failure = None

    def _snapshot(self, record: _DiagnosisRun) -> DiagnosisExecutionResponse:
        self._sync_runtime(record)
        return DiagnosisExecutionResponse.model_validate(
            {
                "status": record.status,
                "runtime": "PYTHON_AGENTLAB",
                "implementation": "REAL",
                "workflow": "Diagnosis Workflow",
                "provider": record.provider,
                "model": record.model,
                "projectId": record.project_id,
                "runId": record.run_id,
                "taskId": record.test_report.task_id,
                "reportId": record.test_report.report_id,
                "agentRunId": record.agent_run_id,
                "traceId": record.trace_id,
                "workflowId": record.workflow_id,
                "testReport": record.test_report.model_dump(mode="json"),
                "report": (
                    record.diagnosis_report.model_dump(mode="json")
                    if record.diagnosis_report is not None
                    else None
                ),
                "toolIntentId": record.tool_intent_id,
                "toolCallId": record.tool_call_id,
                "approvalRequest": self._approval_payload(record),
                "steps": self._steps(record),
                "context": self._context_summary(record),
                "failure": (
                    record.failure.model_dump(mode="json") if record.failure is not None else None
                ),
            }
        )

    def _approval_payload(self, record: _DiagnosisRun) -> dict[str, object] | None:
        request = record.approval_request
        if request is None:
            return None
        state_intent = record.latest_state.get("intent")
        arguments: dict[str, object] = {}
        if isinstance(state_intent, ToolIntent):
            arguments = dict(state_intent.arguments)
        risk = record.latest_state.get("tool_risk")
        risk_value = getattr(risk, "value", risk)
        return {
            "toolName": request.tool_name,
            "risk": str(risk_value or "REQUIRE_APPROVAL"),
            "reason": "Guardrails require approval before the Java Tool Gateway call.",
            "arguments": arguments,
            "scope": {
                "workflowId": request.workflow_id,
                "projectId": request.project_id,
                "toolIntentId": request.intent_id,
                "argumentsFingerprint": request.arguments_fingerprint,
            },
        }

    def _steps(self, record: _DiagnosisRun) -> tuple[DiagnosisExecutionStep, ...]:
        records = record.trace_recorder.typed_records
        steps: list[DiagnosisExecutionStep] = []
        if any(
            item.record_type == "retrieval"
            and getattr(item, "retrieval_kind", None) == "JAVA_TEST_REPORT"
            for item in records
        ):
            steps.append(
                DiagnosisExecutionStep(
                    id="java-test-report",
                    label="Java TestReport",
                    detail="Read through JavaApiOpsClient.",
                    state="COMPLETED",
                )
            )
        if isinstance(record.latest_state.get("context_pack"), ContextPack):
            steps.append(
                DiagnosisExecutionStep(
                    id="context-pack",
                    label="ContextPack / RAG",
                    detail="Project-scoped ContextPack was built by the existing workflow.",
                    state="COMPLETED",
                )
            )
        if any(item.record_type == "model_call" for item in records):
            steps.append(
                DiagnosisExecutionStep(
                    id="diagnosis-llm",
                    label=f"{record.provider} diagnosis",
                    detail="A real provider call was recorded by TraceRecorder.",
                    state=(
                        "COMPLETED"
                        if record.diagnosis_report is not None or record.approval_request
                        else "ACTIVE"
                    ),
                )
            )
        if record.approval_request is not None:
            steps.append(
                DiagnosisExecutionStep(
                    id="hitl-approval",
                    label="HITL approval",
                    detail="The existing Guardrails policy paused this exact ToolIntent.",
                    state="ACTIVE" if record.status == "APPROVAL_REQUIRED" else "COMPLETED",
                )
            )
        if record.tool_intent_id is not None and any(
            item.record_type == "tool_result" for item in records
        ):
            steps.append(
                DiagnosisExecutionStep(
                    id="java-tool-gateway",
                    label="Java Tool Gateway",
                    detail="The Java-owned ToolResult was observed by TraceRecorder.",
                    state="COMPLETED" if record.tool_call_id is not None else "ACTIVE",
                )
            )
        if record.diagnosis_report is not None:
            steps.append(
                DiagnosisExecutionStep(
                    id="diagnosis-report",
                    label="DiagnosisReport",
                    detail="Real DiagnosisReport returned by the existing workflow.",
                    state="REJECTED" if record.status == "REJECTED" else "COMPLETED",
                )
            )
        return tuple(steps)

    def _context_summary(self, record: _DiagnosisRun) -> DiagnosisContextSummary:
        pack = record.latest_state.get("context_pack")
        evidence_items = 0
        context_characters = 0
        if isinstance(pack, ContextPack):
            evidence_items = len(pack.items)
            context_characters = sum(len(item.content) for item in pack.items)
        model_calls = sum(
            1
            for item in record.trace_recorder.typed_records
            if item.record_type == "model_call" and item.event is TraceEvent.START
        )
        tool_calls = sum(
            1 for item in record.trace_recorder.typed_records if item.record_type == "tool_result"
        )
        return DiagnosisContextSummary(
            evidenceItems=evidence_items,
            contextCharacters=context_characters,
            modelCalls=model_calls,
            toolCalls=tool_calls,
        )

    def _get_record(
        self,
        agent_run_id: str,
        *,
        settings: AppSettings | None = None,
    ) -> _DiagnosisRun:
        if not isinstance(agent_run_id, str) or not agent_run_id.strip():
            raise ApplicationError("DIAGNOSIS_NOT_FOUND", "Diagnosis execution was not found.", 404)
        stored = self._run_repository.get(agent_run_id)
        if stored is None:
            raise ApplicationError("DIAGNOSIS_NOT_FOUND", "Diagnosis execution was not found.", 404)
        recorder = self._trace_recorders.get(agent_run_id)
        if recorder is None:
            recorder = create_trace_recorder(settings or self._settings)
            self._trace_recorders[agent_run_id] = recorder
        return self._from_stored_record(stored, trace_recorder=recorder)

    @staticmethod
    def _map_java_error(exc: JavaApiOpsError) -> ApplicationError:
        if isinstance(exc, JavaApiOpsAuthenticationError):
            return ApplicationError(
                "JAVA_AUTHENTICATION_FAILED",
                "Java rejected the supplied credential.",
                401,
            )
        if isinstance(exc, JavaApiOpsAuthorizationError):
            return ApplicationError(
                "JAVA_AUTHORIZATION_DENIED",
                "Java denied access to the requested project resource.",
                403,
            )
        if isinstance(exc, JavaApiOpsNotFoundError):
            return ApplicationError(
                "JAVA_RESOURCE_NOT_FOUND",
                "The requested Java project resource was not found.",
                404,
            )
        if isinstance(
            exc,
            (JavaApiOpsTimeoutError, JavaApiOpsTransportError, JavaApiOpsServerError),
        ):
            return ApplicationError(
                "JAVA_UNAVAILABLE",
                "Java API Ops is unavailable.",
                503,
            )
        if isinstance(exc, (JavaApiOpsMalformedResponseError, JavaApiOpsResponseValidationError)):
            return ApplicationError(
                "JAVA_INVALID_RESPONSE",
                "Java API Ops returned an invalid response.",
                502,
            )
        if isinstance(exc, JavaApiOpsClientError):
            return ApplicationError(
                "JAVA_REQUEST_FAILED",
                "Java API Ops rejected the request.",
                502,
            )
        return ApplicationError("JAVA_REQUEST_FAILED", "Java API Ops request failed.", 502)

    def _sync_runtime(self, record: _DiagnosisRun) -> None:
        failure_code = record.failure.code if record.failure is not None else None
        failure_message = record.failure.message if record.failure is not None else None
        runtime_evaluation_store.update(
            agent_run_id=record.agent_run_id,
            status=record.status,  # type: ignore[arg-type]
            trace_records=record.trace_recorder.typed_records,
            failure_code=failure_code,
            failure_message=failure_message,
        )

    def _mark_failure(self, record: _DiagnosisRun, code: str, message: str) -> None:
        record.status = "FAILED"
        record.failure = DiagnosisFailure(code=code, message=message)
        self._persist_record(record)
        self._sync_runtime(record)


def _string_value(value: object) -> str | None:
    return value if isinstance(value, str) and value.strip() else None


__all__ = ["DiagnosisExecutionService"]
