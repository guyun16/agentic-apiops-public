"""Typed internal state and failures for the bounded Tool-use workflow."""

from __future__ import annotations

from enum import StrEnum
from typing import NotRequired, TypedDict

from pydantic import BaseModel, ConfigDict, StrictStr

from app.guardrails import PreflightDecision, UntrustedEvidence
from app.schemas.tool_call import ToolCall
from app.schemas.tool_result import ToolResult
from app.tools import ToolIntent, ToolRisk
from app.workflows.approval import ApprovalDecision, ApprovalRequest


class ToolUseStatus(StrEnum):
    PENDING = "PENDING"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    CONTINUE = "CONTINUE"
    FAILED = "FAILED"
    REJECTED = "REJECTED"
    LIMIT_EXCEEDED = "LIMIT_EXCEEDED"


class ToolFailureCode(StrEnum):
    PYTHON_PREFLIGHT_DENIED = "PYTHON_PREFLIGHT_DENIED"
    APPROVAL_REQUIRED = "APPROVAL_REQUIRED"
    APPROVAL_RESPONSE_INVALID = "APPROVAL_RESPONSE_INVALID"
    APPROVAL_ROUND_LIMIT_EXCEEDED = "APPROVAL_ROUND_LIMIT_EXCEEDED"
    HUMAN_REJECTED = "HUMAN_REJECTED"
    STALE_APPROVAL = "STALE_APPROVAL"
    WORKFLOW_IDENTITY_MISMATCH = "WORKFLOW_IDENTITY_MISMATCH"
    CONTRACT_OR_ROUTING_FAILURE = "CONTRACT_OR_ROUTING_FAILURE"
    JAVA_AUTHENTICATION_FAILED = "JAVA_AUTHENTICATION_FAILED"
    JAVA_AUTHORIZATION_DENIED = "JAVA_AUTHORIZATION_DENIED"
    JAVA_RESOURCE_NOT_FOUND = "JAVA_RESOURCE_NOT_FOUND"
    JAVA_EXECUTION_FAILED = "JAVA_EXECUTION_FAILED"
    JAVA_TIMEOUT = "JAVA_TIMEOUT"
    JAVA_TRANSPORT_UNAVAILABLE = "JAVA_TRANSPORT_UNAVAILABLE"
    INVALID_GATEWAY_RESULT = "INVALID_GATEWAY_RESULT"
    TOOL_CALL_LIMIT_EXCEEDED = "TOOL_CALL_LIMIT_EXCEEDED"


class ToolFailure(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    code: ToolFailureCode
    message: StrictStr


class ToolUseState(TypedDict):
    """One bounded Tool-use execution; it is not a shared public contract."""

    intent: ToolIntent
    tool_call: ToolCall
    tool_result: ToolResult | None
    status: ToolUseStatus
    failure: ToolFailure | None
    tool_calls_used: int
    result_sanitized: bool | None
    result_truncated: bool | None
    tool_risk: NotRequired[ToolRisk]
    preflight_decision: NotRequired[PreflightDecision]
    untrusted_evidence: NotRequired[tuple[UntrustedEvidence, ...]]
    workflow_id: NotRequired[str]
    project_id: NotRequired[str]
    intent_id: NotRequired[str]
    approval_request: NotRequired[ApprovalRequest | None]
    approval_decision: NotRequired[ApprovalDecision | None]
    approval_consumed: NotRequired[bool]
    approval_round: NotRequired[int]
    max_approval_rounds: NotRequired[int]
    trace_agent_step_id: NotRequired[str]


__all__ = [
    "ToolFailure",
    "ToolFailureCode",
    "ToolUseState",
    "ToolUseStatus",
]
