"""End-to-end-in-process tests for the Stage 20.2 Python orchestration."""

from __future__ import annotations

import json

import httpx
import pytest

from app.agents.testcase_generator import TestCaseGenerator
from app.clients.java_apiops import JavaApiOpsClient
from app.tracing import InMemoryTraceSink, TraceRecorder
from app.workflows.generation_context import TestStrategy as Strategy
from app.workflows.stage20_execution import (
    GeneratedTestCaseNotValidatedError,
    RunnerReadbackPolicy,
    Stage20ExecutionWorkflow,
)


class SequenceLLM:
    def __init__(self, responses: list[str]) -> None:
        self.responses = responses.copy()

    async def complete(self, prompt: str) -> str:
        if not self.responses:
            raise AssertionError("unexpected model call")
        return self.responses.pop(0)


def metadata() -> dict[str, object]:
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
        "security": [],
        "deprecated": False,
        "parameters": [],
        "requestSchemas": [],
        "responseSchemas": [
            {
                "statusCode": "200",
                "description": "ok",
                "mediaType": "application/json",
                "schema": {"type": "array"},
            }
        ],
        "examples": [],
    }


def candidate(*, valid: bool = True) -> str:
    value: dict[str, object] = {
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
    if not valid:
        del value["steps"]
    return json.dumps(value)


def envelope(data: object) -> dict[str, object]:
    return {"success": True, "code": "00000", "message": "success", "data": data}


def terminal_progress() -> dict[str, object]:
    return {
        "projectId": 41,
        "taskId": 301,
        "runId": 701,
        "total": 1,
        "completed": 1,
        "running": 0,
        "success": 1,
        "assertionFailed": 0,
        "executionFailed": 0,
        "timeout": 0,
        "cancelled": 0,
        "status": "SUCCESS",
        "updatedAt": "2026-08-23T12:00:00Z",
    }


def report() -> dict[str, object]:
    return {
        "projectId": 41,
        "taskId": 301,
        "runId": 701,
        "reportId": "report:701",
        "status": "SUCCESS",
        "startedAt": "2026-08-23T11:59:58Z",
        "finishedAt": "2026-08-23T12:00:00Z",
        "summary": {
            "totalCases": 1,
            "totalSteps": 1,
            "totalAssertions": 1,
            "passedAssertions": 1,
            "failedAssertions": 0,
            "failureType": "NONE",
        },
        "cases": [
            {
                "caseId": "case-1",
                "status": "SUCCESS",
                "failureType": "NONE",
                "steps": [
                    {
                        "stepId": "step-1",
                        "status": "SUCCESS",
                        "failureType": "NONE",
                        "responseStatusCode": 200,
                        "durationMs": 12,
                        "assertionResults": [
                            {
                                "type": "STATUS_CODE",
                                "passed": True,
                                "expected": 200,
                                "actual": 200,
                                "message": "status assertion",
                            }
                        ],
                    }
                ],
            }
        ],
    }


@pytest.mark.anyio
async def test_full_chain_uses_public_boundaries_and_records_java_identity_references() -> None:
    paths: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        assert request.headers["authorization"] == "Bearer credential"
        assert request.headers["x-trace-id"] == "trace-20"
        if request.url.path.endswith("/openapi/apis/api-1"):
            return httpx.Response(200, json=envelope(metadata()))
        if request.url.path.endswith("/test-batches"):
            body = json.loads(request.content)
            assert len(body["testCases"]) == 1
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
        if request.url.path.endswith("/progress/events"):
            running = terminal_progress() | {
                "completed": 0,
                "running": 1,
                "success": 0,
                "status": "RUNNING",
            }
            stream = (
                f"event: progress\ndata: {json.dumps(running)}\n\n"
                f"event: terminal\ndata: {json.dumps(terminal_progress())}\n\n"
            )
            return httpx.Response(200, text=stream)
        if request.url.path.endswith("/report"):
            return httpx.Response(200, json=envelope(report()))
        raise AssertionError(f"unexpected boundary: {request.url.path}")

    sink = InMemoryTraceSink()
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        workflow = Stage20ExecutionWorkflow(
            JavaApiOpsClient(
                http_client,
                base_url="https://java.example.test",
                timeout_seconds=2,
            ),
            TestCaseGenerator(SequenceLLM([candidate()])),
            token_provider=lambda: "credential",
            trace_recorder=TraceRecorder(sink),
            readback_policy=RunnerReadbackPolicy(overall_deadline_seconds=5),
        )
        result = await workflow.execute(
            project_id=41,
            api_id="api-1",
            strategy=Strategy.HAPPY_PATH,
            trace_id="trace-20",
            agent_run_id="agent-run-20",
        )

    assert result.trace_id == "trace-20"
    assert result.agent_run_id == "agent-run-20"
    assert result.submission.run_ids == (701,)
    assert result.terminal_progress.status == "SUCCESS"
    assert result.report.run_id == 701
    assert paths == [
        "/api/v1/projects/41/openapi/apis/api-1",
        "/api/v1/projects/41/test-batches",
        "/api/v1/projects/41/test-runs/701/progress/events",
        "/api/v1/projects/41/test-runs/701/report",
    ]
    references = [item for item in sink.records if item["record_type"] == "java_run_reference"]
    assert [item["reference_stage"] for item in references] == [
        "SUBMIT_ACCEPTED",
        "TERMINAL_OBSERVED",
        "REPORT_READ",
    ]
    assert all(item["trace_id"] == "trace-20" for item in references)
    assert all(item["agent_run_id"] == "agent-run-20" for item in references)
    assert all(item["java_run_id"] == 701 for item in references)
    assert all("report" not in item for item in references)


@pytest.mark.anyio
async def test_rejected_stage16_candidate_never_reaches_submit() -> None:
    paths: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        if request.url.path.endswith("/openapi/apis/api-1"):
            return httpx.Response(200, json=envelope(metadata()))
        raise AssertionError("invalid DSL must not reach a Java execution boundary")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        workflow = Stage20ExecutionWorkflow(
            JavaApiOpsClient(
                http_client,
                base_url="https://java.example.test",
                timeout_seconds=2,
            ),
            TestCaseGenerator(SequenceLLM([candidate(valid=False), candidate(valid=False)])),
            token_provider=lambda: "credential",
        )
        with pytest.raises(GeneratedTestCaseNotValidatedError):
            await workflow.execute(
                project_id=41,
                api_id="api-1",
                strategy=Strategy.HAPPY_PATH,
            )

    assert paths == ["/api/v1/projects/41/openapi/apis/api-1"]
