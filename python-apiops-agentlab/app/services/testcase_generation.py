"""Real Python TestCase generation over Java metadata and DeepSeek."""

from __future__ import annotations

from collections.abc import Mapping

import httpx
from pydantic import ValidationError

from app.agents.testcase_generator import Candidate, TestCaseGenerator
from app.clients.deepseek import DeepSeekError
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
    JavaApiOpsTransportError,
)
from app.clients.llm_provider import build_llm, provider_identity
from app.clients.qwen import QwenError
from app.core.errors import ApplicationError
from app.core.settings import AppSettings, get_settings
from app.schemas.testcase_dsl import TestCaseDSL
from app.schemas.testcase_generation_api import (
    TestCaseGenerationModelCall,
    TestCaseGenerationRequest,
    TestCaseGenerationResponse,
)
from app.services.runtime_evaluation import (
    RuntimeValidationFacts,
    runtime_evaluation_store,
)
from app.tracing import ModelCall, TraceEvent, TraceRecorder, create_trace_recorder, new_identity
from app.workflows.candidate_validation import CandidateValidationResult
from app.workflows.generation_context import build_generation_context
from app.workflows.state import (
    APIOpsAgentState,
    TestCaseGenerationStatus,
    WorkflowPhase,
)
from app.workflows.testcase_generation_graph import build_testcase_generation_graph


class TestCaseGenerationService:
    """Bind the existing LangGraph generator to one authenticated HTTP call."""

    async def generate(
        self,
        *,
        project_id: int,
        api_id: str,
        request: TestCaseGenerationRequest,
        token: str,
        trace_id: str,
        settings: AppSettings | None = None,
    ) -> TestCaseGenerationResponse:
        effective_settings = settings or get_settings()

        try:
            async with httpx.AsyncClient(trust_env=False) as http_client:
                java_client = JavaApiOpsClient(
                    http_client,
                    base_url=effective_settings.java_apiops_base_url,
                    timeout_seconds=effective_settings.java_apiops_timeout_seconds,
                )
                try:
                    metadata = await java_client.get_api_metadata(
                        project_id=project_id,
                        api_id=api_id,
                        token=token,
                        trace_id=trace_id,
                    )
                except JavaApiOpsError as exc:
                    raise self._map_java_error(exc) from exc

                try:
                    generation_context = build_generation_context(
                        metadata,
                        request.strategy,
                    )
                except ValueError as exc:
                    message = str(exc)
                    if "is not applicable" in message:
                        raise ApplicationError(
                            "STRATEGY_NOT_APPLICABLE",
                            "The selected strategy is not supported by this endpoint's "
                            "documented metadata.",
                            422,
                        ) from exc
                    raise ApplicationError(
                        "GENERATOR_REQUEST_INVALID",
                        "The generator request cannot be applied to this endpoint.",
                        422,
                    ) from exc
                except TypeError as exc:
                    raise ApplicationError(
                        "GENERATOR_REQUEST_INVALID",
                        "The generator request is invalid.",
                        422,
                    ) from exc

                llm = build_llm(
                    http_client,
                    settings=effective_settings,
                    provider=effective_settings.testcase_llm_provider,
                )
                configured_identity = provider_identity(
                    effective_settings,
                    effective_settings.testcase_llm_provider,
                )
                recorder = create_trace_recorder(effective_settings)
                graph = build_testcase_generation_graph(
                    TestCaseGenerator(llm),
                    trace_recorder=recorder,
                )
                initial_state = self._initial_state(
                    project_id=project_id,
                    api_id=api_id,
                    strategy=request.strategy.value,
                    trace_id=trace_id,
                    generation_context=generation_context,
                )
                agent_run_id = initial_state["agent_run_id"]
                if not isinstance(agent_run_id, str):
                    raise RuntimeError("generation workflow did not return an agent identity")
                runtime_evaluation_store.begin(
                    agent_run_id=agent_run_id,
                    trace_id=trace_id,
                    execution_type="TESTCASE_GENERATION",
                    provider=getattr(llm, "provider", configured_identity.provider),
                    model=getattr(llm, "model", configured_identity.model),
                    project_id=project_id,
                    api_id=api_id,
                    validation_applicable=True,
                )
                generated: object | None = None
                try:
                    generated = await graph.ainvoke(initial_state)
                    response = self._response(generated, recorder)
                except Exception as exc:
                    self._sync_runtime(
                        agent_run_id=agent_run_id,
                        recorder=recorder,
                        generated=generated,
                        status="FAILED",
                        failure_code=type(exc).__name__,
                    )
                    raise
                self._sync_runtime(
                    agent_run_id=agent_run_id,
                    recorder=recorder,
                    generated=generated,
                    status=self._runtime_status(generated),
                )
                return response
        except ApplicationError:
            raise
        except (DeepSeekError, QwenError, ValidationError, RuntimeError) as exc:
            raise ApplicationError(
                "GENERATOR_FAILED",
                "The Python TestCase generator failed.",
                502,
            ) from exc
        except Exception as exc:  # noqa: BLE001 - public boundary fails closed
            raise ApplicationError(
                "GENERATOR_FAILED",
                "The Python TestCase generator failed.",
                502,
            ) from exc

    @staticmethod
    def _initial_state(
        *,
        project_id: int,
        api_id: str,
        strategy: str,
        trace_id: str,
        generation_context: object,
    ) -> APIOpsAgentState:
        return {
            "trace_id": trace_id,
            "agent_run_id": new_identity("agent_run"),
            "phase": WorkflowPhase.INITIAL,
            "route": None,
            "error": None,
            "attempt_count": 0,
            "max_attempts": 0,
            "project_id": project_id,
            "api_id": api_id,
            "generation_intent": strategy,
            "api_metadata": None,
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

    @staticmethod
    def _response(
        generated: object,
        recorder: TraceRecorder,
    ) -> TestCaseGenerationResponse:
        if not isinstance(generated, Mapping):
            raise RuntimeError("generation workflow returned an invalid state")
        candidate = generated.get("candidate")
        validation = generated.get("validation_result")
        if (
            generated.get("generation_status") is not TestCaseGenerationStatus.ACCEPTED
            or not isinstance(candidate, Candidate)
            or not isinstance(validation, CandidateValidationResult)
            or not validation.valid
        ):
            raise RuntimeError("generation workflow did not return an accepted candidate")
        try:
            testcase = TestCaseDSL.model_validate(candidate.structured)
        except ValidationError as exc:
            raise RuntimeError("accepted candidate did not match Shared TestCase DSL") from exc

        agent_run_id = generated.get("agent_run_id")
        if not isinstance(agent_run_id, str) or not agent_run_id.strip():
            raise RuntimeError("generation workflow did not return an agent identity")
        model_calls = TestCaseGenerationService._model_calls(recorder)
        return TestCaseGenerationResponse(
            agentRunId=agent_run_id,
            promptName="testcase_generate",
            promptVersion="v1",
            modelCalls=model_calls,
            candidate=testcase.model_dump(mode="json"),
        )

    @staticmethod
    def _runtime_status(generated: object) -> str:
        if not isinstance(generated, Mapping):
            return "FAILED"
        phase = getattr(generated.get("phase"), "value", generated.get("phase"))
        generation_status = getattr(
            generated.get("generation_status"),
            "value",
            generated.get("generation_status"),
        )
        if phase == WorkflowPhase.FINISHED.value:
            return "COMPLETED"
        if generation_status == TestCaseGenerationStatus.REPAIR_EXHAUSTED.value:
            return "REJECTED"
        return "FAILED"

    @staticmethod
    def _runtime_validation(generated: object) -> RuntimeValidationFacts | None:
        if not isinstance(generated, Mapping):
            return None
        candidate = generated.get("candidate")
        validation = generated.get("validation_result")
        if not isinstance(validation, CandidateValidationResult):
            return None
        return RuntimeValidationFacts(
            valid_json=isinstance(candidate, Candidate),
            schema_valid=not any(issue.layer == "SCHEMA" for issue in validation.issues),
            contract_accepted=validation.valid,
        )

    @classmethod
    def _sync_runtime(
        cls,
        *,
        agent_run_id: str,
        recorder: TraceRecorder,
        generated: object | None,
        status: str,
        failure_code: str | None = None,
    ) -> None:
        runtime_evaluation_store.update(
            agent_run_id=agent_run_id,
            status=status,  # type: ignore[arg-type]
            trace_records=recorder.typed_records,
            validation=cls._runtime_validation(generated) if generated is not None else None,
            failure_code=failure_code,
            failure_message="TestCase generation failed." if failure_code else None,
        )

    @staticmethod
    def _model_calls(recorder: TraceRecorder) -> list[TestCaseGenerationModelCall]:
        calls: list[TestCaseGenerationModelCall] = []
        previous_call_id: str | None = None
        for record in recorder.typed_records:
            if not isinstance(record, ModelCall) or record.event is not TraceEvent.TERMINAL:
                continue
            calls.append(
                TestCaseGenerationModelCall(
                    modelCallId=record.model_call_id,
                    repairOfModelCallId=previous_call_id,
                )
            )
            previous_call_id = record.model_call_id
        if not calls or len(calls) > 2:
            raise RuntimeError("generation workflow did not record a bounded model call set")
        return calls

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


__all__ = ["TestCaseGenerationService"]
