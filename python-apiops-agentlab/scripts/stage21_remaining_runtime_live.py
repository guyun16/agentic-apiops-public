"""Accept the remaining Stage 21 runtime paths without calling an LLM.

RAG-only tasks are accepted by the Java test-owned public Tool Gateway
boundary.  Diagnosis recipes below exercise the existing Java Runner/SSE/
Report path.  E2E tasks are classified but deliberately not executed here:
their contract requires real Stage 16 generation and this acceptance run is
explicitly model-free.

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
from app.benchmark.models import BenchmarkTask, TaskType
from app.benchmark.stage21_rag_runtime_recipes import (
    STAGE21_RAG_RUNTIME_RECIPE_TASK_IDS,
)
from app.benchmark.stage21_runner_runtime_recipes import (
    STAGE21_RUNNER_RUNTIME_RECIPE_TASK_IDS,
    Stage21RunnerRuntimeRecipe,
    load_stage21_runner_runtime_recipes,
    resolve_stage21_runner_runtime_recipe,
)
from app.clients.java_apiops import JavaApiOpsClient
from app.workflows.stage20_execution import RunnerReadbackPolicy, Stage20ExecutionWorkflow

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = REPO_ROOT / "tests" / "benchmark" / "fixtures"
MANIFEST_PATH = FIXTURE_ROOT / "dataset-manifest.json"
ARTIFACT_ROOT = REPO_ROOT / "artifacts" / "stage21" / "remaining-runtime-live"

COMPLETED_REPORT_TASK_IDS = frozenset(
    {
        "bench_task_failure_assertion_mismatch",
        "bench_task_failure_assertion_contract_mismatch",
        "bench_task_failure_http_500",
        "bench_task_failure_business_inventory",
        "bench_task_failure_timeout",
        "bench_task_failure_transport_connect",
    }
)
REMAINING_TASK_COUNT = 28


class _NoModel:
    async def complete(self, prompt: str) -> str:
        del prompt
        raise AssertionError("remaining runtime acceptance must not call an LLM")


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _load_tasks() -> tuple[BenchmarkTask, ...]:
    manifest = load_dataset_manifest(MANIFEST_PATH)
    selected = tuple(
        entry
        for entry in manifest.tasks
        if entry.benchmark_task_id not in COMPLETED_REPORT_TASK_IDS
        and entry.benchmark_task_id
        in (
            STAGE21_RUNNER_RUNTIME_RECIPE_TASK_IDS
            | STAGE21_RAG_RUNTIME_RECIPE_TASK_IDS
            | {
                "bench_task_e2e_generation_business_failure",
                "bench_task_e2e_generation_runner_success",
                "bench_task_formal_e2e_generation_diagnosis_guarded",
                "bench_task_golden_e2e_apiops",
            }
        )
    )
    if len(selected) != REMAINING_TASK_COUNT:
        raise RuntimeError(
            f"expected {REMAINING_TASK_COUNT} remaining tasks, found {len(selected)}"
        )
    tasks = tuple(
        BenchmarkTask.model_validate_json(
            (MANIFEST_PATH.parent / entry.task_file).read_text(encoding="utf-8")
        )
        for entry in selected
    )
    if len({task.benchmark_task_id for task in tasks}) != REMAINING_TASK_COUNT:
        raise RuntimeError("remaining runtime task IDs are not unique")
    return tasks


def _initial_input_refs(task: BenchmarkTask) -> list[dict[str, object]]:
    refs: list[dict[str, object]] = []
    for entry in task.initial_state.entries:
        value: dict[str, object] = {"kind": entry.kind, "key": entry.key}
        if hasattr(entry, "ref"):
            value["ref"] = entry.ref
        elif hasattr(entry, "value"):
            value["value"] = entry.value
        refs.append(value)
    return refs


def _build_execution_path_matrix(tasks: tuple[BenchmarkTask, ...]) -> list[dict[str, object]]:
    sidecar = json.loads(
        (FIXTURE_ROOT / "stage21-execution-prerequisites.json").read_text(encoding="utf-8")
    )
    sidecar_rows = {
        row["benchmarkTaskId"]: row
        for row in sidecar["tasks"]
        if row["benchmarkTaskId"] not in COMPLETED_REPORT_TASK_IDS
        and row["resourceSetupType"] == "RUNTIME_RECIPE"
    }
    runner_recipes = load_stage21_runner_runtime_recipes()
    matrix: list[dict[str, object]] = []
    for task in tasks:
        row = sidecar_rows.get(task.benchmark_task_id)
        if row is None:
            raise RuntimeError(f"missing sidecar row for {task.benchmark_task_id}")
        operations = tuple(row["requiredOperations"])
        is_rag = task.task_type is TaskType.RAG_EVIDENCE_RETRIEVAL
        is_e2e = task.task_type is TaskType.E2E_APIOPS
        is_diagnosis = task.task_type is TaskType.FAILURE_DIAGNOSIS
        if is_rag:
            workflow = "Java Tool Gateway -> ResourceGuard -> RagRetriever"
            setup = "RAG_TEST_OWNED_DETERMINISTIC_PROVIDER"
            recipe_family = "RAG_SEARCH"
            live_status = "READY_TO_RUN"
        elif is_diagnosis:
            workflow = "Stage20ExecutionWorkflow -> Java Runner -> SSE -> Report API"
            setup = "CONTROLLED_TARGET_SERVICE"
            recipe_family = runner_recipes[task.benchmark_task_id].recipe_family
            live_status = "READY_TO_RUN"
        elif is_e2e:
            workflow = "Stage16 generation -> Stage20 Runner -> SSE -> Report/diagnosis"
            setup = "TASK_DECLARED_E2E_RUNTIME_TARGET"
            recipe_family = "E2E_GENERATE_AND_EXECUTE"
            live_status = "BLOCKED_REAL_MODEL_CALL_FORBIDDEN"
        else:
            raise RuntimeError(f"unclassified remaining runtime task: {task.benchmark_task_id}")
        matrix.append(
            {
                "benchmarkTaskId": task.benchmark_task_id,
                "category": task.task_type.value,
                "authProfile": row["authProfile"],
                "currentProjectId": row["currentProjectId"],
                "sourceInputReferences": _initial_input_refs(task),
                "requiresGeneration": is_e2e,
                "requiresRunner": is_e2e or "RUNNER_SUBMIT" in operations,
                "requiresReport": is_e2e or "READ_REPORT" in operations,
                "requiresRagTool": "RAG_SEARCH" in operations,
                "runtimeSetupTarget": setup,
                "recipeFamily": recipe_family,
                "existingWorkflow": workflow,
                "classificationStatus": "CLASSIFIED",
                "liveAcceptanceStatus": live_status,
            }
        )
    if len(matrix) != REMAINING_TASK_COUNT:
        raise RuntimeError("execution-path matrix does not contain 28 rows")
    return sorted(matrix, key=lambda row: str(row["benchmarkTaskId"]))


def _enum_value(value: object) -> str | None:
    raw = getattr(value, "value", value)
    return raw if isinstance(raw, str) else None


def _report_facts(report: object) -> dict[str, object]:
    steps: list[dict[str, object]] = []
    for case in report.cases:
        for step in case.steps:
            steps.append(
                {
                    "status": step.status,
                    "failureType": _enum_value(step.failure_type),
                    "responseStatusCode": step.response_status_code,
                    "assertionCount": len(step.assertion_results),
                }
            )
    return {
        "status": report.status,
        "summaryFailureType": _enum_value(report.summary.failure_type),
        "steps": steps,
    }


def _scenario_match(recipe: Stage21RunnerRuntimeRecipe, report: object) -> bool:
    kind = recipe.recipe_family
    summary_failure = _enum_value(report.summary.failure_type)
    steps = [step for case in report.cases for step in case.steps]
    response_codes = [step.response_status_code for step in steps]
    step_failures = [_enum_value(step.failure_type) for step in steps]
    if kind == "ASSERTION_EVALUATION_ERROR":
        return (
            report.status == "EXECUTION_FAILED"
            and summary_failure == "ASSERTION_EVALUATION_ERROR"
            and "ASSERTION_EVALUATION_ERROR" in step_failures
            and 200 in response_codes
        )
    if kind == "ASSERTION_MISMATCH":
        return (
            report.status == "ASSERTION_FAILED"
            and summary_failure == "ASSERTION_MISMATCH"
            and "ASSERTION_MISMATCH" in step_failures
            and 200 in response_codes
        )
    if kind == "HTTP_500_RESPONSE":
        return 500 in response_codes
    if kind == "BUSINESS_INVENTORY_CONFLICT":
        return 409 in response_codes
    if kind == "TIMEOUT":
        return report.status == "TIMEOUT" and summary_failure == "TIMEOUT"
    if kind == "TRANSPORT_CONNECT_FAILURE":
        return report.status == "EXECUTION_FAILED" and summary_failure == "CONNECT_ERROR"
    if kind == "TRANSPORT_DNS_FAILURE":
        return report.status == "EXECUTION_FAILED" and summary_failure in {
            "DNS_ERROR",
            "CONNECT_ERROR",
        }
    return False


async def _run() -> int:
    base_url = os.environ.get("JAVA_APIOPS_BASE_URL", "").strip()
    if not base_url:
        raise RuntimeError("JAVA_APIOPS_BASE_URL is required for live acceptance")
    tasks = _load_tasks()
    matrix = _build_execution_path_matrix(tasks)
    artifact_dir = ARTIFACT_ROOT / datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    artifact_dir.mkdir(parents=True, exist_ok=False)
    (artifact_dir / "execution-path-matrix.json").write_text(
        json.dumps(matrix, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    runner_tasks = tuple(
        task for task in tasks if task.benchmark_task_id in STAGE21_RUNNER_RUNTIME_RECIPE_TASK_IDS
    )
    results: list[dict[str, object]] = []
    async with httpx.AsyncClient(trust_env=False) as http_client:
        client = JavaApiOpsClient(http_client, base_url=base_url, timeout_seconds=15)
        resolver = AuthProfileResolver(client)
        workflows: dict[str, Stage20ExecutionWorkflow] = {}
        for task in runner_tasks:
            session = await resolver.resolve_for_task(task.benchmark_task_id)
            profile = session.auth_profile.value
            workflows.setdefault(
                profile,
                Stage20ExecutionWorkflow(
                    client,
                    TestCaseGenerator(_NoModel()),
                    token_provider=resolver.token_provider(session.auth_profile),
                    readback_policy=RunnerReadbackPolicy(overall_deadline_seconds=60),
                ),
            )
        for task in runner_tasks:
            recipe = resolve_stage21_runner_runtime_recipe(task)
            if recipe is None:
                raise RuntimeError(f"runner recipe missing for {task.benchmark_task_id}")
            session = await resolver.resolve_for_task(task.benchmark_task_id)
            item: dict[str, object] = {
                "taskId": task.benchmark_task_id,
                "category": task.task_type.value,
                "recipeFamily": recipe.recipe_family,
                "projectId": recipe.testcase.project_id,
                "runnerSubmitSuccess": False,
                "reportReadbackSuccess": False,
                "runId": None,
                "reportId": None,
                "scenarioMatch": False,
            }
            started = monotonic()
            try:
                execution = await workflows[
                    session.auth_profile.value
                ].execute_prepared_testcase(
                    project_id=recipe.testcase.project_id,
                    testcase=recipe.testcase,
                    trace_id=str(uuid4()),
                    agent_run_id=str(uuid4()),
                )
                item.update(
                    {
                        "runnerSubmitSuccess": True,
                        "javaTaskId": execution.submission.task_ids[0],
                        "javaBatchId": execution.submission.batch_id,
                        "runId": execution.terminal_progress.run_id,
                        "terminalStatus": execution.terminal_progress.status,
                        "reportReadbackSuccess": True,
                        "reportId": execution.report.report_id,
                        "reportStatus": execution.report.status,
                        "failureType": _enum_value(execution.report.summary.failure_type),
                        "reportFacts": _report_facts(execution.report),
                        "scenarioMatch": _scenario_match(recipe, execution.report),
                    }
                )
            except Exception as exc:  # noqa: BLE001 - keep per-task evidence visible
                item["failure"] = {"type": type(exc).__name__, "message": str(exc)}
            item["elapsedMs"] = round((monotonic() - started) * 1000, 1)
            results.append(item)
            print(json.dumps(item, ensure_ascii=False))

    runner_passed = sum(
        bool(item.get("runnerSubmitSuccess"))
        and bool(item.get("reportReadbackSuccess"))
        and bool(item.get("runId"))
        and bool(item.get("reportId"))
        and bool(item.get("scenarioMatch"))
        for item in results
        if "taskId" in item
    )
    record = {
        "schemaVersion": "stage21-remaining-runtime-live/v1",
        "executionMode": "REMAINING_RUNTIME_RECIPE_LIVE_ACCEPTANCE",
        "startedAt": _now(),
        "javaBaseUrl": base_url,
        "selectedTaskCount": REMAINING_TASK_COUNT,
        "matrixTaskCount": len(matrix),
        "ragOnlyTaskCount": len(STAGE21_RAG_RUNTIME_RECIPE_TASK_IDS),
        "runnerRecipeTaskCount": len(STAGE21_RUNNER_RUNTIME_RECIPE_TASK_IDS),
        "e2eTaskCount": sum(row["category"] == "E2E_APIOPS" for row in matrix),
        "runnerReadbackPassed": runner_passed,
        "runnerReadbackTotal": len(runner_tasks),
        "ragAcceptance": "RUN_BY_JAVA_TEST_HARNESS",
        "e2eAcceptance": "BLOCKED_REAL_MODEL_CALL_FORBIDDEN",
        "deepSeekCalled": False,
        "secretsPersisted": False,
        "finishedAt": _now(),
    }
    (artifact_dir / "runner-results.json").write_text(
        json.dumps(results, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    (artifact_dir / "run.json").write_text(
        json.dumps(record, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(json.dumps({"artifactDir": str(artifact_dir), **record}, ensure_ascii=False))
    return 0 if runner_passed == len(runner_tasks) else 1


if __name__ == "__main__":
    try:
        raise SystemExit(asyncio.run(_run()))
    except Exception as exc:  # noqa: BLE001 - stable acceptance failure
        print(
            json.dumps(
                {"status": "REMAINING_RUNTIME_RECIPE_LIVE_ACCEPTANCE_BLOCKED", "error": str(exc)},
                ensure_ascii=False,
            )
        )
        raise SystemExit(1)
