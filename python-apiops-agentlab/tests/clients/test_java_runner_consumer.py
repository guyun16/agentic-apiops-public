"""Stage 20.2 tests for Java Runner and TestReport consumers."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from typing import Any

import httpx
import pytest

from app.clients import (
    JavaApiOpsAuthenticationError,
    JavaApiOpsAuthorizationError,
    JavaApiOpsConflictError,
    JavaApiOpsNotFoundError,
    JavaApiOpsResponseValidationError,
    JavaRunnerStatusQueryTimeoutError,
    JavaRunnerSubmitUncertainError,
)
from app.clients.java_apiops import JavaApiOpsClient
from app.schemas.testcase_dsl import TestCaseDSL as Dsl


def make_testcase() -> Dsl:
    return Dsl.model_validate(
        {
            "schemaVersion": "1.0.0",
            "caseId": "case-1",
            "projectId": 41,
            "apiId": "api-1",
            "name": "Get orders",
            "environment": {"baseUrl": "https://api.example", "variables": {}},
            "steps": [
                {
                    "stepId": "step-1",
                    "name": "Get orders",
                    "request": {"method": "GET", "path": "/orders"},
                    "assertions": [{"type": "STATUS_CODE", "expected": 200}],
                    "extractors": [],
                }
            ],
        }
    )


def envelope(data: object) -> dict[str, object]:
    return {"success": True, "code": "00000", "message": "success", "data": data}


def progress(status: str, *, completed: int) -> dict[str, object]:
    terminal = status not in {"PENDING", "RUNNING"}
    return {
        "projectId": 41,
        "taskId": 301,
        "runId": 701,
        "total": 1,
        "completed": completed,
        "running": 0 if terminal else 1,
        "success": 1 if status == "SUCCESS" else 0,
        "assertionFailed": 1 if status == "ASSERTION_FAILED" else 0,
        "executionFailed": 1 if status == "EXECUTION_FAILED" else 0,
        "timeout": 1 if status == "TIMEOUT" else 0,
        "cancelled": 1 if status == "CANCELLED" else 0,
        "status": status,
        "updatedAt": "2026-08-23T12:00:00Z",
    }


def report(status: str = "SUCCESS") -> dict[str, object]:
    failure = "ASSERTION_MISMATCH" if status == "ASSERTION_FAILED" else "NONE"
    passed = status == "SUCCESS"
    return {
        "projectId": 41,
        "taskId": 301,
        "runId": 701,
        "reportId": "report:701",
        "status": status,
        "startedAt": "2026-08-23T11:59:58Z",
        "finishedAt": "2026-08-23T12:00:00Z",
        "summary": {
            "totalCases": 1,
            "totalSteps": 1,
            "totalAssertions": 1,
            "passedAssertions": 1 if passed else 0,
            "failedAssertions": 0 if passed else 1,
            "failureType": failure,
        },
        "cases": [
            {
                "caseId": "case-1",
                "status": status,
                "failureType": failure,
                "steps": [
                    {
                        "stepId": "step-1",
                        "status": status,
                        "failureType": failure,
                        "responseStatusCode": 200,
                        "durationMs": 12,
                        "assertionResults": [
                            {
                                "type": "STATUS_CODE",
                                "passed": passed,
                                "expected": 200,
                                "actual": 200 if passed else 500,
                                "message": "status assertion",
                            }
                        ],
                    }
                ],
            }
        ],
    }


async def with_client(
    handler: Callable[[httpx.Request], Awaitable[httpx.Response]],
    action: Callable[[JavaApiOpsClient], Awaitable[Any]],
) -> Any:
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        client = JavaApiOpsClient(
            http_client,
            base_url="https://java.example.test",
            timeout_seconds=2,
        )
        return await action(client)


@pytest.mark.anyio
async def test_submit_preserves_java_authority_identity_and_trace_header() -> None:
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            202,
            json=envelope(
                {
                    "batchId": "123e4567-e89b-42d3-a456-426614174000",
                    "taskIds": [301],
                    "runIds": [701],
                }
            ),
        )

    result = await with_client(
        handler,
        lambda client: client.submit_testcase(
            project_id=41,
            testcase=make_testcase(),
            token="credential",
            trace_id="trace-stage20",
        ),
    )

    assert result.batch_id == "123e4567-e89b-42d3-a456-426614174000"
    assert result.task_ids == (301,)
    assert result.run_ids == (701,)
    assert len(requests) == 1
    assert requests[0].method == "POST"
    assert requests[0].headers["x-trace-id"] == "trace-stage20"
    assert json.loads(requests[0].content) == {
        "testCases": [make_testcase().model_dump(mode="json")]
    }


@pytest.mark.anyio
async def test_submit_timeout_is_uncertain_and_is_not_retried() -> None:
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise httpx.ReadTimeout("after dispatch", request=request)

    async def submit(client: JavaApiOpsClient) -> None:
        with pytest.raises(JavaRunnerSubmitUncertainError, match="uncertain"):
            await client.submit_testcase(
                project_id=41,
                testcase=make_testcase(),
                token="credential",
                trace_id="trace-stage20",
            )

    await with_client(handler, submit)
    assert calls == 1


@pytest.mark.anyio
@pytest.mark.parametrize("terminal", ["SUCCESS", "ASSERTION_FAILED", "TIMEOUT"])
async def test_status_stream_preserves_java_terminal_state(terminal: str) -> None:
    content = "\n\n".join(
        (
            f"event: progress\ndata: {json.dumps(progress('RUNNING', completed=0))}",
            f"event: terminal\ndata: {json.dumps(progress(terminal, completed=1))}",
        )
    )

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["accept"] == "text/event-stream"
        return httpx.Response(200, text=content)

    result = await with_client(
        handler,
        lambda client: client.wait_for_run_terminal(
            project_id=41,
            run_id=701,
            token="credential",
            trace_id="trace-stage20",
            overall_deadline_seconds=3,
        ),
    )

    assert result.status == terminal
    assert result.terminal is True


@pytest.mark.anyio
async def test_status_http_timeout_is_not_java_runner_timeout_state() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("status read", request=request)

    async def read_status(client: JavaApiOpsClient) -> None:
        with pytest.raises(JavaRunnerStatusQueryTimeoutError) as caught:
            await client.wait_for_run_terminal(
                project_id=41,
                run_id=701,
                token="credential",
                trace_id="trace-stage20",
                overall_deadline_seconds=3,
            )
        assert "Runner status TIMEOUT" not in str(caught.value)

    await with_client(handler, read_status)


@pytest.mark.anyio
async def test_report_readback_is_typed_and_preserves_assertion_failure() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=envelope(report("ASSERTION_FAILED")))

    result = await with_client(
        handler,
        lambda client: client.get_test_report(
            project_id=41,
            run_id=701,
            token="credential",
            trace_id="trace-stage20",
        ),
    )

    assert result.status == "ASSERTION_FAILED"
    assert result.report_id == "report:701"
    assert result.summary.failure_type == "ASSERTION_MISMATCH"
    assert result.cases[0].steps[0].assertion_results[0].passed is False


@pytest.mark.anyio
async def test_malformed_report_is_contract_failure() -> None:
    malformed = report()
    del malformed["summary"]

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=envelope(malformed))

    async def read_report(client: JavaApiOpsClient) -> None:
        with pytest.raises(JavaApiOpsResponseValidationError):
            await client.get_test_report(
                project_id=41,
                run_id=701,
                token="credential",
                trace_id="trace-stage20",
            )

    await with_client(handler, read_report)


@pytest.mark.anyio
@pytest.mark.parametrize(
    "field_update",
    [{"reportId": None}, {"reportId": 701}],
)
async def test_report_identity_is_strictly_required_and_typed(
    field_update: dict[str, object],
) -> None:
    malformed = report()
    malformed.update(field_update)

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=envelope(malformed))

    async def read_report(client: JavaApiOpsClient) -> None:
        with pytest.raises(JavaApiOpsResponseValidationError):
            await client.get_test_report(
                project_id=41,
                run_id=701,
                token="credential",
                trace_id="trace-stage20",
            )

    await with_client(handler, read_report)


@pytest.mark.anyio
async def test_report_identity_missing_is_contract_failure() -> None:
    malformed = report()
    del malformed["reportId"]

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=envelope(malformed))

    async def read_report(client: JavaApiOpsClient) -> None:
        with pytest.raises(JavaApiOpsResponseValidationError):
            await client.get_test_report(
                project_id=41,
                run_id=701,
                token="credential",
                trace_id="trace-stage20",
            )

    await with_client(handler, read_report)


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("status_code", "error_type"),
    [
        (401, JavaApiOpsAuthenticationError),
        (403, JavaApiOpsAuthorizationError),
        (404, JavaApiOpsNotFoundError),
        (409, JavaApiOpsConflictError),
    ],
)
async def test_relevant_http_errors_remain_distinct(
    status_code: int,
    error_type: type[Exception],
) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, json={"secret": "must-not-leak"})

    async def submit(client: JavaApiOpsClient) -> None:
        with pytest.raises(error_type) as caught:
            await client.submit_testcase(
                project_id=41,
                testcase=make_testcase(),
                token="credential",
                trace_id="trace-stage20",
            )
        assert "must-not-leak" not in str(caught.value)

    await with_client(handler, submit)
