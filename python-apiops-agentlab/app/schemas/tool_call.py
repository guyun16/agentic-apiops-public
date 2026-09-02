"""Strict Pydantic v2 view for the shared ToolCall contract."""

from __future__ import annotations

from typing import Any, Literal, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, StrictStr
from pydantic.experimental.missing_sentinel import MISSING

from .testcase_dsl import JsonValue

ToolName: TypeAlias = Literal[
    "openapi.metadata.read",
    "testcase.validate",
    "runner.submit",
    "report.read",
    "sql.read",
    "redis.read",
    "log.search",
    "rag.search",
]


class _ToolCallModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        populate_by_name=False,
        strict=True,
    )

    def model_dump(self, **kwargs: Any) -> dict[str, Any]:
        kwargs.setdefault("by_alias", True)
        return super().model_dump(**kwargs)


class ToolCall(_ToolCallModel):
    """Canonical invocation request; Java assigns execution identity later."""

    schema_version: Literal["0.2.0"] = Field(alias="schemaVersion")
    agent_run_id: StrictStr = Field(alias="agentRunId", min_length=1)
    agent_step_id: StrictStr | MISSING = Field(
        default=MISSING,
        alias="agentStepId",
        min_length=1,
    )
    project_id: StrictStr = Field(alias="projectId", min_length=1)
    tool_name: ToolName = Field(alias="toolName")
    params: dict[StrictStr, JsonValue]
    trace_id: StrictStr = Field(alias="traceId", min_length=1)
