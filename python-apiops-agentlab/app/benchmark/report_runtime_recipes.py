"""Input-side Runner recipes for the six Stage 21 report tasks.

These recipes are execution inputs, not reports.  They contain a validated
TestCase DSL that the existing Java Runner can execute.  Java remains the
authority for the submission, terminal state, and report identities.
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
from .models import BenchmarkTask, JavaResourceReference, LiteralSetup

DEFAULT_REPORT_RUNTIME_RECIPE_PATH = (
    GOLDEN_FIXTURE_ROOT / "support" / "stage21-report-runtime-recipes.json"
)

REPORT_RUNTIME_RECIPE_TASK_IDS = frozenset(
    {
        "bench_task_failure_assertion_mismatch",
        "bench_task_failure_assertion_contract_mismatch",
        "bench_task_failure_http_500",
        "bench_task_failure_business_inventory",
        "bench_task_failure_timeout",
        "bench_task_failure_transport_connect",
    }
)

_RECIPE_FIELDS = frozenset(
    {
        "benchmarkTaskId",
        "sourceReference",
        "recipeKind",
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
    }
)


class ReportRuntimeRecipeResolutionError(ValueError):
    """A declared report recipe cannot be safely resolved."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class ReportRuntimeRecipe:
    """A validated Runner input and its original task-side symbolic reference."""

    benchmark_task_id: str
    source_reference: str
    recipe_kind: str
    readback_deadline_seconds: float
    testcase: TestCaseDSL


def is_report_runtime_recipe_task(task: BenchmarkTask) -> bool:
    """Return true only for the six input-side report recipe tasks."""

    return task.benchmark_task_id in REPORT_RUNTIME_RECIPE_TASK_IDS


def load_report_runtime_recipes(
    path: Path = DEFAULT_REPORT_RUNTIME_RECIPE_PATH,
) -> dict[str, ReportRuntimeRecipe]:
    """Load and strictly validate the Stage 21 recipe catalog."""

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, JSONDecodeError) as exc:
        raise ReportRuntimeRecipeResolutionError(
            "JAVA_REPORT_RUNTIME_RECIPE_UNREADABLE",
            "Stage 21 report runtime recipe catalog is not readable JSON",
        ) from exc
    if not isinstance(payload, dict) or set(payload) != _ROOT_FIELDS:
        raise ReportRuntimeRecipeResolutionError(
            "JAVA_REPORT_RUNTIME_RECIPE_INVALID",
            "Stage 21 report runtime recipe catalog has an invalid root shape",
        )
    if payload.get("schemaVersion") != "stage21-report-runtime-recipe/v1":
        raise ReportRuntimeRecipeResolutionError(
            "JAVA_REPORT_RUNTIME_RECIPE_INVALID",
            "Stage 21 report runtime recipe catalog has an unsupported schema version",
        )
    rows = payload.get("recipes")
    if not isinstance(rows, list):
        raise ReportRuntimeRecipeResolutionError(
            "JAVA_REPORT_RUNTIME_RECIPE_INVALID",
            "Stage 21 report runtime recipe catalog recipes must be an array",
        )

    recipes: dict[str, ReportRuntimeRecipe] = {}
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise ReportRuntimeRecipeResolutionError(
                "JAVA_REPORT_RUNTIME_RECIPE_INVALID",
                f"Stage 21 report runtime recipe row {index} has an invalid shape",
            )
        _reject_expected_side(
            {key: value for key, value in row.items() if key != "testCase"},
            location=f"recipe row {index}",
        )
        if set(row) != _RECIPE_FIELDS:
            raise ReportRuntimeRecipeResolutionError(
                "JAVA_REPORT_RUNTIME_RECIPE_INVALID",
                f"Stage 21 report runtime recipe row {index} has an invalid shape",
            )
        task_id = row.get("benchmarkTaskId")
        source_reference = row.get("sourceReference")
        recipe_kind = row.get("recipeKind")
        deadline = row.get("readbackDeadlineSeconds")
        if (
            not isinstance(task_id, str)
            or not task_id.strip()
            or not isinstance(source_reference, str)
            or not source_reference.strip()
            or not isinstance(recipe_kind, str)
            or not recipe_kind.strip()
            or isinstance(deadline, bool)
            or not isinstance(deadline, (int, float))
            or deadline <= 0
        ):
            raise ReportRuntimeRecipeResolutionError(
                "JAVA_REPORT_RUNTIME_RECIPE_INVALID",
                f"Stage 21 report runtime recipe row {index} has invalid scalar fields",
            )
        if task_id not in REPORT_RUNTIME_RECIPE_TASK_IDS or task_id in recipes:
            raise ReportRuntimeRecipeResolutionError(
                "JAVA_REPORT_RUNTIME_RECIPE_INVALID",
                f"Stage 21 report runtime recipe task identity is invalid: {task_id}",
            )
        test_case_payload = row.get("testCase")
        _reject_expected_side(test_case_payload, location=f"recipe {task_id} testCase")
        try:
            testcase = TestCaseDSL.model_validate(test_case_payload)
        except ValidationError as exc:
            raise ReportRuntimeRecipeResolutionError(
                "JAVA_REPORT_RUNTIME_RECIPE_INVALID",
                f"Stage 21 report runtime recipe DSL is invalid: {task_id}",
            ) from exc
        recipes[task_id] = ReportRuntimeRecipe(
            benchmark_task_id=task_id,
            source_reference=source_reference,
            recipe_kind=recipe_kind,
            readback_deadline_seconds=float(deadline),
            testcase=testcase,
        )

    if set(recipes) != REPORT_RUNTIME_RECIPE_TASK_IDS:
        raise ReportRuntimeRecipeResolutionError(
            "JAVA_REPORT_RUNTIME_RECIPE_INVALID",
            "Stage 21 report runtime recipe catalog must contain exactly the six report tasks",
        )
    return recipes


def resolve_report_runtime_recipe(
    task: BenchmarkTask,
    *,
    fixture_path: Path | None = None,
) -> ReportRuntimeRecipe | None:
    """Resolve a task's symbolic report reference to an input-side Runner recipe.

    Only the task id, typed initial state, and the independent recipe catalog
    participate.  Expected-side fields are intentionally never read.
    """

    if not is_report_runtime_recipe_task(task):
        return None
    references = tuple(
        entry.ref
        for entry in task.initial_state.entries
        if isinstance(entry, JavaResourceReference) and entry.key == "testReport"
    )
    if len(references) != 1:
        raise ReportRuntimeRecipeResolutionError(
            "JAVA_REPORT_RUNTIME_RECIPE_REFERENCE_INVALID",
            f"{task.benchmark_task_id} must declare exactly one testReport reference",
        )
    source_reference = references[0]
    recipe = load_report_runtime_recipes(fixture_path or DEFAULT_REPORT_RUNTIME_RECIPE_PATH).get(
        task.benchmark_task_id
    )
    if recipe is None or recipe.source_reference != source_reference:
        raise ReportRuntimeRecipeResolutionError(
            "JAVA_REPORT_RUNTIME_RECIPE_REFERENCE_UNRESOLVED",
            f"no input-side Runner recipe matches {task.benchmark_task_id}",
        )
    project_id = _task_project_id(task)
    if project_id is None or recipe.testcase.project_id != project_id:
        raise ReportRuntimeRecipeResolutionError(
            "JAVA_REPORT_RUNTIME_RECIPE_PROJECT_MISMATCH",
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
                raise ReportRuntimeRecipeResolutionError(
                    "JAVA_REPORT_RUNTIME_RECIPE_EXPECTED_SIDE_LEAK",
                    f"expected-side key is not allowed in {location}",
                )
            _reject_expected_side(nested, location=location)
    elif isinstance(value, list):
        for nested in value:
            _reject_expected_side(nested, location=location)


__all__ = [
    "DEFAULT_REPORT_RUNTIME_RECIPE_PATH",
    "REPORT_RUNTIME_RECIPE_TASK_IDS",
    "ReportRuntimeRecipe",
    "ReportRuntimeRecipeResolutionError",
    "is_report_runtime_recipe_task",
    "load_report_runtime_recipes",
    "resolve_report_runtime_recipe",
]
