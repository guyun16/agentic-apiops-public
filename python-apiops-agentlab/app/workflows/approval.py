"""Intent-bound, process-local human approval models."""

from __future__ import annotations

import hashlib
import json
from enum import StrEnum
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, StrictStr, model_validator

from app.schemas.testcase_dsl import JsonValue
from app.tools import ToolIntent


class ApprovalAction(StrEnum):
    APPROVE = "APPROVE"
    EDIT = "EDIT"
    REJECT = "REJECT"


class ApprovalRequest(BaseModel):
    """The exact workflow intent awaiting a one-shot human decision."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    workflow_id: StrictStr = Field(min_length=1)
    project_id: StrictStr = Field(min_length=1)
    intent_id: StrictStr = Field(min_length=1)
    tool_name: StrictStr = Field(min_length=1)
    arguments_fingerprint: StrictStr = Field(pattern=r"^[0-9a-f]{64}$")

    def matches(self, decision: ApprovalDecision) -> bool:
        return (
            self.workflow_id == decision.workflow_id
            and self.project_id == decision.project_id
            and self.intent_id == decision.intent_id
            and self.tool_name == decision.tool_name
            and self.arguments_fingerprint == decision.arguments_fingerprint
        )


class ApprovalDecision(ApprovalRequest):
    """One human response bound to one ApprovalRequest snapshot."""

    decision: ApprovalAction
    edited_arguments: dict[StrictStr, JsonValue] | None = None

    @model_validator(mode="after")
    def edit_payload_matches_action(self) -> ApprovalDecision:
        if self.decision is ApprovalAction.EDIT and self.edited_arguments is None:
            raise ValueError("EDIT requires edited_arguments")
        if self.decision is not ApprovalAction.EDIT and self.edited_arguments is not None:
            raise ValueError("edited_arguments is only valid for EDIT")
        return self


def fingerprint_arguments(arguments: dict[str, JsonValue]) -> str:
    """Hash canonical JSON; object key order does not affect the result."""

    canonical = json.dumps(
        arguments,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return hashlib.sha256(canonical).hexdigest()


def approval_request(
    *,
    workflow_id: str,
    project_id: str,
    intent_id: str,
    intent: ToolIntent,
) -> ApprovalRequest:
    return ApprovalRequest(
        workflow_id=workflow_id,
        project_id=project_id,
        intent_id=intent_id,
        tool_name=intent.tool_name,
        arguments_fingerprint=fingerprint_arguments(intent.arguments),
    )


def new_intent_id() -> str:
    """Create a process-local identity for a human-edited intent candidate."""

    return uuid4().hex


__all__ = [
    "ApprovalAction",
    "ApprovalDecision",
    "ApprovalRequest",
    "approval_request",
    "fingerprint_arguments",
    "new_intent_id",
]
