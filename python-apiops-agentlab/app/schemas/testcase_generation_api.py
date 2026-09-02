"""HTTP request and response models for the real Python generator boundary."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, StrictStr

from app.workflows.generation_context import TestStrategy


class TestCaseGenerationRequest(BaseModel):
    """The shared Java/Python generator request shape."""

    model_config = ConfigDict(
        extra="forbid",
        populate_by_name=False,
        strict=True,
    )

    strategy: TestStrategy = Field(
        default=TestStrategy.HAPPY_PATH,
        strict=False,
    )


class TestCaseGenerationModelCall(BaseModel):
    """Identity of one actual Python model call, matching Java's response."""

    model_config = ConfigDict(
        extra="forbid",
        populate_by_name=False,
        strict=True,
    )

    model_call_id: StrictStr = Field(alias="modelCallId", min_length=1)
    repair_of_model_call_id: StrictStr | None = Field(
        default=None,
        alias="repairOfModelCallId",
    )


class TestCaseGenerationResponse(BaseModel):
    """Accepted Shared TestCase DSL plus Java-compatible generation identities."""

    model_config = ConfigDict(
        extra="forbid",
        populate_by_name=False,
        strict=True,
    )

    agent_run_id: StrictStr = Field(alias="agentRunId", min_length=1)
    prompt_name: StrictStr = Field(alias="promptName", min_length=1)
    prompt_version: StrictStr = Field(alias="promptVersion", min_length=1)
    model_calls: list[TestCaseGenerationModelCall] = Field(
        alias="modelCalls",
        min_length=1,
        max_length=2,
    )
    candidate: dict[StrictStr, object]


__all__ = [
    "TestCaseGenerationModelCall",
    "TestCaseGenerationRequest",
    "TestCaseGenerationResponse",
]
