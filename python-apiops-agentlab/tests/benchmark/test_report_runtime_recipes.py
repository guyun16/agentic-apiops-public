"""Stage 21 report-task input recipes and public Runner readback tests."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping

import httpx
import pytest

from app.agents.testcase_generator import TestCaseGenerator
from app.benchmark import (
    DEFAULT_REPORT_RUNTIME_RECIPE_PATH,
    REPORT_RUNTIME_RECIPE_TASK_IDS,
    FixtureSetup,
    RealModelStage20WorkflowAdapter,
    ReportRuntimeRecipeResolutionError,
    load_dataset,
    load_report_runtime_recipes,
    resolve_report_runtime_recipe,
)
from app.clients.java_apiops import JavaApiOpsClient
from app.tracing import JavaRunReferenceFact
from app.workflows.stage20_execution import Stage20ExecutionWorkflow


def _task(task_id: str):
    return next(task for task in load_dataset().tasks if task.benchmark_task_id == task_id)


def _envelope(data: object) -> dict[str, object]:
    return {"success": True, "code": "00000", "message": "success", "data": data}


def _progress() -> dict[str, object]:
    return {
        "projectId": 1001,
        "taskId": 801,
        "runId": 1801,
        "total": 1,
        "completed": 1,
        "running": 0,
        "success": 0,
        "assertionFailed": 1,
        "executionFailed": 0,
        "timeout": 0,
        "cancelled": 0,
        "status": "ASSERTION_FAILED",
        "updatedAt": "2026-08-28T00:00:00Z",
    }


def _report() -> dict[str, object]:
    return {
        "projectId": 1001,
        "taskId": 801,
        "runId": 1801,
        "reportId": "report:stage21:1801",
        "status": "ASSERTION_FAILED",
        "startedAt": "2026-08-28T00:00:00Z",
        "finishedAt": "2026-08-28T00:00:01Z",
        "summary": {
            "totalCases": 1,
            "totalSteps": 1,
            "totalAssertions": 1,
            "passedAssertions": 0,
            "failedAssertions": 1,
            "failureType": "ASSERTION_MISMATCH",
        },
        "cases": [
            {
                "caseId": "stage21-case",
                "status": "ASSERTION_FAILED",
                "failureType": "ASSERTION_MISMATCH",
                "steps": [
                    {
                        "stepId": "stage21-step",
                        "status": "ASSERTION_FAILED",
                        "failureType": "ASSERTION_MISMATCH",
                        "responseStatusCode": 500,
                        "durationMs": 10,
                        "assertionResults": [
                            {
                                "type": "STATUS_CODE",
                                "passed": False,
                                "expected": 201,
                                "actual": 500,
                                "message": "status mismatch",
                            }
                        ],
                    }
                ],
            }
        ],
    }


def test_six_report_tasks_resolve_to_strict_input_recipes() -> None:
    recipes = load_report_runtime_recipes()
    assert set(recipes) == REPORT_RUNTIME_RECIPE_TASK_IDS

    resolved = {
        task_id: resolve_report_runtime_recipe(_task(task_id))
        for task_id in REPORT_RUNTIME_RECIPE_TASK_IDS
    }
    assert all(recipe is not None for recipe in resolved.values())
    assert {recipe.benchmark_task_id for recipe in resolved.values() if recipe} == set(
        REPORT_RUNTIME_RECIPE_TASK_IDS
    )
    assert all(recipe.testcase.project_id == 1001 for recipe in resolved.values() if recipe)
    assert all(
        "runId" not in recipe.testcase.model_dump(mode="json")
        and "reportId" not in recipe.testcase.model_dump(mode="json")
        for recipe in resolved.values()
        if recipe
    )


def test_recipe_resolution_reads_input_side_only() -> None:
    task = _task("bench_task_failure_assertion_mismatch")
    original = resolve_report_runtime_recipe(task)
    changed_expected = task.model_copy(
        update={
            "expected_output": {
                "failureType": "provider-controlled-value",
                "reportId": "must-not-be-read",
            }
        }
    )

    changed = resolve_report_runtime_recipe(changed_expected)

    assert original is not None
    assert changed == original


def test_recipe_catalog_rejects_expected_side_without_rejecting_dsl_assertions(
    tmp_path,
) -> None:
    source = load_report_runtime_recipes()
    payload = json.loads(DEFAULT_REPORT_RUNTIME_RECIPE_PATH.read_text(encoding="utf-8"))
    payload["recipes"][0]["expectedOutput"] = {"leak": True}
    path = tmp_path / "recipes.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ReportRuntimeRecipeResolutionError) as error:
        load_report_runtime_recipes(path)

    assert error.value.code == "JAVA_REPORT_RUNTIME_RECIPE_EXPECTED_SIDE_LEAK"
    assert source


@pytest.mark.anyio
async def test_prepared_recipe_uses_existing_submit_progress_report_boundaries() -> None:
    paths: list[str] = []
    submitted_case: dict[str, object] | None = None

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal submitted_case
        paths.append(request.url.path)
        if request.url.path.endswith("/test-batches"):
            submitted_case = json.loads(request.content)["testCases"][0]
            return httpx.Response(
                202,
                json=_envelope(
                    {
                        "batchId": "123e4567-e89b-42d3-a456-426614174000",
                        "taskIds": [801],
                        "runIds": [1801],
                    }
                ),
            )
        if request.url.path.endswith("/progress/events"):
            progress = _progress()
            return httpx.Response(
                200,
                text=f"event: terminal\ndata: {json.dumps(progress)}\n\n",
            )
        if request.url.path.endswith("/report"):
            return httpx.Response(200, json=_envelope(_report()))
        raise AssertionError(f"unexpected Java boundary: {request.url.path}")

    recipe = resolve_report_runtime_recipe(_task("bench_task_failure_assertion_mismatch"))
    assert recipe is not None
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        workflow = Stage20ExecutionWorkflow(
            JavaApiOpsClient(
                http_client,
                base_url="https://java.example.test",
                timeout_seconds=2,
            ),
            TestCaseGenerator(_NoCallLLM()),
            token_provider=lambda: "credential",
        )
        result = await workflow.execute_prepared_testcase(
            project_id=1001,
            testcase=recipe.testcase,
            trace_id="trace-stage21-recipe",
            agent_run_id="agent-stage21-recipe",
        )

    assert submitted_case == recipe.testcase.model_dump(mode="json")
    assert paths == [
        "/api/v1/projects/1001/test-batches",
        "/api/v1/projects/1001/test-runs/1801/progress/events",
        "/api/v1/projects/1001/test-runs/1801/report",
    ]
    assert result.submission.run_ids == (1801,)
    assert result.report.run_id == 1801
    assert result.report.report_id == "report:stage21:1801"


class _NoCallLLM:
    async def complete(self, prompt: str) -> str:
        del prompt
        raise AssertionError("the prepared report recipe must not call the model")


class _DiagnosisLLM:
    async def complete(self, prompt: str) -> str:
        del prompt
        return json.dumps(
            {
                "schemaVersion": "0.1.0",
                "reportId": "report:stage21:1801",
                "agentRunId": "agent-stage21-adapter",
                "projectId": 1001,
                "runId": 1801,
                "failureType": "ASSERTION_MISMATCH",
                "summary": "The Java report contains an assertion mismatch.",
                "rootCauseHypotheses": [
                    {
                        "statement": "The returned status did not satisfy the assertion.",
                        "confidence": "MEDIUM",
                        "evidenceRefs": [{"itemId": "report:stage21:1801"}],
                    }
                ],
                "sufficientEvidence": True,
                "limitations": [],
                "recommendedChecks": ["Inspect the failed assertion."],
                "traceId": "trace-stage21-adapter",
            }
        )


@pytest.mark.anyio
async def test_adapter_resolves_recipe_then_runs_diagnosis_from_java_report() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/test-batches"):
            return httpx.Response(
                202,
                json=_envelope(
                    {
                        "batchId": "123e4567-e89b-42d3-a456-426614174000",
                        "taskIds": [801],
                        "runIds": [1801],
                    }
                ),
            )
        if request.url.path.endswith("/progress/events"):
            return httpx.Response(
                200,
                text=f"event: terminal\ndata: {json.dumps(_progress())}\n\n",
            )
        if request.url.path.endswith("/report"):
            return httpx.Response(200, json=_envelope(_report()))
        raise AssertionError(f"unexpected Java boundary: {request.url.path}")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        adapter = RealModelStage20WorkflowAdapter(
            _DiagnosisLLM(),
            java_client=JavaApiOpsClient(
                http_client,
                base_url="https://java.example.test",
                timeout_seconds=2,
            ),
            token_provider=lambda: "credential",
        )
        outcome = await adapter.execute(
            _task("bench_task_failure_assertion_mismatch"),
            FixtureSetup(),
            trace_id="trace-stage21-adapter",
            agent_run_id="agent-stage21-adapter",
        )

    references = [
        record for record in outcome.trace_records if isinstance(record, JavaRunReferenceFact)
    ]
    assert outcome.run_id == 1801
    assert outcome.report_id == "report:stage21:1801"
    assert outcome.java_execution_status.value == "EXECUTED"
    assert [record.reference_stage for record in references] == [
        "SUBMIT_ACCEPTED",
        "TERMINAL_OBSERVED",
        "REPORT_READ",
    ]
    assert all(record.java_run_id == 1801 for record in references)


def test_recipe_task_without_java_boundary_fails_closed_before_fixture_report() -> None:
    task = _task("bench_task_failure_timeout")
    adapter = RealModelStage20WorkflowAdapter(_NoCallLLM())

    outcome = asyncio.run(
        adapter.execute(
            task,
            FixtureSetup(),
            trace_id="trace-stage21-no-java",
            agent_run_id="agent-stage21-no-java",
        )
    )

    assert outcome.java_execution_status.value == "REQUIRED_BUT_UNAVAILABLE"
    assert outcome.run_id is None
    assert outcome.report_id is None
    assert outcome.trace_records == ()


def test_recipe_payload_contains_no_expected_side_or_java_identity() -> None:
    forbidden = {
        "groundtruth",
        "expectedtoolcalls",
        "expectedevidenceids",
        "expectedoutput",
        "tasksuccess",
        "expectedsafety",
        "runid",
        "reportid",
    }

    def visit(value: object) -> None:
        if isinstance(value, Mapping):
            for key, nested in value.items():
                if isinstance(key, str) and key.lower() in forbidden:
                    raise AssertionError(key)
                visit(nested)
        elif isinstance(value, list):
            for nested in value:
                visit(nested)

    for recipe in load_report_runtime_recipes().values():
        visit(recipe.testcase.model_dump(mode="json"))
