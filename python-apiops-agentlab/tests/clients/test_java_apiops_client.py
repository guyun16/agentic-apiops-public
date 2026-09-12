"""Deterministic tests for the Java API Ops outbound boundary."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest

from app.clients.java_apiops import (
    JavaApiOpsAuthenticationError,
    JavaApiOpsClient,
    JavaApiOpsClientError,
    JavaApiOpsHttpError,
    JavaApiOpsMalformedResponseError,
    JavaApiOpsResponseValidationError,
    JavaApiOpsServerError,
    JavaApiOpsTimeoutError,
    JavaApiOpsTransportError,
    JavaRunSummary,
)
from app.schemas.openapi_metadata import OpenApiMetadataDetail
from app.schemas.tool_call import ToolCall
from app.schemas.tool_result import ToolResult
from app.tools import ToolCatalog, ToolIntent, map_tool_intent

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
JAVA_CONTRACT_FIXTURES = (
    REPOSITORY_ROOT
    / "java-apiops-platform"
    / "apiops-web"
    / "src"
    / "test"
    / "resources"
    / "contracts"
)


def metadata_payload() -> dict[str, Any]:
    return {
        "apiId": "api-1",
        "apiDocId": "doc-1",
        "operationId": "getOrders",
        "method": "GET",
        "path": "/orders",
        "summary": "List orders",
        "description": "Returns orders",
        "tags": ["orders"],
        "servers": [{"url": "https://api.example"}],
        "security": [{"apiKeyAuth": []}],
        "deprecated": False,
        "parameters": [
            {
                "name": "limit",
                "location": "query",
                "required": False,
                "description": None,
                "schema": {"type": "integer"},
                "example": 10,
            }
        ],
        "requestSchemas": [
            {
                "required": True,
                "mediaType": "application/json",
                "schema": {"type": "object"},
            }
        ],
        "responseSchemas": [
            {
                "statusCode": "200",
                "description": "ok",
                "mediaType": "application/json",
                "schema": {"type": "object"},
            }
        ],
        "examples": [
            {
                "owner": {
                    "type": "RESPONSE_SCHEMA",
                    "parameterName": None,
                    "parameterLocation": None,
                    "mediaType": "application/json",
                    "statusCode": "200",
                },
                "exampleName": "success",
                "summary": None,
                "description": None,
                "value": {"id": 1},
            }
        ],
    }


def success_payload(data: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "success": True,
        "code": "00000",
        "message": "success",
        "data": metadata_payload() if data is None else data,
    }


def login_payload() -> dict[str, Any]:
    return {
        "success": True,
        "code": "00000",
        "message": "success",
        "data": {
            "userId": 8,
            "username": "stage21-safety41",
            "tokenType": "Bearer",
            "accessToken": "java-issued-token",
            "expiresAt": "2026-08-28T00:00:00Z",
        },
    }


async def execute(
    handler: Callable[[httpx.Request], Awaitable[httpx.Response]],
) -> OpenApiMetadataDetail:
    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http_client:
        client = JavaApiOpsClient(
            http_client,
            base_url="https://java.example.test/",
            timeout_seconds=2.5,
        )
        return await client.get_api_metadata(
            project_id=41,
            api_id="api-1",
            token="secret-token",
            trace_id="T500",
        )


@pytest.mark.anyio
async def test_2xx_validates_java_envelope_and_metadata() -> None:
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=success_payload())

    result = await execute(handler)

    assert result.api_id == "api-1"
    assert result.request_schemas[0].media_type == "application/json"
    assert result.parameters[0].example == 10
    assert len(requests) == 1
    request = requests[0]
    assert request.method == "GET"
    assert str(request.url) == "https://java.example.test/api/v1/projects/41/openapi/apis/api-1"
    assert request.headers["authorization"] == "Bearer secret-token"
    assert request.headers["x-trace-id"] == "T500"


@pytest.mark.anyio
async def test_login_uses_public_auth_boundary_and_returns_java_session() -> None:
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=login_payload())

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http_client:
        client = JavaApiOpsClient(
            http_client,
            base_url="https://java.example.test/",
            timeout_seconds=2.5,
        )
        session = await client.login(
            username="stage21-safety41",
            password="test-password",
        )

    assert session.user_id == 8
    assert session.username == "stage21-safety41"
    assert session.token_type == "Bearer"
    assert session.token == "java-issued-token"
    assert session.expires_at == datetime(2026, 8, 28, tzinfo=UTC)
    assert "java-issued-token" not in repr(session)
    assert len(requests) == 1
    request = requests[0]
    assert request.method == "POST"
    assert str(request.url) == "https://java.example.test/api/v1/auth/login"
    assert "authorization" not in request.headers
    assert json.loads(request.content) == {
        "username": "stage21-safety41",
        "password": "test-password",
    }


@pytest.mark.anyio
@pytest.mark.parametrize('expiry', ['not-a-date', '2026-09-06T00:00:00', ''])
async def test_login_rejects_unusable_expiry_without_token_disclosure(expiry) -> None:
    payload = login_payload()
    payload['data']['expiresAt'] = expiry
    async with httpx.AsyncClient(transport=httpx.MockTransport(
        lambda request: httpx.Response(200, json=payload)
    )) as http_client:
        client = JavaApiOpsClient(
            http_client, base_url='https://java.example.test', timeout_seconds=2.5
        )
        with pytest.raises(JavaApiOpsResponseValidationError) as error:
            await client.login(username='stage21-safety41', password='test-password')
    assert 'java-issued-token' not in str(error.value)


@pytest.mark.anyio
async def test_list_test_runs_validates_java_owned_summary_contract() -> None:
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "success": True,
                "code": "00000",
                "message": "success",
                "data": [
                    {
                        "runId": 9876,
                        "caseId": "stage21-initial-report:task",
                        "apiId": "stage21-initial-report",
                        "testCaseName": "Stage 21 initial TestReport",
                        "status": "ASSERTION_FAILED",
                        "failureType": "BUSINESS_ERROR",
                        "createdAt": "2026-08-29T00:00:00Z",
                        "startedAt": "2026-08-29T00:00:00Z",
                        "finishedAt": "2026-08-29T00:00:00Z",
                        "durationMs": 1,
                    }
                ],
            },
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http_client:
        client = JavaApiOpsClient(
            http_client,
            base_url="https://java.example.test",
            timeout_seconds=2.5,
        )
        summaries = await client.list_test_runs(
            project_id=41,
            token="java-issued-token",
            trace_id="trace:run-list",
        )

    assert summaries == (
        JavaRunSummary(
            run_id=9876,
            case_id="stage21-initial-report:task",
            api_id="stage21-initial-report",
        ),
    )
    assert summaries[0].run_id == 9876
    assert summaries[0].case_id == "stage21-initial-report:task"
    assert summaries[0].api_id == "stage21-initial-report"
    assert len(requests) == 1
    assert requests[0].method == "GET"
    assert str(requests[0].url) == "https://java.example.test/api/v1/projects/41/test-runs"
    assert requests[0].headers["authorization"] == "Bearer java-issued-token"
    assert requests[0].headers["x-trace-id"] == "trace:run-list"


@pytest.mark.anyio
async def test_find_latest_test_run_uses_exact_case_boundary_outside_list_window() -> None:
    requests: list[httpx.Request] = []
    case_id = "stage21-initial-report:older-case"

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "success": True,
                "code": "00000",
                "message": "success",
                "data": {
                    "runId": 7001,
                    "caseId": case_id,
                    "apiId": "stage21-initial-report",
                    "testCaseName": "Stable symbolic report",
                    "status": "ASSERTION_FAILED",
                    "failureType": "BUSINESS_ERROR",
                    "createdAt": "2026-08-29T00:00:00Z",
                    "startedAt": "2026-08-29T00:00:00Z",
                    "finishedAt": "2026-08-29T00:00:01Z",
                    "durationMs": 1000,
                },
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        result = await JavaApiOpsClient(
            http_client,
            base_url="https://java.example.test",
            timeout_seconds=2.5,
        ).find_latest_test_run(
            project_id=41,
            case_id=case_id,
            token="java-issued-token",
            trace_id="trace:case-lookup",
        )

    assert result == JavaRunSummary(
        run_id=7001,
        case_id=case_id,
        api_id="stage21-initial-report",
    )
    assert len(requests) == 1
    assert requests[0].url.path.endswith("/test-runs/latest-by-case")
    assert requests[0].url.params["caseId"] == case_id


@pytest.mark.anyio
async def test_find_latest_test_run_returns_none_for_missing_exact_case() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(
            200,
            json={"success": True, "code": "00000", "message": "success", "data": None},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        result = await JavaApiOpsClient(
            http_client,
            base_url="https://java.example.test",
            timeout_seconds=2.5,
        ).find_latest_test_run(
            project_id=41,
            case_id="stage21-initial-report:absent",
            token="java-issued-token",
            trace_id="trace:case-missing",
        )

    assert result is None


@pytest.mark.anyio
async def test_find_latest_test_run_falls_back_to_exhaustive_advancing_pages() -> None:
    paths: list[str] = []

    def summary(run_id: int, case_id: str) -> dict[str, object]:
        return {
            "runId": run_id,
            "caseId": case_id,
            "apiId": "stage21-initial-report",
            "testCaseName": case_id,
            "status": "ASSERTION_FAILED",
            "failureType": "BUSINESS_ERROR",
            "createdAt": "2026-08-29T00:00:00Z",
            "startedAt": "2026-08-29T00:00:00Z",
            "finishedAt": "2026-08-29T00:00:01Z",
            "durationMs": 1000,
        }

    async def handler(request: httpx.Request) -> httpx.Response:
        paths.append(str(request.url))
        if request.url.path.endswith("/latest-by-case"):
            return httpx.Response(404)
        before = request.url.params.get("beforeRunId")
        if before is None:
            page = [summary(run_id, f"unrelated-{run_id}") for run_id in range(300, 200, -1)]
        else:
            assert before == "201"
            page = [summary(200, "stage21-initial-report:older-case")]
        return httpx.Response(
            200,
            json={"success": True, "code": "00000", "message": "success", "data": page},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        result = await JavaApiOpsClient(
            http_client,
            base_url="https://java.example.test",
            timeout_seconds=2.5,
        ).find_latest_test_run(
            project_id=41,
            case_id="stage21-initial-report:older-case",
            token="java-issued-token",
            trace_id="trace:paged-case-lookup",
        )

    assert result is not None and result.run_id == 200
    assert len(paths) == 3
    assert "limit=100" in paths[1]
    assert "beforeRunId=201" in paths[2]


@pytest.mark.anyio
@pytest.mark.parametrize("api_id", [None, ""])
async def test_list_test_runs_rejects_missing_or_empty_api_id(api_id: str | None) -> None:
    summary = {
        "runId": 9876,
        "caseId": "stage21-initial-report:task",
        "apiId": "stage21-initial-report",
        "testCaseName": "Stage 21 initial TestReport",
        "status": "ASSERTION_FAILED",
        "failureType": "BUSINESS_ERROR",
        "createdAt": "2026-08-29T00:00:00Z",
        "startedAt": "2026-08-29T00:00:00Z",
        "finishedAt": "2026-08-29T00:00:00Z",
        "durationMs": 1,
    }
    if api_id is None:
        del summary["apiId"]
    else:
        summary["apiId"] = api_id

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "success": True,
                "code": "00000",
                "message": "success",
                "data": [summary],
            },
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http_client:
        client = JavaApiOpsClient(
            http_client,
            base_url="https://java.example.test",
            timeout_seconds=2.5,
        )
        with pytest.raises(JavaApiOpsResponseValidationError):
            await client.list_test_runs(
                project_id=41,
                token="java-issued-token",
                trace_id="trace:run-list",
            )


@pytest.mark.anyio
async def test_login_http_401_is_an_authentication_failure_without_body_leakage() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            401,
            json={"secret": "password-value", "message": "invalid credentials"},
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http_client:
        client = JavaApiOpsClient(
            http_client,
            base_url="https://java.example.test",
            timeout_seconds=2.5,
        )
        with pytest.raises(JavaApiOpsAuthenticationError) as error:
            await client.login(username="stage21-normal", password="password-value")

    assert error.value.status_code == 401
    assert "password-value" not in str(error.value)


@pytest.mark.anyio
async def test_4xx_is_a_stable_client_error_without_response_body() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            403,
            json={"secret": "response-token", "message": "forbidden"},
        )

    with pytest.raises(JavaApiOpsClientError) as error:
        await execute(handler)

    assert error.value.status_code == 403
    assert str(error.value) == "Java API Ops request returned HTTP 403"
    assert "response-token" not in str(error.value)


@pytest.mark.anyio
async def test_400_validation_response_is_distinct_from_transport_and_preserves_status() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400,
            json={
                "success": False,
                "code": "A0001",
                "message": "request parameter invalid",
                "data": None,
            },
        )

    with pytest.raises(JavaApiOpsClientError) as error:
        await execute(handler)

    assert error.value.status_code == 400
    assert not isinstance(error.value, JavaApiOpsTransportError)
    assert not isinstance(error.value, JavaApiOpsTimeoutError)
    assert "A0001" not in str(error.value)


@pytest.mark.anyio
async def test_5xx_is_a_stable_server_error() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"message": "temporary failure"})

    with pytest.raises(JavaApiOpsServerError) as error:
        await execute(handler)

    assert error.value.status_code == 503
    assert str(error.value) == "Java API Ops request returned HTTP 503"


@pytest.mark.anyio
async def test_timeout_is_distinct_from_transport_failure() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("secret-token timeout", request=request)

    with pytest.raises(JavaApiOpsTimeoutError) as error:
        await execute(handler)

    assert str(error.value) == "Java API Ops metadata request timed out"
    assert "secret-token" not in str(error.value)


@pytest.mark.anyio
async def test_transport_failure_is_distinct_from_timeout() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("secret-token connection failure", request=request)

    with pytest.raises(JavaApiOpsTransportError) as error:
        await execute(handler)

    assert str(error.value) == "Java API Ops metadata request failed during transport"
    assert "secret-token" not in str(error.value)


@pytest.mark.anyio
async def test_2xx_invalid_typed_response_is_not_an_http_error() -> None:
    invalid_data = metadata_payload()
    del invalid_data["apiId"]

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=success_payload(invalid_data))

    with pytest.raises(JavaApiOpsResponseValidationError) as error:
        await execute(handler)

    assert not isinstance(error.value, JavaApiOpsHttpError)


@pytest.mark.anyio
async def test_2xx_invalid_metadata_enum_is_rejected() -> None:
    invalid_data = metadata_payload()
    invalid_data["examples"][0]["owner"]["type"] = "UNKNOWN"

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=success_payload(invalid_data))

    with pytest.raises(JavaApiOpsResponseValidationError):
        await execute(handler)


@pytest.mark.anyio
async def test_2xx_malformed_json_has_its_own_error() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"not-json")

    with pytest.raises(JavaApiOpsMalformedResponseError):
        await execute(handler)


def gateway_call(project_id: str = "41") -> ToolCall:
    return map_tool_intent(
        ToolIntent(
            tool_name="rag.search",
            arguments={
                "nested": {"enabled": True, "nullable": None},
                "items": [1, 2.5, False, None],
            },
        ),
        catalog=ToolCatalog(),
        agent_run_id="run-contract-1",
        project_id=project_id,
        trace_id="trace-contract-1",
    )


def gateway_call_with_target(target_project_id: int) -> ToolCall:
    return map_tool_intent(
        ToolIntent(
            tool_name="rag.search",
            arguments={
                "query": "order timeout",
                "topK": 2,
                "targetProjectId": target_project_id,
            },
        ),
        catalog=ToolCatalog(),
        agent_run_id="run-target-1",
        project_id="41",
        trace_id="trace-target-1",
    )


def java_gateway_fixture(name: str) -> dict[str, Any]:
    return json.loads((JAVA_CONTRACT_FIXTURES / name).read_text(encoding="utf-8"))


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("fixture_name", "status", "tool_call_id"),
    (
        ("tool-result-success.json", "SUCCESS", "java-generated-call-1"),
        ("tool-result-forbidden.json", "FORBIDDEN", "java-generated-denied-1"),
    ),
)
async def test_gateway_consumes_real_java_serialization_fixture(
    fixture_name: str,
    status: str,
    tool_call_id: str,
) -> None:
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=java_gateway_fixture(fixture_name))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        client = JavaApiOpsClient(
            http_client,
            base_url="https://java.example.test",
            timeout_seconds=2,
        )
        result = await client.execute_tool_call(
            project_id=41,
            tool_call=gateway_call(),
            token="secret-token",
        )

    assert isinstance(result, ToolResult)
    assert result.status == status
    assert result.tool_call_id == tool_call_id
    assert len(requests) == 1
    body = json.loads(requests[0].content)
    assert body == gateway_call().model_dump(mode="json")
    assert "toolCallId" not in body
    assert "arguments" not in body
    assert body["params"]["nested"] == {"enabled": True, "nullable": None}
    assert requests[0].headers["x-trace-id"] == "trace-contract-1"


@pytest.mark.anyio
async def test_gateway_forwards_structured_target_project_without_rewriting_it() -> None:
    requests: list[httpx.Request] = []
    call = gateway_call_with_target(42)

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        payload = java_gateway_fixture("tool-result-success.json")
        payload["traceId"] = call.trace_id
        return httpx.Response(200, json=payload)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        client = JavaApiOpsClient(
            http_client,
            base_url="https://java.example.test",
            timeout_seconds=2,
        )
        result = await client.execute_tool_call(
            project_id=41,
            tool_call=call,
            token="secret-token",
        )

    assert result.status == "SUCCESS"
    body = json.loads(requests[0].content)
    assert body["projectId"] == "41"
    assert body["params"]["targetProjectId"] == 42
    assert "targetProjectId" not in body.get("arguments", {})


@pytest.mark.anyio
async def test_gateway_rejects_old_java_raw_envelope_as_invalid_shared_result() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "success": True,
                "status": "SUCCESS",
                "toolName": "rag.search",
                "toolCallId": "java-call-1",
                "code": "00000",
                "message": "success",
                "data": {},
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        client = JavaApiOpsClient(
            http_client,
            base_url="https://java.example.test",
            timeout_seconds=2,
        )
        with pytest.raises(JavaApiOpsResponseValidationError):
            await client.execute_tool_call(
                project_id=41,
                tool_call=gateway_call(),
                token="secret-token",
            )


@pytest.mark.anyio
async def test_trusted_project_mismatch_stops_before_http() -> None:
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(500)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        client = JavaApiOpsClient(
            http_client,
            base_url="https://java.example.test",
            timeout_seconds=2,
        )
        with pytest.raises(ValueError, match="projectId"):
            await client.execute_tool_call(
                project_id=41,
                tool_call=gateway_call("42"),
                token="secret-token",
            )

    assert calls == 0
