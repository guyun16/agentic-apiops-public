"""Stage 18 section 1 tests for internal catalog and deterministic routing."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.schemas.tool_call import ToolCall
from app.schemas.tool_result import ToolResult
from app.tools import (
    DuplicateToolError,
    FakeToolGatewayAdapter,
    ToolAdapterUnavailableError,
    ToolCatalog,
    ToolContractMismatchError,
    ToolDescriptor,
    ToolIntent,
    ToolRouter,
    UnapprovedToolError,
    UnknownToolError,
    map_tool_intent,
)


def intent(name: str = "rag.search") -> ToolIntent:
    return ToolIntent(tool_name=name, arguments={"query": "order timeout", "topK": 2})


def tool_call(tool_name: str = "rag.search") -> ToolCall:
    return ToolCall.model_validate(
        {
            "schemaVersion": "0.2.0",
            "agentRunId": "run-1",
            "projectId": "41",
            "toolName": tool_name,
            "params": {"query": "order timeout", "topK": 2},
            "traceId": "trace-1",
        }
    )


def tool_result(status: str = "SUCCESS") -> ToolResult:
    return ToolResult.model_validate(
        {
            "schemaVersion": "0.1.0",
            "toolCallId": "fake-java-call-1",
            "status": status,
            "data": {"accepted": status == "SUCCESS"},
            "error": None if status == "SUCCESS" else {"code": status},
            "sanitized": True,
            "traceId": "trace-1",
        }
    )


def test_tool_intent_accepts_json_arguments_without_java_execution_identity() -> None:
    value = intent()

    assert value.tool_name == "rag.search"
    assert value.arguments == {"query": "order timeout", "topK": 2}
    assert "tool_call_id" not in type(value).model_fields
    assert "toolCallId" not in type(value).model_fields


def test_tool_intent_rejects_non_json_arguments() -> None:
    with pytest.raises(ValidationError):
        ToolIntent(tool_name="rag.search", arguments={"query": object()})


@pytest.mark.parametrize("call_id_key", ("toolCallId", "tool_call_id"))
def test_tool_intent_rejects_java_execution_identity_inside_arguments(
    call_id_key: str,
) -> None:
    with pytest.raises(ValidationError, match="must not contain a Java toolCallId"):
        ToolIntent(tool_name="rag.search", arguments={call_id_key: "caller-generated"})


@pytest.mark.parametrize(
    "authority_field",
    ("role", "permission", "datasource", "security_policy", "toolCallId", "tool_call_id"),
)
def test_tool_intent_rejects_authority_and_java_identity_as_top_level_fields(
    authority_field: str,
) -> None:
    with pytest.raises(ValidationError):
        ToolIntent.model_validate(
            {
                "tool_name": "rag.search",
                "arguments": {},
                authority_field: "untrusted",
            }
        )


def test_catalog_contains_only_current_production_executable_inventory() -> None:
    catalog = ToolCatalog()

    assert catalog.get("rag.search").name == "rag.search"
    assert catalog.get("redis.read").name == "redis.read"
    assert [item.name for item in catalog.list_descriptors()] == ["rag.search", "redis.read"]
    assert not catalog.contains("sql.read")
    assert not catalog.contains("mysql.raw")
    assert not catalog.contains("redis.raw")
    assert not catalog.contains("qdrant.raw")
    assert not catalog.contains("log.raw")


def test_catalog_unknown_shell_exec_fails_closed() -> None:
    with pytest.raises(UnknownToolError, match="unknown tool: shell.exec"):
        ToolCatalog().get("shell.exec")


def test_catalog_rejects_unapproved_tool_even_if_java_class_exists() -> None:
    with pytest.raises(UnapprovedToolError, match="sql.read"):
        ToolCatalog(
            [
                ToolDescriptor(
                    name="sql.read",
                    description="Not production executable",
                    contract_name="sql.read",
                )
            ]
        )


def test_catalog_rejects_duplicate_names_deterministically() -> None:
    descriptor = ToolCatalog().get("rag.search")

    with pytest.raises(DuplicateToolError, match="duplicate tool descriptor: rag.search"):
        ToolCatalog([descriptor, descriptor])


@pytest.mark.anyio
async def test_known_mapped_tool_routes_to_one_approved_adapter() -> None:
    adapter = FakeToolGatewayAdapter(tool_result())
    router = ToolRouter(ToolCatalog(), {"rag.search": adapter})
    value = intent()
    call = tool_call()

    result = await router.route(value, call)

    assert result == tool_result()
    assert adapter.calls == [call]


@pytest.mark.anyio
async def test_rag_target_project_is_validated_and_forwarded_unchanged() -> None:
    adapter = FakeToolGatewayAdapter(tool_result())
    router = ToolRouter(ToolCatalog(), {"rag.search": adapter})
    value = ToolIntent(
        tool_name="rag.search",
        arguments={"query": "order timeout", "topK": 2, "targetProjectId": 42},
    )
    call = map_tool_intent(
        value,
        catalog=ToolCatalog(),
        agent_run_id="run-target",
        project_id="41",
        trace_id="trace-target",
    )

    await router.route(value, call)

    assert adapter.calls[0].params == value.arguments
    assert adapter.calls[0].params["targetProjectId"] == 42


@pytest.mark.anyio
@pytest.mark.parametrize("target_project_id", ("42", 0, -1, True, None))
async def test_rag_target_project_rejects_invalid_values(
    target_project_id: object,
) -> None:
    adapter = FakeToolGatewayAdapter(tool_result())
    router = ToolRouter(ToolCatalog(), {"rag.search": adapter})
    value = ToolIntent(
        tool_name="rag.search",
        arguments={
            "query": "order timeout",
            "topK": 2,
            "targetProjectId": target_project_id,
        },
    )
    call = map_tool_intent(
        value,
        catalog=ToolCatalog(),
        agent_run_id="run-invalid-target",
        project_id="41",
        trace_id="trace-invalid-target",
    )

    with pytest.raises(ToolContractMismatchError, match="targetProjectId"):
        await router.route(value, call)

    assert adapter.calls == []


@pytest.mark.anyio
async def test_rag_target_project_rejects_unknown_scope_alias() -> None:
    adapter = FakeToolGatewayAdapter(tool_result())
    router = ToolRouter(ToolCatalog(), {"rag.search": adapter})
    value = ToolIntent(
        tool_name="rag.search",
        arguments={"query": "order timeout", "topK": 2, "target_project_id": 42},
    )
    call = map_tool_intent(
        value,
        catalog=ToolCatalog(),
        agent_run_id="run-alias",
        project_id="41",
        trace_id="trace-alias",
    )

    with pytest.raises(ToolContractMismatchError, match="target_project_id"):
        await router.route(value, call)

    assert adapter.calls == []


@pytest.mark.anyio
async def test_unknown_tool_fails_before_any_adapter_call() -> None:
    adapter = FakeToolGatewayAdapter(tool_result())
    router = ToolRouter(ToolCatalog(), {"rag.search": adapter})

    with pytest.raises(UnknownToolError, match="unknown tool: shell.exec"):
        await router.route(intent("shell.exec"), tool_call())

    assert adapter.calls == []


@pytest.mark.anyio
async def test_known_but_unmapped_tool_fails_closed() -> None:
    adapter = FakeToolGatewayAdapter(tool_result())
    router = ToolRouter(ToolCatalog(), {"rag.search": adapter})

    with pytest.raises(ToolAdapterUnavailableError, match="redis.read"):
        await router.route(
            ToolIntent(tool_name="redis.read", arguments={"keys": []}),
            ToolCall.model_validate(
                {
                    **tool_call("redis.read").model_dump(by_alias=True),
                    "params": {"keys": []},
                }
            ),
        )

    assert adapter.calls == []


@pytest.mark.anyio
@pytest.mark.parametrize("status", ("FORBIDDEN", "TIMEOUT", "FAILED"))
async def test_non_success_outcome_never_falls_back(status: str) -> None:
    selected = FakeToolGatewayAdapter(tool_result(status))
    alternate = FakeToolGatewayAdapter(tool_result())
    router = ToolRouter(
        ToolCatalog(),
        {
            "rag.search": selected,
            "redis.read": alternate,
        },
    )

    result = await router.route(intent(), tool_call())

    assert result.status == status
    assert len(selected.calls) == 1
    assert alternate.calls == []


@pytest.mark.anyio
async def test_same_inputs_route_deterministically() -> None:
    expected = ToolResult.model_validate(
        {
            **tool_result().model_dump(by_alias=True),
            "data": {"items": [1, 2]},
        }
    )
    adapter = FakeToolGatewayAdapter(expected)
    router = ToolRouter(ToolCatalog(), {"rag.search": adapter})
    value = intent()
    call = tool_call()

    first = await router.route(value, call)
    second = await router.route(value, call)

    assert first == second == expected
    assert adapter.calls == [call, call]


@pytest.mark.anyio
async def test_intent_and_shared_tool_call_must_match_before_gateway() -> None:
    adapter = FakeToolGatewayAdapter(tool_result())
    router = ToolRouter(ToolCatalog(), {"rag.search": adapter})

    with pytest.raises(ToolContractMismatchError, match="does not match"):
        await router.route(intent(), tool_call("redis.read"))

    assert adapter.calls == []


def test_mapper_is_the_only_arguments_to_params_and_name_translation() -> None:
    value = ToolIntent(
        tool_name="rag.search",
        arguments={
            "nested": {"enabled": True, "nullable": None},
            "items": [1, 2.5, False, None],
        },
    )

    call = map_tool_intent(
        value,
        catalog=ToolCatalog(),
        agent_run_id="run-1",
        project_id="41",
        trace_id="trace-1",
    )

    assert call.tool_name == "rag.search"
    assert call.params == value.arguments
    assert "toolCallId" not in call.model_dump(by_alias=True)
