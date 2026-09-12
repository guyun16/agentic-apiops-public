from __future__ import annotations

import json

import httpx
import pytest

from app.agents.testcase_generator import TestCaseGenerator
from app.benchmark import LiteralSetup, load_golden_tasks, resolve_python_fixture
from app.clients.java_apiops import JavaApiOpsClient
from app.tracing import InMemoryTraceSink, TraceRecorder
from app.workflows.generation_context import TestStrategy
from app.workflows.stage20_execution import RunnerReadbackPolicy, Stage20ExecutionWorkflow
from tests.workflows.test_stage20_execution import (
    SequenceLLM,
    candidate,
    envelope,
    metadata,
    report,
    terminal_progress,
)


@pytest.mark.anyio
async def test_e2e_golden_initial_state_reuses_existing_stage20_workflow() -> None:
    task = next(
        task
        for task in load_golden_tasks()
        if task.benchmark_task_id == "bench_task_golden_e2e_apiops"
    )
    literals = {
        entry.key: entry.value
        for entry in task.initial_state.entries
        if isinstance(entry, LiteralSetup)
    }
    assert literals["projectId"] == 41
    assert resolve_python_fixture("examples/testcase-valid.json").is_file()
    assert any(entry.key == "apiMetadata" for entry in task.initial_state.entries)

    paths: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        if request.url.path.endswith("/openapi/apis/api-1"):
            return httpx.Response(200, json=envelope(metadata()))
        if request.url.path.endswith("/test-batches"):
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
            project_id=literals["projectId"],
            api_id="api-1",
            strategy=TestStrategy.HAPPY_PATH,
            trace_id="trace-stage21-e2e",
            agent_run_id="agent-run-stage21-e2e",
        )

    assert result.trace_id == "trace-stage21-e2e"
    assert result.agent_run_id == "agent-run-stage21-e2e"
    assert result.submission.run_ids == (701,)
    assert result.report.report_id == "report:701"
    assert paths == [
        "/api/v1/projects/41/openapi/apis/api-1",
        "/api/v1/projects/41/test-batches",
        "/api/v1/projects/41/test-runs/701/progress/events",
        "/api/v1/projects/41/test-runs/701/report",
    ]
