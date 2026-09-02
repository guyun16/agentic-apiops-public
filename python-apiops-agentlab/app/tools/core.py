"""Internal tool selection and routing boundaries for Python workflows.

These types are process-local orchestration models.  They are neither the
shared ToolCall/ToolResult contract nor Java Tool Gateway execution facts.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field, StrictStr, field_validator

from app.schemas.testcase_dsl import JsonValue
from app.schemas.tool_call import ToolCall, ToolName
from app.schemas.tool_result import ToolResult


class ToolIntent(BaseModel):
    """Validated model intent with no trusted authority or Java call identity."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    tool_name: StrictStr = Field(min_length=1)
    arguments: dict[StrictStr, JsonValue]

    @field_validator("arguments")
    @classmethod
    def arguments_must_not_claim_java_call_identity(
        cls,
        value: dict[str, JsonValue],
    ) -> dict[str, JsonValue]:
        if value.keys() & {"toolCallId", "tool_call_id"}:
            raise ValueError("arguments must not contain a Java toolCallId")
        return value


class ToolDescriptor(BaseModel):
    """Minimal consumer view of one currently approved Java tool."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    name: StrictStr = Field(min_length=1)
    description: StrictStr = Field(min_length=1)
    contract_name: ToolName


class ToolCatalogError(ValueError):
    """Base class for fail-closed consumer catalog errors."""


class DuplicateToolError(ToolCatalogError):
    """The static consumer catalog contains the same name more than once."""


class UnapprovedToolError(ToolCatalogError):
    """A descriptor is not in the frozen consumer-approved inventory."""


class UnknownToolError(ToolCatalogError):
    """The requested name is not visible in the consumer catalog."""


_APPROVED_DESCRIPTORS = (
    ToolDescriptor(
        name="rag.search",
        description="Search project-scoped diagnostic knowledge and return cited evidence",
        contract_name="rag.search",
    ),
    ToolDescriptor(
        name="redis.read",
        description="Read bounded Stage 9 task-progress evidence from Redis",
        contract_name="redis.read",
    ),
)
_APPROVED_BY_NAME = {descriptor.name: descriptor for descriptor in _APPROVED_DESCRIPTORS}
_RAG_ARGUMENTS = frozenset({"query", "topK", "targetProjectId"})
_RAG_MAX_QUERY_LENGTH = 4_096
_RAG_MAX_TOP_K = 20


def map_tool_intent(
    intent: ToolIntent,
    *,
    catalog: ToolCatalog,
    agent_run_id: str,
    project_id: str,
    trace_id: str,
    agent_step_id: str | None = None,
) -> ToolCall:
    """Map one internal intent to the sole public invocation request shape."""

    if not isinstance(intent, ToolIntent):
        raise TypeError("intent must be a ToolIntent")
    descriptor = catalog.get(intent.tool_name)
    payload = {
        "schemaVersion": "0.2.0",
        "agentRunId": agent_run_id,
        "projectId": project_id,
        "toolName": descriptor.contract_name,
        "params": intent.arguments,
        "traceId": trace_id,
    }
    if agent_step_id is not None:
        payload["agentStepId"] = agent_step_id
    return ToolCall.model_validate(payload)


class ToolCatalog:
    """Temporary static consumer view; Java ToolRegistry remains authoritative."""

    def __init__(self, descriptors: Iterable[ToolDescriptor] = _APPROVED_DESCRIPTORS) -> None:
        entries: dict[str, ToolDescriptor] = {}
        for descriptor in descriptors:
            if not isinstance(descriptor, ToolDescriptor):
                raise TypeError("descriptor must be a ToolDescriptor")
            if descriptor.name in entries:
                raise DuplicateToolError(f"duplicate tool descriptor: {descriptor.name}")
            if _APPROVED_BY_NAME.get(descriptor.name) != descriptor:
                raise UnapprovedToolError(f"tool is not consumer-approved: {descriptor.name}")
            entries[descriptor.name] = descriptor
        self._descriptors = entries

    def get(self, name: str) -> ToolDescriptor:
        try:
            return self._descriptors[name]
        except KeyError as exc:
            raise UnknownToolError(f"unknown tool: {name}") from exc

    def contains(self, name: str) -> bool:
        return name in self._descriptors

    def list_descriptors(self) -> tuple[ToolDescriptor, ...]:
        return tuple(self._descriptors[name] for name in sorted(self._descriptors))


class ToolContractMismatchError(ToolCatalogError):
    """Internal intent and shared ToolCall select different operations or arguments."""


class ToolGatewayTimeoutError(RuntimeError):
    """The approved Gateway boundary exceeded its timeout."""


class ToolGatewayAuthenticationError(RuntimeError):
    """Java rejected the credential used at the Tool Gateway boundary."""


class ToolGatewayAuthorizationError(RuntimeError):
    """Java denied the project-scoped Tool Gateway request."""


class ToolGatewayNotFoundError(RuntimeError):
    """Java could not find the project-scoped Tool Gateway resource."""


class ToolGatewayTransportError(RuntimeError):
    """The approved Gateway boundary was unavailable before returning a result."""


class InvalidGatewayResultError(RuntimeError):
    """A returned Gateway payload did not satisfy the shared ToolResult contract."""


@runtime_checkable
class ToolGatewayAdapter(Protocol):
    """Consume shared ToolCall and return shared ToolResult without granting authority."""

    async def execute(self, tool_call: ToolCall) -> ToolResult:
        """Execute one already catalog-approved shared ToolCall."""


class FakeToolGatewayAdapter:
    """Deterministic test adapter; it does not represent a Java execution."""

    def __init__(self, response: object) -> None:
        self._response = response
        self.calls: list[ToolCall] = []

    async def execute(self, tool_call: ToolCall) -> ToolResult:
        if not isinstance(tool_call, ToolCall):
            raise TypeError("tool_call must be a ToolCall")
        self.calls.append(tool_call)
        if isinstance(self._response, Exception):
            raise self._response
        try:
            return ToolResult.model_validate(self._response)
        except Exception as exc:
            raise InvalidGatewayResultError(
                "Gateway response did not match the shared ToolResult contract"
            ) from exc


class ToolAdapterUnavailableError(RuntimeError):
    """A known tool has no approved adapter mapping."""


class ToolRouter:
    """Deterministically route a known intent once, without fallback."""

    def __init__(
        self,
        catalog: ToolCatalog,
        adapters: Mapping[str, ToolGatewayAdapter],
    ) -> None:
        if not isinstance(catalog, ToolCatalog):
            raise TypeError("catalog must be a ToolCatalog")
        for name, adapter in adapters.items():
            if not catalog.contains(name):
                raise UnknownToolError(f"adapter mapped for unknown tool: {name}")
            if not isinstance(adapter, ToolGatewayAdapter):
                raise TypeError(f"adapter for {name} must implement ToolGatewayAdapter")
        self._catalog = catalog
        self._adapters = dict(adapters)

    def validate(self, intent: ToolIntent, tool_call: ToolCall) -> ToolDescriptor:
        """Validate selection and contract binding without calling an adapter."""

        if not isinstance(intent, ToolIntent):
            raise TypeError("intent must be a ToolIntent")
        if not isinstance(tool_call, ToolCall):
            raise TypeError("tool_call must be a ToolCall")
        descriptor = self._catalog.get(intent.tool_name)
        if descriptor.contract_name != tool_call.tool_name:
            raise ToolContractMismatchError(
                f"intent {descriptor.name} does not match ToolCall {tool_call.tool_name}"
            )
        if intent.arguments != tool_call.params:
            raise ToolContractMismatchError("intent arguments do not match ToolCall params")
        _validate_tool_arguments(descriptor, intent.arguments)
        return descriptor

    async def route(self, intent: ToolIntent, tool_call: ToolCall) -> ToolResult:
        descriptor = self.validate(intent, tool_call)
        adapter = self._adapters.get(descriptor.name)
        if adapter is None:
            raise ToolAdapterUnavailableError(
                f"approved adapter unavailable for tool: {descriptor.name}"
            )
        return await adapter.execute(tool_call)


def _validate_tool_arguments(
    descriptor: ToolDescriptor,
    arguments: Mapping[str, JsonValue],
) -> None:
    """Apply the small model-facing schema that is not expressible in ToolCall."""

    if descriptor.contract_name != "rag.search":
        return

    unknown = sorted(set(arguments) - _RAG_ARGUMENTS)
    if unknown:
        raise ToolContractMismatchError(f"rag.search has unknown argument: {unknown[0]}")

    query = arguments.get("query")
    if not isinstance(query, str) or not query.strip():
        raise ToolContractMismatchError("rag.search query must be a non-empty string")
    if len(query) > _RAG_MAX_QUERY_LENGTH:
        raise ToolContractMismatchError("rag.search query must not exceed 4096 characters")

    top_k = arguments.get("topK")
    if isinstance(top_k, bool) or not isinstance(top_k, int):
        raise ToolContractMismatchError("rag.search topK must be an integer")
    if not 1 <= top_k <= _RAG_MAX_TOP_K:
        raise ToolContractMismatchError("rag.search topK must be between 1 and 20")

    if "targetProjectId" in arguments:
        target_project_id = arguments["targetProjectId"]
        if (
            isinstance(target_project_id, bool)
            or not isinstance(target_project_id, int)
            or target_project_id < 1
        ):
            raise ToolContractMismatchError("rag.search targetProjectId must be a positive integer")


__all__ = [
    "DuplicateToolError",
    "FakeToolGatewayAdapter",
    "InvalidGatewayResultError",
    "map_tool_intent",
    "ToolAdapterUnavailableError",
    "ToolCatalog",
    "ToolCatalogError",
    "ToolDescriptor",
    "ToolContractMismatchError",
    "ToolGatewayAdapter",
    "ToolGatewayAuthenticationError",
    "ToolGatewayAuthorizationError",
    "ToolGatewayNotFoundError",
    "ToolGatewayTimeoutError",
    "ToolGatewayTransportError",
    "ToolIntent",
    "ToolRouter",
    "UnapprovedToolError",
    "UnknownToolError",
]
