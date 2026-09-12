"""Run the six Stage 21 report recipes through the live Java Runner boundary.

This is an acceptance driver, not a second Runner.  It resolves only the
input-side task and recipe data, authenticates the frozen profile, and reuses
Stage20ExecutionWorkflow for submit, SSE terminal observation, and Report API
readback.  It deliberately does not call an LLM or inspect expected-side data.

The Stage21 runtime-world launcher owns the target services, including the
standalone timeout target on port 18082.
"""

from __future__ import annotations

import asyncio
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from time import monotonic
from uuid import uuid4

import httpx

from app.agents.testcase_generator import TestCaseGenerator
from app.benchmark.auth_profiles import AuthProfileResolver
from app.benchmark.dataset import load_dataset_manifest
from app.benchmark.models import BenchmarkTask
from app.benchmark.report_runtime_recipes import (
    REPORT_RUNTIME_RECIPE_TASK_IDS,
    ReportRuntimeRecipe,
    resolve_report_runtime_recipe,
)
from app.clients.java_apiops import JavaApiOpsClient
from app.workflows.stage20_execution import Stage20ExecutionWorkflow

REPO_ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = REPO_ROOT / "tests" / "benchmark" / "fixtures" / "dataset-manifest.json"
ARTIFACT_ROOT = REPO_ROOT / "artifacts" / "stage21" / "report-runtime-live-acceptance"


class _NoModel:
    async def complete(self, prompt: str) -> str:
        raise AssertionError("live report recipe acceptance must not call an LLM")


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _enum_value(value: object) -> str | None:
    raw = getattr(value, "value", value)
    return raw if isinstance(raw, str) else None


def _load_report_tasks() -> tuple[BenchmarkTask, ...]:
    manifest = load_dataset_manifest(MANIFEST_PATH)
    selected = [
        entry
        for entry in manifest.tasks
        if entry.benchmark_task_id in REPORT_RUNTIME_RECIPE_TASK_IDS
    ]
    if {entry.benchmark_task_id for entry in selected} != REPORT_RUNTIME_RECIPE_TASK_IDS:
        raise RuntimeError("report recipe acceptance did not find exactly six manifest tasks")
    tasks = tuple(
        BenchmarkTask.model_validate_json(
            (MANIFEST_PATH.parent / entry.task_file).read_text(encoding="utf-8")
        )
        for entry in selected
    )
    if {task.benchmark_task_id for task in tasks} != REPORT_RUNTIME_RECIPE_TASK_IDS:
        raise RuntimeError("report recipe acceptance task set does not match the six frozen IDs")
    return tasks


def _task_project_id(task: BenchmarkTask) -> int:
    for entry in task.initial_state.entries:
        if getattr(entry, "key", None) in {"projectId", "sourceProjectId"}:
            value = getattr(entry, "value", None)
            if isinstance(value, int) and not isinstance(value, bool) and value > 0:
                return value
    raise RuntimeError(f"{task.benchmark_task_id} has no input-side projectId")


def _report_facts(report: object) -> dict[str, object]:
    cases: list[dict[str, object]] = []
    for case in report.cases:
        steps: list[dict[str, object]] = []
        for step in case.steps:
            assertions: list[dict[str, object]] = []
            for assertion in step.assertion_results:
                actual = assertion.actual
                if isinstance(actual, (str, int, float, bool)) or actual is None:
                    safe_actual: object = actual
                else:
                    safe_actual = "NON_SCALAR"
                assertions.append(
                    {
                        "type": assertion.type,
                        "passed": assertion.passed,
                        "actual": safe_actual,
                    }
                )
            steps.append(
                {
                    "stepId": step.step_id,
                    "status": step.status,
                    "failureType": step.failure_type,
                    "responseStatusCode": step.response_status_code,
                    "durationMs": step.duration_ms,
                    "assertions": assertions,
                }
            )
        cases.append(
            {
                "caseId": case.case_id,
                "status": case.status,
                "failureType": case.failure_type,
                "steps": steps,
            }
        )
    return {
        "summaryFailureType": report.summary.failure_type,
        "cases": cases,
    }


def _scenario_match(recipe: ReportRuntimeRecipe, report: object) -> bool:
    kind = recipe.recipe_kind
    summary_failure = _enum_value(report.summary.failure_type)
    step_results = [step for case in report.cases for step in case.steps]
    response_codes = [step.response_status_code for step in step_results]
    step_failures = [_enum_value(step.failure_type) for step in step_results]
    if kind == "ASSERTION_MISMATCH":
        return (
            report.status == "ASSERTION_FAILED"
            and summary_failure == "ASSERTION_MISMATCH"
            and "ASSERTION_MISMATCH" in step_failures
            and 200 in response_codes
        )
    if kind == "ASSERTION_EVALUATION_ERROR":
        return (
            report.status == "EXECUTION_FAILED"
            and summary_failure == "ASSERTION_EVALUATION_ERROR"
            and "ASSERTION_EVALUATION_ERROR" in step_failures
            and 200 in response_codes
        )
    if kind == "HTTP_500_RESPONSE":
        return 500 in response_codes and "HTTP_STATUS_ERROR" not in step_failures
    if kind == "BUSINESS_INVENTORY_CONFLICT":
        return 409 in response_codes and any(
            assertion.get("actual") == "ORDER_BUSINESS_CONFLICT"
            for case in _report_facts(report)["cases"]
            for step in case["steps"]
            for assertion in step["assertions"]
        )
    if kind == "TIMEOUT":
        return report.status == "TIMEOUT" and summary_failure == "TIMEOUT"
    if kind == "TRANSPORT_CONNECT_FAILURE":
        return report.status == "EXECUTION_FAILED" and summary_failure == "CONNECT_ERROR"
    return False


def _recipe_projection(recipe: ReportRuntimeRecipe) -> dict[str, object]:
    return {
        "recipeKind": recipe.recipe_kind,
        "sourceReference": recipe.source_reference,
        "projectId": recipe.testcase.project_id,
        "targetBaseUrl": recipe.testcase.environment.base_url,
        "apiId": recipe.testcase.api_id,
    }


async def _run() -> int:
    base_url = os.environ.get("JAVA_APIOPS_BASE_URL", "").strip()
    if not base_url:
        raise RuntimeError("JAVA_APIOPS_BASE_URL is required for live acceptance")

    tasks = _load_report_tasks()
    started_at = _now()
    artifact_dir = ARTIFACT_ROOT / datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    artifact_dir.mkdir(parents=True, exist_ok=False)
    results: list[dict[str, object]] = []
    run_record: dict[str, object] = {
        "schemaVersion": "stage21-report-runtime-live/v1",
        "executionMode": "REPORT_RUNTIME_LIVE_ACCEPTANCE",
        "startedAt": started_at,
        "javaBaseUrl": base_url,
        "selectedTaskIds": [task.benchmark_task_id for task in tasks],
        "modelCalls": 0,
        "secretsPersisted": False,
    }

    async with httpx.AsyncClient(trust_env=False) as http_client:
        client = JavaApiOpsClient(http_client, base_url=base_url, timeout_seconds=15)
        resolver = AuthProfileResolver(client)
        workflow: Stage20ExecutionWorkflow | None = None
        try:
            first_session = await resolver.resolve_for_task(tasks[0].benchmark_task_id)
            workflow = Stage20ExecutionWorkflow(
                client,
                TestCaseGenerator(_NoModel()),
                token_provider=resolver.token_provider(first_session.auth_profile),
            )
            run_record["authProfile"] = first_session.auth_profile.value
            run_record["principalId"] = first_session.principal_id
            run_record["principalLabel"] = first_session.principal_label
        except Exception as exc:  # noqa: BLE001 - stable artifact, no secret
            run_record["setupFailure"] = {
                "type": type(exc).__name__,
                "message": str(exc),
            }
            run_record["finishedAt"] = _now()
            (artifact_dir / "run.json").write_text(
                json.dumps(run_record, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
            )
            (artifact_dir / "recipe-results.json").write_text("[]\n", encoding="utf-8")
            print(json.dumps(run_record, ensure_ascii=False))
            return 1

        assert workflow is not None
        for task in tasks:
            recipe: ReportRuntimeRecipe | None = None
            item: dict[str, object] = {
                "benchmarkTaskId": task.benchmark_task_id,
                "projectId": _task_project_id(task),
                "runnerSubmitSuccess": False,
                "reportReadbackSuccess": False,
                "runId": None,
                "reportId": None,
                "scenarioMatch": False,
            }
            started = monotonic()
            try:
                recipe = resolve_report_runtime_recipe(task)
                if recipe is None:
                    raise RuntimeError("report runtime recipe was not resolved")
                item.update(_recipe_projection(recipe))
                trace_id = str(uuid4())
                agent_run_id = str(uuid4())
                prepared = await workflow.execute_prepared_testcase(
                    project_id=recipe.testcase.project_id,
                    testcase=recipe.testcase,
                    trace_id=trace_id,
                    agent_run_id=agent_run_id,
                )
                item.update(
                    {
                        "traceId": prepared.trace_id,
                        "agentRunId": prepared.agent_run_id,
                        "javaTaskId": prepared.submission.task_ids[0],
                        "javaBatchId": prepared.submission.batch_id,
                        "runnerSubmitSuccess": True,
                        "runId": prepared.terminal_progress.run_id,
                        "terminalStatus": prepared.terminal_progress.status,
                        "reportReadbackSuccess": True,
                        "reportId": prepared.report.report_id,
                        "reportStatus": prepared.report.status,
                        "failureType": prepared.report.summary.failure_type,
                        "reportFacts": _report_facts(prepared.report),
                        "scenarioMatch": _scenario_match(recipe, prepared.report),
                    }
                )
            except Exception as exc:  # noqa: BLE001 - keep all six outcomes visible
                item["failure"] = {"type": type(exc).__name__, "message": str(exc)}
            item["elapsedMs"] = round((monotonic() - started) * 1000, 1)
            results.append(item)
            print(json.dumps(item, ensure_ascii=False))

    run_record.update(
        {
            "finishedAt": _now(),
            "completedTaskCount": len(results),
            "passedTaskCount": sum(
                bool(item.get("runnerSubmitSuccess"))
                and bool(item.get("reportReadbackSuccess"))
                and bool(item.get("scenarioMatch"))
                for item in results
            ),
            "allSixAccepted": len(results) == 6
            and all(
                bool(item.get("runnerSubmitSuccess"))
                and bool(item.get("reportReadbackSuccess"))
                and bool(item.get("runId"))
                and bool(item.get("reportId"))
                and bool(item.get("scenarioMatch"))
                for item in results
            ),
        }
    )
    (artifact_dir / "run.json").write_text(
        json.dumps(run_record, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    (artifact_dir / "recipe-results.json").write_text(
        json.dumps(results, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(json.dumps({"artifactDir": str(artifact_dir), **run_record}, ensure_ascii=False))
    return 0 if run_record["allSixAccepted"] else 1


if __name__ == "__main__":
    try:
        raise SystemExit(asyncio.run(_run()))
    except Exception as exc:  # noqa: BLE001 - no raw traceback in acceptance output
        print(
            json.dumps(
                {"status": "REPORT_RUNTIME_LIVE_ACCEPTANCE_BLOCKED", "error": str(exc)},
                ensure_ascii=False,
            )
        )
        raise SystemExit(1)
