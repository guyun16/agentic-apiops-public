from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from app.guardrails.preflight import PreflightDecision
from app.tools.risk import ToolRisk
from app.tracing import (
    AgentRun,
    AgentStep,
    ApprovalFact,
    FailureDetail,
    Latency,
    ModelCall,
    ModelIdentity,
    ParentIdentity,
    PromptIdentity,
    ResumeFact,
    RetrievalFact,
    RetrievalReference,
    TokenUsage,
    ToolIntentRecord,
    ToolResultRecord,
    TraceEvent,
    TraceStatus,
    digest_payload,
)
from app.tracing.models import IdentityAuthority
from app.workflows.approval import ApprovalAction


def failed_validation_step() -> AgentStep:
    return AgentStep(
        trace_id="trace-1",
        agent_run_id="run-1",
        agent_step_id="step-validation-1",
        step_type="validation",
        event=TraceEvent.TERMINAL,
        status=TraceStatus.FAILED,
        failure=FailureDetail(
            failure_category="VALIDATION_FAILED",
            failure_code="SCHEMA_ERROR",
            message="candidate did not validate",
        ),
    )


def test_trace_models_are_strict_and_status_has_no_cancelled() -> None:
    run = AgentRun(trace_id="trace-1", agent_run_id="run-1", status=TraceStatus.RUNNING)

    assert run.sequence is None
    with pytest.raises(ValidationError):
        AgentRun(
            trace_id="trace-1",
            agent_run_id="run-1",
            status="CANCELLED",
        )
    with pytest.raises(ValidationError):
        AgentRun(
            trace_id="trace-1",
            agent_run_id="run-1",
            status=TraceStatus.RUNNING,
            unexpected=True,
        )


def test_python_owned_correlation_ids_are_explicit() -> None:
    call = ModelCall(
        trace_id="trace-1",
        agent_run_id="run-1",
        agent_step_id="step-generate-1",
        model_call_id="model-call-1",
        model_identity=ModelIdentity(provider="deepseek", model="deepseek-v4-flash"),
        prompt=PromptIdentity(name="testcase_generate", version="v1"),
        model_input=digest_payload("bounded prompt"),
        status=TraceStatus.RUNNING,
    )

    assert call.agent_run_id == "run-1"
    assert call.agent_step_id == "step-generate-1"
    assert call.model_call_id == "model-call-1"
    assert call.model_dump(mode="json")["model_input"]["summary"] == "bounded prompt"
    assert "raw_prompt" not in call.model_dump(mode="json")


def test_model_call_structured_identity_is_optional_but_typed() -> None:
    call = ModelCall(
        trace_id="trace-1",
        agent_run_id="run-1",
        agent_step_id="step-generate-1",
        model_call_id="model-call-1",
        model_identity=ModelIdentity(provider="qwen", model="qwen3.7-plus-2026-05-26"),
        prompt=PromptIdentity(name="diagnosis", version="v1"),
        model_input=digest_payload("bounded prompt"),
        structured_output_mode="JSON_SCHEMA",
        schema_name="diagnosis_report_v1",
        schema_digest="a" * 64,
        status=TraceStatus.RUNNING,
    )

    assert call.structured_output_mode == "JSON_SCHEMA"
    assert call.schema_name == "diagnosis_report_v1"
    assert call.schema_digest == "a" * 64

    with pytest.raises(ValidationError):
        ModelCall(
            trace_id="trace-1",
            agent_run_id="run-1",
            agent_step_id="step-generate-1",
            model_call_id="model-call-1",
            model_identity=ModelIdentity(provider="qwen", model="qwen"),
            prompt=PromptIdentity(name="diagnosis", version="v1"),
            model_input=digest_payload("bounded prompt"),
            structured_output_mode="JSON_SCHEMA",
            status=TraceStatus.RUNNING,
        )

    with pytest.raises(ValidationError):
        ModelCall(
            trace_id="trace-1",
            agent_run_id="run-1",
            agent_step_id="step-generate-1",
            model_call_id="model-call-1",
            model_identity=ModelIdentity(provider="qwen", model="qwen"),
            prompt=PromptIdentity(name="diagnosis", version="v1"),
            model_input=digest_payload("bounded prompt"),
            structured_output_mode="JSON_OBJECT",
            schema_name="wrong-for-object",
            status=TraceStatus.RUNNING,
        )


def test_java_tool_call_id_is_only_an_external_reference() -> None:
    without_java_id = ToolResultRecord(
        trace_id="trace-1",
        agent_run_id="run-1",
        tool_name="rag.search",
        status=TraceStatus.DENIED,
        failure=FailureDetail(failure_category="PREFLIGHT_DENIED", message="denied"),
        sanitized=True,
        truncated=False,
    )
    with_java_id = without_java_id.model_copy(
        update={"status": TraceStatus.SUCCESS, "failure": None, "java_tool_call_id": "java-1"}
    )

    assert without_java_id.java_tool_call_id is None
    assert with_java_id.tool_call_id == "java-1"
    assert "toolCallId" not in without_java_id.model_dump(mode="json")


def test_stage18_intent_id_is_the_trace_tool_identity() -> None:
    record = ToolIntentRecord(
        trace_id="trace-1",
        agent_run_id="run-1",
        tool_intent_id="stage18-intent-1",
        tool_name="rag.search",
        arguments_digest=digest_payload({"topK": 3, "query": "timeout"}),
        risk=ToolRisk.READ_ONLY_LOW,
        python_decision=PreflightDecision.ALLOW,
        status=TraceStatus.RUNNING,
    )

    assert record.intent_id == "stage18-intent-1"
    assert record.tool_intent_id == record.intent_id


def test_status_and_failure_category_are_separate() -> None:
    step = failed_validation_step()

    assert step.status is TraceStatus.FAILED
    assert step.failure is not None
    assert step.failure.failure_category == "VALIDATION_FAILED"
    with pytest.raises(ValidationError):
        AgentStep(
            trace_id="trace-1",
            agent_run_id="run-1",
            agent_step_id="step-1",
            step_type="validation",
            event=TraceEvent.TERMINAL,
            status=TraceStatus.FAILED,
        )


def test_successful_run_can_follow_an_earlier_failed_step() -> None:
    run = AgentRun(
        trace_id="trace-1",
        agent_run_id="run-1",
        event=TraceEvent.TERMINAL,
        status=TraceStatus.SUCCESS,
    )
    repaired = AgentStep(
        trace_id="trace-1",
        agent_run_id="run-1",
        agent_step_id="step-validation-2",
        step_type="validation",
        event=TraceEvent.TERMINAL,
        status=TraceStatus.SUCCESS,
    )

    assert failed_validation_step().status is TraceStatus.FAILED
    assert repaired.status is TraceStatus.SUCCESS
    assert run.status is TraceStatus.SUCCESS


def test_interrupt_resume_keeps_agent_run_identity() -> None:
    interrupted = AgentRun(
        trace_id="trace-1",
        agent_run_id="run-1",
        event=TraceEvent.INTERRUPT,
        status=TraceStatus.INTERRUPTED,
    )
    resumed = ResumeFact(
        trace_id="trace-1",
        agent_run_id="run-1",
        workflow_id="workflow-1",
        intent_id="intent-1",
        parent_identity=ParentIdentity(
            authority=IdentityAuthority.PYTHON,
            kind="interrupt",
            identity="sequence:2",
        ),
        status=TraceStatus.RUNNING,
    )

    assert interrupted.agent_run_id == resumed.agent_run_id
    assert resumed.event is TraceEvent.RESUME
    assert resumed.status is TraceStatus.RUNNING


def test_parent_and_timestamp_are_typed() -> None:
    timestamp = datetime.now(UTC)
    step = AgentStep(
        trace_id="trace-1",
        agent_run_id="run-1",
        agent_step_id="step-1",
        step_type="generation",
        parent_identity=ParentIdentity(
            authority=IdentityAuthority.PYTHON,
            kind="agent_run",
            identity="run-1",
        ),
        timestamp=timestamp,
        status=TraceStatus.RUNNING,
    )

    assert step.parent_identity is not None
    assert step.parent_identity.identity == "run-1"
    assert step.timestamp == timestamp


def test_approval_has_existing_correlation_and_no_parallel_approval_id() -> None:
    fingerprint = "a" * 64
    request = ApprovalFact(
        trace_id="trace-1",
        agent_run_id="run-1",
        workflow_id="workflow-1",
        intent_id="intent-1",
        tool_name="redis.read",
        arguments_fingerprint=fingerprint,
        status=TraceStatus.INTERRUPTED,
    )
    decision = ApprovalFact(
        trace_id="trace-1",
        agent_run_id="run-1",
        workflow_id="workflow-1",
        intent_id="intent-1",
        tool_name="redis.read",
        arguments_fingerprint=fingerprint,
        event=TraceEvent.DECISION,
        decision=ApprovalAction.APPROVE,
        status=TraceStatus.RUNNING,
    )

    assert request.intent_id == decision.intent_id
    with pytest.raises(ValidationError):
        ApprovalFact.model_validate(
            {
                **request.model_dump(),
                "approval_id": "approval-1",
            }
        )


def test_retrieval_reference_has_no_context_pack_id() -> None:
    fact = RetrievalFact(
        trace_id="trace-1",
        agent_run_id="run-1",
        retrieval_kind="RAG",
        reference=RetrievalReference(rag_query_id="ragq-1"),
        status=TraceStatus.SUCCESS,
    )

    assert fact.reference.rag_query_id == "ragq-1"
    with pytest.raises(ValidationError):
        RetrievalFact(
            trace_id="trace-1",
            agent_run_id="run-1",
            retrieval_kind="RAG",
            reference=RetrievalReference(rag_query_id="ragq-1"),
            context_pack_id="must-not-exist",
            status=TraceStatus.SUCCESS,
        )


def test_token_usage_and_latency_reject_invalid_values_and_keep_missing_none() -> None:
    assert TokenUsage().prompt_tokens is None
    assert TokenUsage().completion_tokens is None
    with pytest.raises(ValidationError):
        TokenUsage(prompt_tokens=-1)
    with pytest.raises(ValidationError):
        Latency(duration_ms=-0.1)
    with pytest.raises(ValidationError):
        Latency(
            started_at=datetime.now(UTC),
            finished_at=datetime.now(UTC) - timedelta(seconds=1),
        )
