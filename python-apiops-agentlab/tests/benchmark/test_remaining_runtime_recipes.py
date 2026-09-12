"""Input-side recipes for the remaining Stage 21 runtime paths."""

from __future__ import annotations

from collections.abc import Mapping

import pytest

from app.benchmark import load_dataset
from app.benchmark.models import JavaResourceReference, LiteralSetup, TaskType
from app.benchmark.stage21_rag_runtime_recipes import (
    STAGE21_RAG_RUNTIME_RECIPE_TASK_IDS,
    load_stage21_rag_runtime_recipes,
    resolve_stage21_rag_runtime_recipe,
)
from app.benchmark.stage21_runner_runtime_recipes import (
    STAGE21_RUNNER_RUNTIME_RECIPE_TASK_IDS,
    Stage21RunnerRuntimeRecipeResolutionError,
    load_stage21_runner_runtime_recipes,
    resolve_stage21_runner_runtime_recipe,
)


def _tasks_by_id():
    return {task.benchmark_task_id: task for task in load_dataset().tasks}


def _assert_no_expected_side(value: object) -> None:
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
    if isinstance(value, Mapping):
        for key, nested in value.items():
            assert not (isinstance(key, str) and key.lower() in forbidden), key
            _assert_no_expected_side(nested)
    elif isinstance(value, list):
        for nested in value:
            _assert_no_expected_side(nested)


def _task_project_id(task) -> int:
    project_ids = tuple(
        entry.value
        for entry in task.initial_state.entries
        if isinstance(entry, LiteralSetup) and entry.key == "projectId"
    )
    assert len(project_ids) == 1
    project_id = project_ids[0]
    assert isinstance(project_id, int) and not isinstance(project_id, bool)
    return project_id


def _task_with_java_input_key(task, key: str):
    entries = tuple(
        entry.model_copy(update={"key": key})
        if isinstance(entry, JavaResourceReference)
        else entry
        for entry in task.initial_state.entries
    )
    return task.model_copy(
        update={"initial_state": task.initial_state.model_copy(update={"entries": entries})}
    )


def test_remaining_runner_recipes_resolve_all_registered_tasks_from_typed_input() -> None:
    tasks = _tasks_by_id()
    recipes = load_stage21_runner_runtime_recipes()

    assert set(recipes) == STAGE21_RUNNER_RUNTIME_RECIPE_TASK_IDS
    resolved = {
        task_id: resolve_stage21_runner_runtime_recipe(tasks[task_id])
        for task_id in STAGE21_RUNNER_RUNTIME_RECIPE_TASK_IDS
    }

    assert all(recipe is not None for recipe in resolved.values())
    assert all(
        recipe.testcase.project_id == _task_project_id(tasks[task_id])
        for task_id, recipe in resolved.items()
        if recipe
    )
    assert all(
        "runId" not in recipe.testcase.model_dump(mode="json")
        and "reportId" not in recipe.testcase.model_dump(mode="json")
        for recipe in resolved.values()
        if recipe
    )


def test_create_order_success_runner_recipe_reuses_task_scope_and_contract() -> None:
    tasks = _tasks_by_id()
    task = tasks["bench_task_e2e_generation_runner_success"]
    recipe = resolve_stage21_runner_runtime_recipe(task)

    assert recipe is not None
    assert task.task_type is TaskType.E2E_APIOPS
    assert recipe.source_reference == next(
        entry.ref
        for entry in task.initial_state.entries
        if isinstance(entry, JavaResourceReference) and entry.key == "runnerFixture"
    )
    assert recipe.testcase.project_id == _task_project_id(task)
    assert recipe.testcase.project_id == 1001
    assert recipe.testcase.api_id == "api_create_order"
    assert recipe.testcase.environment.base_url == "http://localhost:8080"

    step = recipe.testcase.steps[0]
    assert step.request.method == "POST"
    assert step.request.path == "/orders"
    assert step.request.body == {
        "userId": 1,
        "items": [{"productId": 1, "quantity": 1}],
    }
    assert [assertion.model_dump(mode="json") for assertion in step.assertions] == [
        {"type": "STATUS_CODE", "expected": 200},
        {
            "type": "HEADER",
            "name": "content-type",
            "operator": "CONTAINS",
            "expected": "application/json",
        },
        {
            "type": "JSON_PATH",
            "expression": "$.code",
            "operator": "EQUALS",
            "expected": "ORDER_SUCCESS",
        },
        {"type": "JSON_PATH", "expression": "$.data", "operator": "EXISTS"},
        {"type": "RESPONSE_TIME", "maxMs": 1000},
    ]


@pytest.mark.parametrize("task_type", [TaskType.E2E_APIOPS, TaskType.FAILURE_DIAGNOSIS])
def test_runner_recipe_input_key_is_task_type_aware(task_type: TaskType) -> None:
    tasks = _tasks_by_id()
    task = next(
        tasks[task_id]
        for task_id in STAGE21_RUNNER_RUNTIME_RECIPE_TASK_IDS
        if tasks[task_id].task_type is task_type
    )
    accepted_key = "runnerFixture" if task_type is TaskType.E2E_APIOPS else "authorityFixture"
    rejected_key = "authorityFixture" if accepted_key == "runnerFixture" else "runnerFixture"

    assert resolve_stage21_runner_runtime_recipe(
        _task_with_java_input_key(task, accepted_key)
    ) is not None
    with pytest.raises(Stage21RunnerRuntimeRecipeResolutionError) as error:
        resolve_stage21_runner_runtime_recipe(_task_with_java_input_key(task, rejected_key))
    assert error.value.code == "JAVA_RUNNER_RUNTIME_RECIPE_REFERENCE_INVALID"


def test_rag_recipes_resolve_every_required_task_from_authority_input() -> None:
    tasks = _tasks_by_id()
    recipes = load_stage21_rag_runtime_recipes()

    assert set(recipes) == STAGE21_RAG_RUNTIME_RECIPE_TASK_IDS
    resolved = {
        task_id: resolve_stage21_rag_runtime_recipe(tasks[task_id])
        for task_id in STAGE21_RAG_RUNTIME_RECIPE_TASK_IDS
    }

    assert all(recipe is not None for recipe in resolved.values())
    assert {recipe.source_reference for recipe in resolved.values() if recipe}
    assert recipes["bench_task_golden_e2e_apiops"].query == (
        "API contract and testcase design runbook"
    )
    assert recipes["bench_task_formal_failure_multi_evidence_report"].query == (
        "formal report plus unique index evidence"
    )
    assert recipes["bench_task_formal_failure_business_acceptable_alt"].query == (
        "formal business diagnosis alternative"
    )
    assert recipes["bench_task_formal_tool_cross_project_request"].top_k == 2


def test_remaining_recipe_catalogs_contain_no_expected_side_or_java_identity() -> None:
    for recipe in load_stage21_runner_runtime_recipes().values():
        _assert_no_expected_side(recipe.testcase.model_dump(mode="json"))
    for recipe in load_stage21_rag_runtime_recipes().values():
        _assert_no_expected_side(
            recipe.__dict__
            if hasattr(recipe, "__dict__")
            else {
                "benchmarkTaskId": recipe.benchmark_task_id,
                "sourceReference": recipe.source_reference,
                "query": recipe.query,
                "topK": recipe.top_k,
            }
        )


def test_remaining_recipe_task_sets_use_only_active_tasks_and_overlap_explicitly() -> None:
    tasks = set(_tasks_by_id())
    assert STAGE21_RUNNER_RUNTIME_RECIPE_TASK_IDS <= tasks
    assert STAGE21_RAG_RUNTIME_RECIPE_TASK_IDS <= tasks
    assert STAGE21_RUNNER_RUNTIME_RECIPE_TASK_IDS & STAGE21_RAG_RUNTIME_RECIPE_TASK_IDS == {
        "bench_task_formal_failure_business_acceptable_alt",
        "bench_task_formal_failure_http500_diagnosis_boundary",
        "bench_task_formal_failure_http500_payload",
        "bench_task_formal_failure_http500_transport_distinction",
        "bench_task_formal_failure_inventory_business",
    }
