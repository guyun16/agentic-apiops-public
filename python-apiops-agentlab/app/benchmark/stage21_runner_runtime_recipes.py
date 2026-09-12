"""Input-side Runner recipes for the remaining Stage 21 runtime tasks.

The recipes describe deterministic request inputs for the existing Java Runner.
They do not contain a report, a Java identity, or any Benchmark expected-side
data.  Java remains authoritative for submission, terminal state, and report
readback.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from json import JSONDecodeError
from pathlib import Path

from pydantic import ValidationError

from app.schemas.testcase_dsl import TestCaseDSL

from .golden import GOLDEN_FIXTURE_ROOT
from .models import BenchmarkTask, JavaResourceReference, LiteralSetup, TaskType

DEFAULT_STAGE21_RUNNER_RECIPE_PATH = (
    GOLDEN_FIXTURE_ROOT / "support" / "stage21-remaining-runner-recipes.json"
)

STAGE21_RUNNER_RUNTIME_RECIPE_TASK_IDS = frozenset(
    {
        "bench_task_formal_failure_assertion_contract",
        "bench_task_formal_failure_assertion_evidence_root",
        "bench_task_formal_failure_assertion_json_path",
        "bench_task_formal_failure_assertion_status",
        "bench_task_formal_failure_business_acceptable_alt",
        "bench_task_formal_failure_http500_diagnosis_boundary",
        "bench_task_formal_failure_http500_payload",
        "bench_task_formal_failure_http500_transport_distinction",
        "bench_task_formal_failure_inventory_business",
        "bench_task_formal_failure_timeout_deadline",
        "bench_task_formal_failure_timeout_partial_report",
        "bench_task_formal_failure_transport_connect",
        "bench_task_formal_failure_transport_dns",
        "bench_task_e2e_generation_runner_success",
        "bench_task_e2e_generation_business_failure",
    }
)

_RECIPE_FIELDS = frozenset(
    {
        "benchmarkTaskId",
        "sourceReference",
        "recipeFamily",
        "readbackDeadlineSeconds",
        "testCase",
    }
)
_ROOT_FIELDS = frozenset({"schemaVersion", "recipes"})
_FORBIDDEN_EXPECTED_KEYS = frozenset(
    {
        "groundtruth",
        "expectedtoolcalls",
        "expectedevidenceids",
        "expectedoutput",
        "tasksuccess",
        "expectedsafety",
        "runid",
        "reportid",
    }
)


class Stage21RunnerRuntimeRecipeResolutionError(ValueError):
    """A declared input-side Runner recipe cannot be resolved safely."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class Stage21RunnerRuntimeRecipe:
    """A validated Runner input and its task-side symbolic reference."""

    benchmark_task_id: str
    source_reference: str
    recipe_family: str
    readback_deadline_seconds: float
    testcase: TestCaseDSL


def is_stage21_runner_runtime_recipe_task(task: BenchmarkTask) -> bool:
    return task.benchmark_task_id in STAGE21_RUNNER_RUNTIME_RECIPE_TASK_IDS


def load_stage21_runner_runtime_recipes(
    path: Path = DEFAULT_STAGE21_RUNNER_RECIPE_PATH,
) -> dict[str, Stage21RunnerRuntimeRecipe]:
    """Load and strictly validate the Stage 21 Runner recipe catalog."""

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, JSONDecodeError) as exc:
        raise Stage21RunnerRuntimeRecipeResolutionError(
            "JAVA_RUNNER_RUNTIME_RECIPE_UNREADABLE",
            "Stage 21 Runner recipe catalog is not readable JSON",
        ) from exc
    if not isinstance(payload, dict) or set(payload) != _ROOT_FIELDS:
        raise Stage21RunnerRuntimeRecipeResolutionError(
            "JAVA_RUNNER_RUNTIME_RECIPE_INVALID",
            "Stage 21 Runner recipe catalog has an invalid root shape",
        )
    if payload.get("schemaVersion") != "stage21-runner-runtime-recipe/v1":
        raise Stage21RunnerRuntimeRecipeResolutionError(
            "JAVA_RUNNER_RUNTIME_RECIPE_INVALID",
            "Stage 21 Runner recipe catalog has an unsupported schema version",
        )
    rows = payload.get("recipes")
    if not isinstance(rows, list):
        raise Stage21RunnerRuntimeRecipeResolutionError(
            "JAVA_RUNNER_RUNTIME_RECIPE_INVALID",
            "Stage 21 Runner recipe catalog recipes must be an array",
        )

    recipes: dict[str, Stage21RunnerRuntimeRecipe] = {}
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise Stage21RunnerRuntimeRecipeResolutionError(
                "JAVA_RUNNER_RUNTIME_RECIPE_INVALID",
                f"Runner recipe row {index} has an invalid shape",
            )
        _reject_expected_side(row, location=f"recipe row {index}")
        if set(row) != _RECIPE_FIELDS:
            raise Stage21RunnerRuntimeRecipeResolutionError(
                "JAVA_RUNNER_RUNTIME_RECIPE_INVALID",
                f"Runner recipe row {index} has an invalid shape",
            )
        task_id = row.get("benchmarkTaskId")
        source_reference = row.get("sourceReference")
        recipe_family = row.get("recipeFamily")
        deadline = row.get("readbackDeadlineSeconds")
        if (
            not isinstance(task_id, str)
            or not task_id.strip()
            or not isinstance(source_reference, str)
            or not source_reference.strip()
            or not isinstance(recipe_family, str)
            or not recipe_family.strip()
            or isinstance(deadline, bool)
            or not isinstance(deadline, (int, float))
            or deadline <= 0
        ):
            raise Stage21RunnerRuntimeRecipeResolutionError(
                "JAVA_RUNNER_RUNTIME_RECIPE_INVALID",
                f"Runner recipe row {index} has invalid scalar fields",
            )
        if task_id not in STAGE21_RUNNER_RUNTIME_RECIPE_TASK_IDS or task_id in recipes:
            raise Stage21RunnerRuntimeRecipeResolutionError(
                "JAVA_RUNNER_RUNTIME_RECIPE_INVALID",
                f"Runner recipe task identity is invalid: {task_id}",
            )
        test_case_payload = row.get("testCase")
        _reject_expected_side(test_case_payload, location=f"recipe {task_id} testCase")
        try:
            testcase = TestCaseDSL.model_validate(test_case_payload)
        except ValidationError as exc:
            raise Stage21RunnerRuntimeRecipeResolutionError(
                "JAVA_RUNNER_RUNTIME_RECIPE_INVALID",
                f"Stage 21 Runner recipe DSL is invalid: {task_id}",
            ) from exc
        recipes[task_id] = Stage21RunnerRuntimeRecipe(
            benchmark_task_id=task_id,
            source_reference=source_reference,
            recipe_family=recipe_family,
            readback_deadline_seconds=float(deadline),
            testcase=testcase,
        )

    if set(recipes) != STAGE21_RUNNER_RUNTIME_RECIPE_TASK_IDS:
        raise Stage21RunnerRuntimeRecipeResolutionError(
            "JAVA_RUNNER_RUNTIME_RECIPE_INVALID",
            "Stage 21 Runner recipe catalog must contain exactly the registered tasks",
        )
    return recipes


def resolve_stage21_runner_runtime_recipe(
    task: BenchmarkTask,
    *,
    fixture_path: Path | None = None,
) -> Stage21RunnerRuntimeRecipe | None:
    """Resolve a task's typed Runner fixture to a Runner input recipe."""

    if not is_stage21_runner_runtime_recipe_task(task):
        return None
    expected_input_key = (
        "runnerFixture" if task.task_type is TaskType.E2E_APIOPS else "authorityFixture"
    )
    references = tuple(
        entry.ref
        for entry in task.initial_state.entries
        if isinstance(entry, JavaResourceReference)
        and entry.key == expected_input_key
    )
    if len(references) != 1:
        raise Stage21RunnerRuntimeRecipeResolutionError(
            "JAVA_RUNNER_RUNTIME_RECIPE_REFERENCE_INVALID",
            f"{task.benchmark_task_id} must declare exactly one {expected_input_key} reference",
        )
    source_reference = references[0]
    recipe = load_stage21_runner_runtime_recipes(
        fixture_path or DEFAULT_STAGE21_RUNNER_RECIPE_PATH
    ).get(task.benchmark_task_id)
    if recipe is None or recipe.source_reference != source_reference:
        raise Stage21RunnerRuntimeRecipeResolutionError(
            "JAVA_RUNNER_RUNTIME_RECIPE_REFERENCE_UNRESOLVED",
            f"no input-side Runner recipe matches {task.benchmark_task_id}",
        )
    project_id = _task_project_id(task)
    if project_id is None or recipe.testcase.project_id != project_id:
        raise Stage21RunnerRuntimeRecipeResolutionError(
            "JAVA_RUNNER_RUNTIME_RECIPE_PROJECT_MISMATCH",
            f"Runner recipe project does not match {task.benchmark_task_id}",
        )
    return recipe


def _task_project_id(task: BenchmarkTask) -> int | None:
    for entry in task.initial_state.entries:
        if isinstance(entry, LiteralSetup) and entry.key in {
            "projectId",
            "sourceProjectId",
        }:
            value = entry.value
            if isinstance(value, int) and not isinstance(value, bool) and value > 0:
                return value
    return None


def _reject_expected_side(value: object, *, location: str) -> None:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            if isinstance(key, str) and key.lower() in _FORBIDDEN_EXPECTED_KEYS:
                raise Stage21RunnerRuntimeRecipeResolutionError(
                    "JAVA_RUNNER_RUNTIME_RECIPE_EXPECTED_SIDE_LEAK",
                    f"expected-side key is not allowed in {location}",
                )
            _reject_expected_side(nested, location=location)
    elif isinstance(value, list):
        for nested in value:
            _reject_expected_side(nested, location=location)


__all__ = [
    "DEFAULT_STAGE21_RUNNER_RECIPE_PATH",
    "STAGE21_RUNNER_RUNTIME_RECIPE_TASK_IDS",
    "Stage21RunnerRuntimeRecipe",
    "Stage21RunnerRuntimeRecipeResolutionError",
    "is_stage21_runner_runtime_recipe_task",
    "load_stage21_runner_runtime_recipes",
    "resolve_stage21_runner_runtime_recipe",
]
