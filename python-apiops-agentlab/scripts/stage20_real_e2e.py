"""Real Java Stage 20.2 acceptance using the deterministic fake LLM."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
from langgraph.checkpoint.memory import InMemorySaver

from app.agents.testcase_generator import TestCaseGenerator
from app.clients import (
    JavaApiOpsAuthenticationError,
    JavaApiOpsAuthorizationError,
    JavaApiOpsClient,
    JavaApiOpsClientError,
    JavaApiOpsMalformedResponseError,
    JavaApiOpsNotFoundError,
    JavaApiOpsResponseValidationError,
    JavaApiOpsToolGatewayAdapter,
    JavaApiOpsTransportError,
)
from app.rag.models import EvidenceRetrieval
from app.schemas.runner import TestReport
from app.schemas.testcase_dsl import TestCaseDSL
from app.schemas.tool_result import ToolResult
from app.tools import ToolCatalog, ToolIntent, ToolRouter, map_tool_intent
from app.tracing import (
    IdentityAuthority,
    InMemoryTraceSink,
    JavaRunReferenceFact,
    TraceEvent,
    TraceRecorder,
    TraceStatus,
    new_identity,
    observe,
    trace_parent,
)
from app.workflows.diagnosis_workflow import (
    build_diagnosis_workflow,
    diagnosis_initial_state,
)
from app.workflows.framework_spike import DeterministicFakeLLM
from app.workflows.generation_context import TestStrategy, build_generation_context
from app.workflows.runtime_control import checkpoint_config
from app.workflows.stage20_execution import (
    GeneratedTestCaseNotValidatedError,
    RunnerReadbackPolicy,
    Stage20ExecutionWorkflow,
)
from app.workflows.state import WorkflowPhase
from app.workflows.testcase_generation_graph import build_testcase_generation_graph


@dataclass(frozen=True)
class DiagnosisE2EConfig:
    """Cross-process inputs supplied by the owning Java test harness."""

    base_url: str
    token: str
    project_id: int
    run_id: int
    trace_id: str
    failure_mode: str | None = None
    expected_tool_status: str | None = None
    tool_query: str = "order endpoint failure evidence"
    tool_top_k: int = 2

    @classmethod
    def from_environment(cls) -> DiagnosisE2EConfig:
        values = {
            name: os.environ.get(name, "").strip()
            for name in (
                "JAVA_APIOPS_BASE_URL",
                "JAVA_APIOPS_TOKEN",
                "STAGE20_PROJECT_ID",
                "STAGE20_RUN_ID",
                "STAGE20_TRACE_ID",
                "STAGE20_FAILURE_MODE",
                "STAGE20_EXPECT_TOOL_STATUS",
                "STAGE20_TOOL_QUERY",
                "STAGE20_TOOL_TOP_K",
            )
        }
        required_names = (
            "JAVA_APIOPS_BASE_URL",
            "JAVA_APIOPS_TOKEN",
            "STAGE20_PROJECT_ID",
            "STAGE20_RUN_ID",
            "STAGE20_TRACE_ID",
        )
        missing = [name for name in required_names if not values[name]]
        if missing:
            raise RuntimeError(f"required environment is missing: {', '.join(missing)}")
        try:
            project_id = int(values["STAGE20_PROJECT_ID"])
            run_id = int(values["STAGE20_RUN_ID"])
            tool_top_k = int(values["STAGE20_TOOL_TOP_K"] or "2")
        except ValueError as exc:
            raise RuntimeError(
                "STAGE20_PROJECT_ID, STAGE20_RUN_ID, and STAGE20_TOOL_TOP_K must be integers"
            ) from exc
        if project_id < 1 or run_id < 1 or tool_top_k < 1:
            raise RuntimeError(
                "STAGE20_PROJECT_ID, STAGE20_RUN_ID, and STAGE20_TOOL_TOP_K must be positive"
            )
        return cls(
            base_url=values["JAVA_APIOPS_BASE_URL"],
            token=values["JAVA_APIOPS_TOKEN"],
            project_id=project_id,
            run_id=run_id,
            trace_id=values["STAGE20_TRACE_ID"],
            failure_mode=values["STAGE20_FAILURE_MODE"].upper() or None,
            expected_tool_status=values["STAGE20_EXPECT_TOOL_STATUS"].upper() or None,
            tool_query=values["STAGE20_TOOL_QUERY"] or "order endpoint failure evidence",
            tool_top_k=tool_top_k,
        )


@dataclass(frozen=True)
class GenerationE2EConfig:
    """Cross-process inputs for the existing metadata plus Stage 16 graph path."""

    base_url: str
    token: str
    project_id: int
    api_id: str
    trace_id: str
    candidate_fixture: str | None = None

    @classmethod
    def from_environment(cls) -> GenerationE2EConfig:
        values = {
            name: os.environ.get(name, "").strip()
            for name in (
                "JAVA_APIOPS_BASE_URL",
                "JAVA_APIOPS_TOKEN",
                "STAGE20_PROJECT_ID",
                "STAGE20_API_ID",
                "STAGE20_TRACE_ID",
                "STAGE21_CANDIDATE_FIXTURE",
            )
        }
        required_names = (
            "JAVA_APIOPS_BASE_URL",
            "JAVA_APIOPS_TOKEN",
            "STAGE20_PROJECT_ID",
            "STAGE20_API_ID",
            "STAGE20_TRACE_ID",
        )
        missing = [name for name in required_names if not values[name]]
        if missing:
            raise RuntimeError(f"required environment is missing: {', '.join(missing)}")
        try:
            project_id = int(values["STAGE20_PROJECT_ID"])
        except ValueError as exc:
            raise RuntimeError("STAGE20_PROJECT_ID must be an integer") from exc
        if project_id < 1:
            raise RuntimeError("STAGE20_PROJECT_ID must be positive")
        return cls(
            base_url=values["JAVA_APIOPS_BASE_URL"],
            token=values["JAVA_APIOPS_TOKEN"],
            project_id=project_id,
            api_id=values["STAGE20_API_ID"],
            trace_id=values["STAGE20_TRACE_ID"],
            candidate_fixture=values["STAGE21_CANDIDATE_FIXTURE"] or None,
        )


@dataclass(frozen=True)
class RunnerFailureE2EConfig:
    """Inputs for the real Runner terminal-failure cross-process probe."""

    base_url: str
    token: str
    project_id: int
    trace_id: str
    testcase_json: str
    readback_deadline_seconds: float = 60.0

    @classmethod
    def from_environment(cls) -> RunnerFailureE2EConfig:
        values = {
            name: os.environ.get(name, "").strip()
            for name in (
                "JAVA_APIOPS_BASE_URL",
                "JAVA_APIOPS_TOKEN",
                "STAGE20_PROJECT_ID",
                "STAGE20_TRACE_ID",
                "STAGE20_TESTCASE_JSON",
                "STAGE20_RUNNER_READBACK_DEADLINE_SECONDS",
            )
        }
        required_names = (
            "JAVA_APIOPS_BASE_URL",
            "JAVA_APIOPS_TOKEN",
            "STAGE20_PROJECT_ID",
            "STAGE20_TRACE_ID",
            "STAGE20_TESTCASE_JSON",
        )
        missing = [name for name in required_names if not values[name]]
        if missing:
            raise RuntimeError(f"required environment is missing: {', '.join(missing)}")
        try:
            project_id = int(values["STAGE20_PROJECT_ID"])
        except ValueError as exc:
            raise RuntimeError("STAGE20_PROJECT_ID must be an integer") from exc
        if project_id < 1:
            raise RuntimeError("STAGE20_PROJECT_ID must be positive")
        deadline = values["STAGE20_RUNNER_READBACK_DEADLINE_SECONDS"] or "60"
        try:
            readback_deadline_seconds = float(deadline)
        except ValueError as exc:
            raise RuntimeError("STAGE20_RUNNER_READBACK_DEADLINE_SECONDS must be numeric") from exc
        if readback_deadline_seconds <= 0:
            raise RuntimeError("STAGE20_RUNNER_READBACK_DEADLINE_SECONDS must be positive")
        return cls(
            base_url=values["JAVA_APIOPS_BASE_URL"],
            token=values["JAVA_APIOPS_TOKEN"],
            project_id=project_id,
            trace_id=values["STAGE20_TRACE_ID"],
            testcase_json=values["STAGE20_TESTCASE_JSON"],
            readback_deadline_seconds=readback_deadline_seconds,
        )


@dataclass(frozen=True)
class FinalE2EConfig:
    """Inputs for the deterministic Stage 20 final cross-process acceptance."""

    base_url: str
    token: str
    project_id: int
    api_id: str
    trace_id: str
    demo_order_base_url: str
    tool_query: str = "order endpoint failure evidence"
    tool_top_k: int = 2
    readback_deadline_seconds: float = 60.0

    @classmethod
    def from_environment(cls) -> FinalE2EConfig:
        values = {
            name: os.environ.get(name, "").strip()
            for name in (
                "JAVA_APIOPS_BASE_URL",
                "JAVA_APIOPS_TOKEN",
                "STAGE20_PROJECT_ID",
                "STAGE20_API_ID",
                "STAGE20_TRACE_ID",
                "STAGE20_DEMO_ORDER_BASE_URL",
                "STAGE20_RUNNER_READBACK_DEADLINE_SECONDS",
                "STAGE20_TOOL_QUERY",
                "STAGE20_TOOL_TOP_K",
            )
        }
        required_names = (
            "JAVA_APIOPS_BASE_URL",
            "JAVA_APIOPS_TOKEN",
            "STAGE20_PROJECT_ID",
            "STAGE20_API_ID",
            "STAGE20_TRACE_ID",
            "STAGE20_DEMO_ORDER_BASE_URL",
        )
        missing = [name for name in required_names if not values[name]]
        if missing:
            raise RuntimeError(f"required environment is missing: {', '.join(missing)}")
        try:
            project_id = int(values["STAGE20_PROJECT_ID"])
            tool_top_k = int(values["STAGE20_TOOL_TOP_K"] or "2")
            deadline = float(values["STAGE20_RUNNER_READBACK_DEADLINE_SECONDS"] or "60")
        except ValueError as exc:
            raise RuntimeError("Stage 20 final numeric environment is invalid") from exc
        if project_id < 1 or tool_top_k < 1 or deadline <= 0:
            raise RuntimeError("Stage 20 final numeric environment must be positive")
        return cls(
            base_url=values["JAVA_APIOPS_BASE_URL"],
            token=values["JAVA_APIOPS_TOKEN"],
            project_id=project_id,
            api_id=values["STAGE20_API_ID"],
            trace_id=values["STAGE20_TRACE_ID"],
            demo_order_base_url=values["STAGE20_DEMO_ORDER_BASE_URL"].rstrip("/"),
            tool_query=values["STAGE20_TOOL_QUERY"] or "order endpoint failure evidence",
            tool_top_k=tool_top_k,
            readback_deadline_seconds=deadline,
        )


class SequenceLLM:
    """Deterministic E2E decisions; Java resource execution remains real."""

    def __init__(self, responses: Sequence[dict[str, object]]) -> None:
        self._responses = list(responses)
        self.prompts: list[str] = []

    async def complete(self, prompt: str) -> str:
        self.prompts.append(prompt)
        if not self._responses:
            raise AssertionError("unexpected diagnosis model call")
        return json.dumps(self._responses.pop(0), separators=(",", ":"))


def _load_generation_support_fixture(reference: str | None) -> dict[str, object] | None:
    """Read the task's checked-in support fixture without treating it as execution output."""

    if reference is None:
        return None
    path = Path(reference)
    if not path.is_absolute():
        path = Path(__file__).resolve().parents[2] / path
    if not path.is_file():
        raise FileNotFoundError(f"Stage 21 generation support fixture is missing: {reference}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Stage 21 generation support fixture must contain a JSON object")
    return {
        "reference": reference,
        "path": str(path.resolve()),
        "caseId": payload.get("caseId"),
    }


async def run_generation_e2e(config: GenerationE2EConfig) -> dict[str, Any]:
    """Run the real Java metadata boundary and the existing Stage 16 graph only.

    TestCase Generation does not require a Runner submit.  The Java metadata query,
    Python generation graph, validator, and trace recorder are the existing Stage 20
    generation inputs; this mode intentionally stops before the Java Runner boundary.
    """

    support_fixture = _load_generation_support_fixture(config.candidate_fixture)
    agent_run_id = new_identity("stage21-generation-agent")
    sink = InMemoryTraceSink()
    observations: list[dict[str, object]] = []

    async def observe_response(response: httpx.Response) -> None:
        observations.append(
            {
                "path": response.request.url.path,
                "status": response.status_code,
                "requestTraceId": response.request.headers.get("x-trace-id"),
                "responseTraceId": response.headers.get("x-trace-id"),
                "responseRequestId": response.headers.get("x-request-id"),
            }
        )

    async with httpx.AsyncClient(
        trust_env=False,
        event_hooks={"response": [observe_response]},
    ) as http_client:
        client = JavaApiOpsClient(
            http_client,
            base_url=config.base_url,
            timeout_seconds=5,
        )
        metadata = await client.get_api_metadata(
            project_id=config.project_id,
            api_id=config.api_id,
            token=config.token,
            trace_id=config.trace_id,
        )
        generation_context = build_generation_context(metadata, TestStrategy.HAPPY_PATH)
        graph = build_testcase_generation_graph(
            TestCaseGenerator(
                DeterministicFakeLLM(
                    candidate(
                        config.project_id,
                        config.api_id,
                        base_url=(metadata.servers or [{}])[0].get("url", "http://127.0.0.1:18080"),
                    )
                )
            ),
            trace_recorder=TraceRecorder(sink),
        )
        state = {
            "trace_id": config.trace_id,
            "agent_run_id": agent_run_id,
            "phase": WorkflowPhase.INITIAL,
            "route": None,
            "error": None,
            "attempt_count": 0,
            "max_attempts": 0,
            "project_id": config.project_id,
            "api_id": config.api_id,
            "generation_intent": TestStrategy.HAPPY_PATH.value,
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
        testcase = Stage20ExecutionWorkflow._accepted_testcase(generated)

    if testcase.project_id != config.project_id or testcase.api_id != config.api_id:
        raise AssertionError("generated TestCase DSL identity does not match Java metadata request")
    if not any(item["path"].endswith(f"/openapi/apis/{config.api_id}") for item in observations):
        raise AssertionError("generation did not read Java metadata through its public boundary")
    if any(item["path"].endswith("/test-batches") for item in observations):
        raise AssertionError("generation-only path unexpectedly submitted to Java Runner")

    return {
        "projectId": config.project_id,
        "apiId": config.api_id,
        "metadata": {
            "operationId": metadata.operation_id,
            "method": metadata.method,
            "path": metadata.path,
            "typed": type(metadata).__name__,
        },
        "generation": {
            "fakeLlm": "DeterministicFakeLLM",
            "validatedDsl": type(testcase).__name__,
            "caseId": testcase.case_id,
            "supportFixture": support_fixture,
            "traceRecordCount": len(sink.records),
        },
        "identity": {
            "traceId": config.trace_id,
            "agentRunId": agent_run_id,
        },
        "httpRequests": observations,
    }


def _final_diagnosis(
    report: TestReport,
    *,
    trace_id: str,
    agent_run_id: str,
) -> dict[str, object]:
    provisional_hypotheses: list[dict[str, object]] = []
    if report.summary.failure_type not in {"NONE", "UNKNOWN"}:
        provisional_hypotheses.append(
            {
                "statement": (
                    f"Observed {report.summary.failure_type} is the current provisional "
                    "failure mechanism; the underlying root cause remains unproven."
                ),
                "confidence": "LOW",
                "evidenceRefs": [{"itemId": report.report_id}],
            }
        )
    return {
        "schemaVersion": "0.1.0",
        "reportId": report.report_id,
        "agentRunId": agent_run_id,
        "projectId": report.project_id,
        "runId": report.run_id,
        "failureType": report.summary.failure_type,
        "summary": "The bounded Java-owned evidence was inspected without asserting a root cause.",
        "rootCauseHypotheses": provisional_hypotheses,
        "sufficientEvidence": False,
        "limitations": ["The bounded evidence does not establish a deterministic root cause."],
        "recommendedChecks": ["Review additional project-authorized execution evidence."],
        "traceId": trace_id,
    }


def _trace_tool_reference(
    records: tuple[dict[str, object], ...],
) -> tuple[dict[str, object], str | None]:
    tool_records = [record for record in records if record.get("record_type") == "tool_result"]
    if len(tool_records) != 1:
        raise AssertionError("expected exactly one ToolResultRecord in TraceRecorder")
    record = tool_records[0]
    tool_call_id = record.get("java_tool_call_id")
    if not isinstance(tool_call_id, str) or not tool_call_id:
        raise AssertionError("TraceRecorder did not preserve Java toolCallId")
    rag_query_ids = [
        reference.get("rag_query_id")
        for trace_record in records
        if trace_record.get("record_type") == "retrieval"
        and isinstance((reference := trace_record.get("reference")), dict)
        and isinstance(reference.get("rag_query_id"), str)
    ]
    return record, rag_query_ids[-1] if rag_query_ids else None


def _retrieved_evidence_ids(result: ToolResult) -> tuple[str, ...]:
    try:
        retrieval = EvidenceRetrieval.model_validate(result.data)
    except Exception:  # noqa: BLE001 - malformed provider data remains a bounded fact
        return ()
    return tuple(item.citation.source_id for item in retrieval.evidence)


async def run_diagnosis_e2e(config: DiagnosisE2EConfig) -> dict[str, Any]:
    """Run real Report/Gateway boundaries and emit only correlation references."""

    agent_run_id = new_identity("stage20-diagnosis-agent")
    workflow_id = new_identity("stage20-diagnosis-workflow")
    sink = InMemoryTraceSink()
    recorder = TraceRecorder(sink)

    http_observations: list[dict[str, object]] = []

    async def observe_response(response: httpx.Response) -> None:
        http_observations.append(
            {
                "path": response.request.url.path,
                "status": response.status_code,
                "requestTraceId": response.request.headers.get("x-trace-id"),
                "responseTraceId": response.headers.get("x-trace-id"),
                "responseRequestId": response.headers.get("x-request-id"),
            }
        )

    async with httpx.AsyncClient(
        trust_env=False,
        event_hooks={"response": [observe_response]},
    ) as http_client:
        client = JavaApiOpsClient(
            http_client,
            base_url=config.base_url,
            timeout_seconds=5,
        )
        report = await client.get_test_report(
            project_id=config.project_id,
            run_id=config.run_id,
            token=config.token,
            trace_id=config.trace_id,
        )
        llm = SequenceLLM(
            [
                {
                    "tool_name": "rag.search",
                    "arguments": {"query": config.tool_query, "topK": config.tool_top_k},
                },
                _final_diagnosis(
                    report,
                    trace_id=config.trace_id,
                    agent_run_id=agent_run_id,
                ),
            ]
        )
        catalog = ToolCatalog()
        gateway = JavaApiOpsToolGatewayAdapter(
            client,
            project_id=config.project_id,
            token_provider=lambda: config.token,
        )
        graph = build_diagnosis_workflow(
            llm,
            ToolRouter(catalog, {"rag.search": gateway}),
            project_id=config.project_id,
            catalog=catalog,
            checkpointer=InMemorySaver(),
            trace_recorder=recorder,
        )
        state = diagnosis_initial_state(
            report,
            trace_id=config.trace_id,
            agent_run_id=agent_run_id,
            workflow_id=workflow_id,
        )
        result = await graph.ainvoke(state, config=checkpoint_config(workflow_id))

    tool_result = result.get("tool_result")
    diagnosis_report = result.get("diagnosis_report")
    if not isinstance(tool_result, ToolResult):
        raise AssertionError("real Java Gateway did not return a typed ToolResult")
    if diagnosis_report is None:
        raise AssertionError("diagnosis continuation did not return DiagnosisReport")
    trace_record, rag_query_id = _trace_tool_reference(sink.records)
    trace_tool_call_id = str(trace_record["java_tool_call_id"])
    if trace_tool_call_id != tool_result.tool_call_id:
        raise AssertionError("Python Trace and Java ToolResult toolCallId differ")
    if result.get("tool_calls_used") != 1:
        raise AssertionError("bounded diagnosis must execute exactly one tool call")
    if tool_result.status == "SUCCESS" and not result.get("untrusted_evidence"):
        raise AssertionError("real ToolResult did not pass the output evidence guard")
    if len(llm.prompts) != 2:
        raise AssertionError("diagnosis must perform one initial and one continuation call")
    if (
        diagnosis_report.project_id != report.project_id
        or diagnosis_report.run_id != report.run_id
        or diagnosis_report.report_id != report.report_id
    ):
        raise AssertionError("DiagnosisReport changed Java Report authority identities")
    if (
        config.expected_tool_status is not None
        and tool_result.status != config.expected_tool_status
    ):
        raise AssertionError(
            "Java ToolResult status did not match the controlled failure expectation"
        )

    failure = result.get("failure")
    failure_code = getattr(getattr(failure, "code", None), "value", None)

    payload: dict[str, Any] = {
        "projectId": report.project_id,
        "taskId": report.task_id,
        "runId": report.run_id,
        "reportId": report.report_id,
        "testReportStatus": report.status,
        "failureType": report.summary.failure_type,
        "traceId": config.trace_id,
        "agentRunId": agent_run_id,
        "agentStepId": trace_record.get("agent_step_id"),
        "toolName": trace_record["tool_name"],
        "toolCallId": trace_tool_call_id,
        "toolResultToolCallId": tool_result.tool_call_id,
        "toolStatus": tool_result.status,
        "toolArguments": {"query": config.tool_query, "topK": config.tool_top_k},
        "evidenceIds": list(_retrieved_evidence_ids(tool_result)),
        "toolFailureCode": failure_code,
        "diagnosisReport": {
            "projectId": diagnosis_report.project_id,
            "runId": diagnosis_report.run_id,
            "reportId": diagnosis_report.report_id,
            "sufficientEvidence": diagnosis_report.sufficient_evidence,
            "rootCauseHypothesesCount": len(diagnosis_report.root_cause_hypotheses),
            "limitations": diagnosis_report.limitations,
            "recommendedChecksCount": len(diagnosis_report.recommended_checks),
        },
        "toolCallCount": result["tool_calls_used"],
        "retryCount": 0,
        "rawFallbackUsed": False,
        "guardedEvidenceCount": len(result.get("untrusted_evidence", ())),
        "httpRequests": http_observations,
    }
    if rag_query_id is not None:
        payload["ragQueryId"] = rag_query_id
    return payload


def _failure_tool_call(
    project_id: int,
    trace_id: str,
    *,
    query: str,
    top_k: int,
    agent_run_id: str = "stage20-failure-probe",
) -> object:
    return map_tool_intent(
        ToolIntent(
            tool_name="rag.search",
            arguments={"query": query, "topK": top_k},
        ),
        catalog=ToolCatalog(),
        agent_run_id=agent_run_id,
        project_id=str(project_id),
        trace_id=trace_id,
    )


def _invalid_runner_probe_case(project_id: int) -> TestCaseDSL:
    """Build an intentionally invalid test-only request for Runner rejection probes."""

    return TestCaseDSL.model_construct(
        schema_version="1.0.0",
        case_id="stage20-invalid-runner-probe",
        project_id=project_id,
        api_id="stage20-invalid-runner-probe",
        name="Stage 20 invalid runner probe",
        environment={"baseUrl": "http://127.0.0.1:1", "variables": {}},
        steps=[],
    )


async def run_failure_probe(config: DiagnosisE2EConfig) -> dict[str, Any]:
    """Exercise one real public-boundary failure without a resource fallback.

    This mode is intentionally separate from the diagnosis workflow: authentication,
    authorization, not-found, and unavailable probes validate the shared client/error
    boundary; the controlled Java failure profile uses ``run_diagnosis_e2e`` so the
    bounded Stage 20 workflow remains the consumer of TIMEOUT/FAILED ToolResults.
    """

    mode = config.failure_mode
    if mode is None:
        raise RuntimeError("STAGE20_FAILURE_MODE is required for --failure-probe")
    agent_run_id = new_identity("stage20-failure-agent")
    observations: list[dict[str, object]] = []

    async def observe_response(response: httpx.Response) -> None:
        observations.append(
            {
                "path": response.request.url.path,
                "status": response.status_code,
                "requestTraceId": response.request.headers.get("x-trace-id"),
                "responseTraceId": response.headers.get("x-trace-id"),
                "responseRequestId": response.headers.get("x-request-id"),
            }
        )

    async with httpx.AsyncClient(
        trust_env=False,
        event_hooks={"response": [observe_response]},
    ) as http_client:
        client = JavaApiOpsClient(
            http_client,
            base_url=config.base_url,
            timeout_seconds=2,
        )
        if mode == "AUTH_401":
            try:
                await client.get_test_report(
                    project_id=config.project_id,
                    run_id=config.run_id,
                    token=config.token,
                    trace_id=config.trace_id,
                )
            except JavaApiOpsAuthenticationError as exc:
                return {
                    "failureMode": mode,
                    "semantic": "authentication_failure",
                    "httpStatus": exc.status_code,
                    "traceId": config.trace_id,
                    "retryCount": 0,
                    "rawFallbackUsed": False,
                    "httpRequests": observations,
                }
            raise AssertionError("invalid credential was not rejected with HTTP 401")

        if mode == "PROJECT_403":
            project_id = config.project_id + 1
            result = await client.execute_tool_call(
                project_id=project_id,
                tool_call=_failure_tool_call(
                    project_id,
                    config.trace_id,
                    query=config.tool_query,
                    top_k=config.tool_top_k,
                    agent_run_id=agent_run_id,
                ),
                token=config.token,
            )
            if result.status != "FORBIDDEN" or not result.tool_call_id:
                raise AssertionError("unauthorized project did not yield Java FORBIDDEN")
            return {
                "failureMode": mode,
                "semantic": "project_authorization_failure",
                "httpStatus": 200,
                "projectId": project_id,
                "toolName": "rag.search",
                "toolStatus": result.status,
                "toolCallId": result.tool_call_id,
                "toolArguments": {"query": config.tool_query, "topK": config.tool_top_k},
                "agentRunId": agent_run_id,
                "traceId": config.trace_id,
                "retryCount": 0,
                "rawFallbackUsed": False,
                "httpRequests": observations,
            }

        if mode == "PROJECT_HTTP_403":
            project_id = config.project_id + 1
            try:
                await client.get_test_report(
                    project_id=project_id,
                    run_id=config.run_id,
                    token=config.token,
                    trace_id=config.trace_id,
                )
            except JavaApiOpsAuthorizationError as exc:
                return {
                    "failureMode": mode,
                    "semantic": "project_authorization_failure",
                    "httpStatus": exc.status_code,
                    "projectId": project_id,
                    "traceId": config.trace_id,
                    "retryCount": 0,
                    "rawFallbackUsed": False,
                    "httpRequests": observations,
                }
            raise AssertionError("unauthorized project report was not rejected with HTTP 403")

        if mode == "RUNNER_REJECT":
            try:
                await client.submit_testcase(
                    project_id=config.project_id,
                    testcase=_invalid_runner_probe_case(config.project_id),
                    token=config.token,
                    trace_id=config.trace_id,
                )
            except JavaApiOpsClientError as exc:
                if exc.status_code != 400:
                    raise AssertionError("Runner rejection did not use HTTP 400") from exc
                return {
                    "failureMode": mode,
                    "semantic": "runner_rejected_before_execution",
                    "httpStatus": exc.status_code,
                    "traceId": config.trace_id,
                    "retryCount": 0,
                    "rawFallbackUsed": False,
                    "httpRequests": observations,
                }
            raise AssertionError("invalid Runner request was unexpectedly accepted")

        if mode == "NOT_FOUND":
            try:
                await client.get_api_metadata(
                    project_id=config.project_id,
                    api_id="stage20-missing-api",
                    token=config.token,
                    trace_id=config.trace_id,
                )
            except JavaApiOpsNotFoundError as exc:
                return {
                    "failureMode": mode,
                    "semantic": "resource_not_found",
                    "httpStatus": exc.status_code,
                    "resource": "metadata",
                    "traceId": config.trace_id,
                    "retryCount": 0,
                    "rawFallbackUsed": False,
                    "httpRequests": observations,
                }
            raise AssertionError("missing Java report was not rejected with HTTP 404")

        if mode == "MALFORMED_RESPONSE":
            try:
                await client.get_test_report(
                    project_id=config.project_id,
                    run_id=config.run_id,
                    token=config.token,
                    trace_id=config.trace_id,
                )
            except (JavaApiOpsMalformedResponseError, JavaApiOpsResponseValidationError) as exc:
                return {
                    "failureMode": mode,
                    "semantic": "malformed_response",
                    "errorType": type(exc).__name__,
                    "traceId": config.trace_id,
                    "retryCount": 0,
                    "rawFallbackUsed": False,
                    "httpRequests": observations,
                }
            raise AssertionError("malformed response unexpectedly passed strict parsing")

        if mode == "JAVA_UNAVAILABLE":
            try:
                await client.get_test_report(
                    project_id=config.project_id,
                    run_id=config.run_id,
                    token=config.token,
                    trace_id=config.trace_id,
                )
            except JavaApiOpsTransportError:
                return {
                    "failureMode": mode,
                    "semantic": "transport_unavailable",
                    "traceId": config.trace_id,
                    "retryCount": 0,
                    "rawFallbackUsed": False,
                    "httpRequests": observations,
                }
            raise AssertionError("unavailable Java boundary unexpectedly returned")

        raise RuntimeError(f"unsupported Stage 20 failure mode: {mode}")


class RecordingStream(httpx.AsyncByteStream):
    def __init__(self, inner: httpx.AsyncByteStream, chunks: list[bytes]) -> None:
        self._inner = inner
        self._chunks = chunks

    async def __aiter__(self):
        async for chunk in self._inner:
            self._chunks.append(chunk)
            yield chunk

    async def aclose(self) -> None:
        await self._inner.aclose()


def candidate(
    project_id: int,
    api_id: str,
    *,
    base_url: str = "http://127.0.0.1:18080",
) -> str:
    return json.dumps(
        {
            "schemaVersion": "1.0.0",
            "caseId": "stage20-real-products",
            "projectId": project_id,
            "apiId": api_id,
            "name": "Stage 20 real products happy path",
            "environment": {"baseUrl": base_url, "variables": {}},
            "steps": [
                {
                    "stepId": "list-products",
                    "name": "List products",
                    "request": {"method": "GET", "path": "/products"},
                    "assertions": [{"type": "STATUS_CODE", "expected": 200}],
                    "extractors": [],
                }
            ],
        },
        separators=(",", ":"),
    )


async def run(args: argparse.Namespace) -> dict[str, Any]:
    token = os.environ.get("JAVA_APIOPS_TOKEN", "").strip()
    if not token:
        raise RuntimeError("JAVA_APIOPS_TOKEN is required")
    trace_id = new_identity("stage20-real-trace")
    agent_run_id = new_identity("stage20-real-agent")
    responses: list[dict[str, object]] = []
    sse_chunks: list[bytes] = []

    async def observe_response(response: httpx.Response) -> None:
        request_trace = response.request.headers.get("x-trace-id")
        responses.append(
            {
                "path": response.request.url.path,
                "status": response.status_code,
                "content_type": response.headers.get("content-type"),
                "trace_echo_matches": response.headers.get("x-trace-id") == request_trace,
                "request_trace": request_trace,
                "response_trace": response.headers.get("x-trace-id"),
                "response_request_id": response.headers.get("x-request-id"),
            }
        )
        if response.request.url.path.endswith("/progress/events"):
            response.stream = RecordingStream(response.stream, sse_chunks)

    sink = InMemoryTraceSink()
    policy = RunnerReadbackPolicy()
    async with httpx.AsyncClient(
        trust_env=False,
        event_hooks={"response": [observe_response]},
    ) as http_client:
        client = JavaApiOpsClient(
            http_client,
            base_url=args.base_url,
            timeout_seconds=5,
        )
        invalid = Stage20ExecutionWorkflow(
            client,
            TestCaseGenerator(DeterministicFakeLLM("{}")),
            token_provider=lambda: token,
            readback_policy=policy,
        )
        before_invalid = len(responses)
        try:
            await invalid.execute(
                project_id=args.project_id,
                api_id=args.api_id,
                strategy=TestStrategy.HAPPY_PATH,
            )
        except GeneratedTestCaseNotValidatedError:
            pass
        else:
            raise AssertionError("invalid candidate unexpectedly reached execution")
        invalid_paths = [item["path"] for item in responses[before_invalid:]]
        if any(str(path).endswith("/test-batches") for path in invalid_paths):
            raise AssertionError("invalid candidate reached Runner submit")

        workflow = Stage20ExecutionWorkflow(
            client,
            TestCaseGenerator(DeterministicFakeLLM(candidate(args.project_id, args.api_id))),
            token_provider=lambda: token,
            trace_recorder=TraceRecorder(sink),
            readback_policy=policy,
        )
        result = await workflow.execute(
            project_id=args.project_id,
            api_id=args.api_id,
            strategy=TestStrategy.HAPPY_PATH,
            trace_id=trace_id,
            agent_run_id=agent_run_id,
        )

    valid_responses = [item for item in responses if item["request_trace"] == trace_id]
    sse_text = b"".join(sse_chunks).decode("utf-8")
    events = [
        line.removeprefix("event:").strip()
        for line in sse_text.splitlines()
        if line.startswith("event:")
    ]
    statuses = []
    for line in sse_text.splitlines():
        if line.startswith("data:"):
            statuses.append(json.loads(line.removeprefix("data:").strip())["status"])
    references = [
        {
            "traceId": item["trace_id"],
            "agentRunId": item["agent_run_id"],
            "batchId": item["java_batch_id"],
            "taskId": item["java_task_id"],
            "runId": item["java_run_id"],
            "status": item["java_status"],
            "stage": item["reference_stage"],
        }
        for item in sink.records
        if item["record_type"] == "java_run_reference"
    ]
    return {
        "projectId": args.project_id,
        "apiId": args.api_id,
        "metadata": {
            "operationId": result.metadata.operation_id,
            "method": result.metadata.method,
            "path": result.metadata.path,
            "typed": type(result.metadata).__name__,
        },
        "generation": {
            "fakeLlm": "DeterministicFakeLLM",
            "validatedDsl": type(result.testcase).__name__,
            "invalidCandidateSubmitBlocked": True,
        },
        "identity": {
            "traceId": result.trace_id,
            "agentRunId": result.agent_run_id,
            "batchId": result.submission.batch_id,
            "taskId": result.submission.task_ids[0],
            "runId": result.submission.run_ids[0],
            "reportId": result.report.report_id,
        },
        "http": valid_responses,
        "sse": {
            "events": events,
            "statuses": statuses,
            "terminalStatus": result.terminal_progress.status,
            "overallDeadlineSeconds": policy.overall_deadline_seconds,
        },
        "report": {
            "projectId": result.report.project_id,
            "taskId": result.report.task_id,
            "runId": result.report.run_id,
            "reportId": result.report.report_id,
            "status": result.report.status,
            "summary": result.report.summary.model_dump(mode="json"),
        },
        "traceReferences": references,
    }


async def run_final_e2e(config: FinalE2EConfig) -> dict[str, Any]:
    """Run the accepted Stage 20 main chain with one trace and one agent run."""

    agent_run_id = new_identity("stage20-final-agent")
    workflow_id = new_identity("stage20-final-diagnosis")
    sink = InMemoryTraceSink()
    recorder = TraceRecorder(sink)
    responses: list[dict[str, object]] = []
    sse_chunks: list[bytes] = []

    async def observe_response(response: httpx.Response) -> None:
        request_trace = response.request.headers.get("x-trace-id")
        responses.append(
            {
                "path": response.request.url.path,
                "status": response.status_code,
                "requestTraceId": request_trace,
                "responseTraceId": response.headers.get("x-trace-id"),
                "responseRequestId": response.headers.get("x-request-id"),
            }
        )
        if response.request.url.path.endswith("/progress/events"):
            response.stream = RecordingStream(response.stream, sse_chunks)

    policy = RunnerReadbackPolicy(config.readback_deadline_seconds)
    async with httpx.AsyncClient(
        trust_env=False,
        event_hooks={"response": [observe_response]},
    ) as http_client:
        client = JavaApiOpsClient(
            http_client,
            base_url=config.base_url,
            timeout_seconds=5,
        )
        execution = Stage20ExecutionWorkflow(
            client,
            TestCaseGenerator(
                DeterministicFakeLLM(
                    candidate(
                        config.project_id,
                        config.api_id,
                        base_url=config.demo_order_base_url,
                    )
                )
            ),
            token_provider=lambda: config.token,
            trace_recorder=recorder,
            readback_policy=policy,
        )
        execution_result = await execution.execute(
            project_id=config.project_id,
            api_id=config.api_id,
            strategy=TestStrategy.HAPPY_PATH,
            trace_id=config.trace_id,
            agent_run_id=agent_run_id,
        )

        diagnosis_llm = SequenceLLM(
            [
                {
                    "tool_name": "rag.search",
                    "arguments": {"query": "order endpoint execution evidence", "topK": 2},
                },
                _final_diagnosis(
                    execution_result.report,
                    trace_id=config.trace_id,
                    agent_run_id=agent_run_id,
                ),
            ]
        )
        catalog = ToolCatalog()
        gateway = JavaApiOpsToolGatewayAdapter(
            client,
            project_id=config.project_id,
            token_provider=lambda: config.token,
        )
        diagnosis_graph = build_diagnosis_workflow(
            diagnosis_llm,
            ToolRouter(catalog, {"rag.search": gateway}),
            project_id=config.project_id,
            catalog=catalog,
            checkpointer=InMemorySaver(),
            trace_recorder=recorder,
        )
        diagnosis_state = diagnosis_initial_state(
            execution_result.report,
            trace_id=config.trace_id,
            agent_run_id=agent_run_id,
            workflow_id=workflow_id,
        )
        diagnosis_result = await diagnosis_graph.ainvoke(
            diagnosis_state,
            config=checkpoint_config(workflow_id),
        )

    tool_result = diagnosis_result.get("tool_result")
    diagnosis_report = diagnosis_result.get("diagnosis_report")
    if not isinstance(tool_result, ToolResult):
        raise AssertionError("real Java Gateway did not return a typed ToolResult")
    if diagnosis_report is None:
        raise AssertionError("diagnosis continuation did not return DiagnosisReport")
    trace_record, rag_query_id = _trace_tool_reference(sink.records)
    trace_tool_call_id = str(trace_record["java_tool_call_id"])
    if trace_tool_call_id != tool_result.tool_call_id:
        raise AssertionError("Python Trace and Java ToolResult toolCallId differ")
    if diagnosis_result.get("tool_calls_used") != 1:
        raise AssertionError("Stage 20 final E2E must execute exactly one tool call")
    if tool_result.status != "SUCCESS" or not diagnosis_result.get("untrusted_evidence"):
        raise AssertionError("real Java evidence did not pass the existing output guard")
    if len(diagnosis_llm.prompts) != 2:
        raise AssertionError("diagnosis must perform one initial and one continuation call")
    report = execution_result.report
    if (
        diagnosis_report.project_id != report.project_id
        or diagnosis_report.run_id != report.run_id
        or diagnosis_report.report_id != report.report_id
    ):
        raise AssertionError("DiagnosisReport changed Java Report authority identities")

    correlated_responses = [item for item in responses if item["requestTraceId"] == config.trace_id]
    request_ids = [
        item["responseRequestId"]
        for item in correlated_responses
        if isinstance(item.get("responseRequestId"), str)
    ]
    if len(request_ids) != len(set(request_ids)):
        raise AssertionError("Java requestId must be unique per inbound HTTP request")
    if any(
        item["responseTraceId"] != config.trace_id or item["responseRequestId"] == config.trace_id
        for item in correlated_responses
    ):
        raise AssertionError("Java traceId/requestId correlation contract was not preserved")

    references = [
        {
            "batchId": item["java_batch_id"],
            "taskId": item["java_task_id"],
            "runId": item["java_run_id"],
            "status": item["java_status"],
            "stage": item["reference_stage"],
        }
        for item in sink.records
        if item["record_type"] == "java_run_reference"
    ]
    return {
        "projectId": report.project_id,
        "apiId": config.api_id,
        "metadata": {
            "operationId": execution_result.metadata.operation_id,
            "method": execution_result.metadata.method,
            "path": execution_result.metadata.path,
            "typed": type(execution_result.metadata).__name__,
        },
        "generation": {
            "fakeLlm": "DeterministicFakeLLM",
            "validatedDsl": type(execution_result.testcase).__name__,
            "caseId": execution_result.testcase.case_id,
        },
        "identity": {
            "traceId": config.trace_id,
            "agentRunId": agent_run_id,
            "batchId": execution_result.submission.batch_id,
            "taskId": report.task_id,
            "runId": report.run_id,
            "reportId": report.report_id,
            "agentStepId": trace_record.get("agent_step_id"),
            "toolCallId": trace_tool_call_id,
        },
        "runner": {
            "terminalStatus": execution_result.terminal_progress.status,
            "overallDeadlineSeconds": policy.overall_deadline_seconds,
        },
        "report": {
            "projectId": report.project_id,
            "taskId": report.task_id,
            "runId": report.run_id,
            "reportId": report.report_id,
            "status": report.status,
            "failureType": report.summary.failure_type,
        },
        "tool": {
            "name": trace_record["tool_name"],
            "status": tool_result.status,
            "toolCallId": tool_result.tool_call_id,
            "traceToolCallId": trace_tool_call_id,
            "ragQueryId": rag_query_id,
            "arguments": {"query": config.tool_query, "topK": config.tool_top_k},
            "evidenceIds": list(_retrieved_evidence_ids(tool_result)),
            "guardedEvidenceCount": len(diagnosis_result.get("untrusted_evidence", ())),
        },
        "diagnosisReport": {
            "projectId": diagnosis_report.project_id,
            "runId": diagnosis_report.run_id,
            "reportId": diagnosis_report.report_id,
            "sufficientEvidence": diagnosis_report.sufficient_evidence,
            "rootCauseHypothesesCount": len(diagnosis_report.root_cause_hypotheses),
            "limitations": diagnosis_report.limitations,
            "recommendedChecksCount": len(diagnosis_report.recommended_checks),
        },
        "traceReferences": references,
        "httpRequests": correlated_responses,
        "toolCallCount": diagnosis_result["tool_calls_used"],
        "retryCount": 0,
        "rawFallbackUsed": False,
    }


def _record_runner_reference(
    recorder: TraceRecorder,
    *,
    trace_id: str,
    agent_run_id: str,
    project_id: int,
    submission,
    task_id: int,
    run_id: int,
    stage: str,
    status: str | None = None,
) -> None:
    observe(
        recorder,
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
            reference_stage=stage,
            java_batch_id=submission.batch_id,
            java_task_id=task_id,
            java_run_id=run_id,
            java_status=status,
        ),
    )


async def run_runner_failure_e2e(config: RunnerFailureE2EConfig) -> dict[str, Any]:
    """Submit one validated DSL and read back Java's real terminal failure."""

    testcase = TestCaseDSL.model_validate_json(config.testcase_json)
    if testcase.project_id != config.project_id:
        raise ValueError("TestCase projectId must match STAGE20_PROJECT_ID")
    agent_run_id = new_identity("stage20-runner-failure-agent")
    sink = InMemoryTraceSink()
    recorder = TraceRecorder(sink)
    observations: list[dict[str, object]] = []

    async def observe_response(response: httpx.Response) -> None:
        observations.append(
            {
                "path": response.request.url.path,
                "status": response.status_code,
                "requestTraceId": response.request.headers.get("x-trace-id"),
                "responseTraceId": response.headers.get("x-trace-id"),
                "responseRequestId": response.headers.get("x-request-id"),
            }
        )

    async with httpx.AsyncClient(
        trust_env=False,
        event_hooks={"response": [observe_response]},
    ) as http_client:
        client = JavaApiOpsClient(
            http_client,
            base_url=config.base_url,
            timeout_seconds=5,
        )
        submission = await client.submit_testcase(
            project_id=config.project_id,
            testcase=testcase,
            token=config.token,
            trace_id=config.trace_id,
        )
        if len(submission.task_ids) != 1 or len(submission.run_ids) != 1:
            raise AssertionError("single failure E2E submit must return one task and run")
        task_id = submission.task_ids[0]
        run_id = submission.run_ids[0]
        _record_runner_reference(
            recorder,
            trace_id=config.trace_id,
            agent_run_id=agent_run_id,
            project_id=config.project_id,
            submission=submission,
            task_id=task_id,
            run_id=run_id,
            stage="SUBMIT_ACCEPTED",
        )
        progress = await client.wait_for_run_terminal(
            project_id=config.project_id,
            run_id=run_id,
            token=config.token,
            trace_id=config.trace_id,
            overall_deadline_seconds=config.readback_deadline_seconds,
        )
        if progress.task_id != task_id or progress.status != "ASSERTION_FAILED":
            raise AssertionError(
                "real Runner did not produce the expected ASSERTION_FAILED terminal state"
            )
        _record_runner_reference(
            recorder,
            trace_id=config.trace_id,
            agent_run_id=agent_run_id,
            project_id=config.project_id,
            submission=submission,
            task_id=task_id,
            run_id=run_id,
            stage="TERMINAL_OBSERVED",
            status=progress.status,
        )
        report = await client.get_test_report(
            project_id=config.project_id,
            run_id=run_id,
            token=config.token,
            trace_id=config.trace_id,
        )
        if (
            report.task_id != task_id
            or report.run_id != run_id
            or report.status != progress.status
            or report.summary.failure_type != "ASSERTION_MISMATCH"
        ):
            raise AssertionError("Java Report did not preserve terminal Runner failure facts")
        _record_runner_reference(
            recorder,
            trace_id=config.trace_id,
            agent_run_id=agent_run_id,
            project_id=config.project_id,
            submission=submission,
            task_id=task_id,
            run_id=run_id,
            stage="REPORT_READ",
            status=report.status,
        )

    references = [
        {
            "traceId": item["trace_id"],
            "agentRunId": item["agent_run_id"],
            "batchId": item["java_batch_id"],
            "taskId": item["java_task_id"],
            "runId": item["java_run_id"],
            "status": item["java_status"],
            "stage": item["reference_stage"],
        }
        for item in sink.records
        if item["record_type"] == "java_run_reference"
    ]
    return {
        "failureScenario": "ASSERTION_FAILED",
        "projectId": report.project_id,
        "taskId": report.task_id,
        "batchId": submission.batch_id,
        "runId": report.run_id,
        "reportId": report.report_id,
        "traceId": config.trace_id,
        "agentRunId": agent_run_id,
        "status": report.status,
        "failureType": report.summary.failure_type,
        "httpRequests": observations,
        "sse": {
            "terminalStatus": progress.status,
            "overallDeadlineSeconds": config.readback_deadline_seconds,
        },
        "report": {
            "projectId": report.project_id,
            "taskId": report.task_id,
            "runId": report.run_id,
            "reportId": report.report_id,
            "status": report.status,
            "failureType": report.summary.failure_type,
        },
        "traceReferences": references,
        "resubmitCount": 0,
        "rawFallbackUsed": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--generation-e2e", action="store_true")
    parser.add_argument("--final-e2e", action="store_true")
    parser.add_argument("--diagnosis-e2e", action="store_true")
    parser.add_argument("--runner-failure-e2e", action="store_true")
    parser.add_argument("--failure-probe", action="store_true")
    parser.add_argument("--base-url", default="http://127.0.0.1:8080")
    parser.add_argument("--project-id", type=int)
    parser.add_argument("--api-id")
    args = parser.parse_args()
    selected_modes = sum(
        bool(value)
        for value in (
            args.generation_e2e,
            args.final_e2e,
            args.diagnosis_e2e,
            args.runner_failure_e2e,
            args.failure_probe,
        )
    )
    if selected_modes > 1:
        parser.error("Stage 20 E2E modes are mutually exclusive")
    if args.generation_e2e:
        result = asyncio.run(run_generation_e2e(GenerationE2EConfig.from_environment()))
    elif args.final_e2e:
        result = asyncio.run(run_final_e2e(FinalE2EConfig.from_environment()))
    elif args.diagnosis_e2e:
        config = DiagnosisE2EConfig.from_environment()
        result = asyncio.run(run_diagnosis_e2e(config))
    elif args.runner_failure_e2e:
        result = asyncio.run(run_runner_failure_e2e(RunnerFailureE2EConfig.from_environment()))
    elif args.failure_probe:
        result = asyncio.run(run_failure_probe(DiagnosisE2EConfig.from_environment()))
    else:
        if args.project_id is None or args.api_id is None:
            parser.error("--project-id and --api-id are required in the default mode")
        result = asyncio.run(run(args))
    print(json.dumps(result, ensure_ascii=False, separators=(",", ":"), sort_keys=True))


if __name__ == "__main__":
    main()
