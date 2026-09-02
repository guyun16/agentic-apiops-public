"""Strict Pydantic v2 view for the shared ToolResult contract."""

from __future__ import annotations

from typing import Any, Literal, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictStr

from .testcase_dsl import JsonValue

ToolResultStatus: TypeAlias = Literal[
    "SUCCESS",
    "FAILED",
    "FORBIDDEN",
    "TIMEOUT",
    "PARAM_INVALID",
    "RESULT_INVALID",
]


class _ToolResultModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        populate_by_name=False,
        strict=True,
    )

    def model_dump(self, **kwargs: Any) -> dict[str, Any]:
        kwargs.setdefault("by_alias", True)
        return super().model_dump(**kwargs)


class ToolResult(_ToolResultModel):
    """Typed result envelope with required nullable data and error fields."""

    schema_version: Literal["0.1.0"] = Field(alias="schemaVersion")
    tool_call_id: StrictStr = Field(alias="toolCallId", min_length=1)
    status: ToolResultStatus
    data: JsonValue
    error: dict[StrictStr, JsonValue] | None
    sanitized: StrictBool
    trace_id: StrictStr = Field(alias="traceId", min_length=1)
