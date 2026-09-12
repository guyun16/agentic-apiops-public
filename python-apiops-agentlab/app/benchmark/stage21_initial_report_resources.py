"""Input-side references for Java-owned Stage 21 initial TestReports.

These references identify the semantic setup slot only.  They intentionally
contain no runId or reportId.  The Java prerequisite setup creates the
authoritative report, and the benchmark resolves its current Java identity
through the public Runs/Report read boundary.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from json import JSONDecodeError
from pathlib import Path

from .golden import GOLDEN_FIXTURE_ROOT
from .models import BenchmarkTask, JavaResourceReference, LiteralSetup

DEFAULT_STAGE21_INITIAL_REPORT_RECIPE_PATH = (
    GOLDEN_FIXTURE_ROOT / "support" / "stage21-initial-report-recipes.json"
)

_ROOT_FIELDS = frozenset({"schemaVersion", "recipes"})
_RECIPE_FIELDS = frozenset({"resourceKey", "resourceType", "lifecycle", "caseId"})
_RESOURCE_KEY_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")

_REFERENCE_RE = re.compile(
    r"^java://test-report/project-(?P<project>[1-9][0-9]*)/"
    r"stage21-initial/(?P<resource>[a-z0-9]+(?:-[a-z0-9]+)*)$"
)


class Stage21InitialReportReferenceError(ValueError):
    """A Java initial TestReport reference cannot be resolved safely."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class Stage21InitialReportRecipe:
    """Approved semantic input recipe, independent of any Benchmark task ID."""

    resource_key: str
    resource_type: str
    lifecycle: str
    case_id: str


@dataclass(frozen=True, slots=True)
class Stage21InitialReportReference:
    """A symbolic initial-report slot and its Java setup case identity."""

    source_reference: str
    project_id: int
    resource_key: str
    case_id: str


def is_stage21_initial_report_task(task: BenchmarkTask) -> bool:
    """Return whether typed input declares the Stage 21 initial-report contract."""

    return any(
        isinstance(entry, JavaResourceReference)
        and entry.ref.startswith("java://test-report/")
        and "/stage21-initial/" in entry.ref
        for entry in task.initial_state.entries
    )


def load_stage21_initial_report_recipes(
    path: Path = DEFAULT_STAGE21_INITIAL_REPORT_RECIPE_PATH,
) -> dict[str, Stage21InitialReportRecipe]:
    """Load the approved input-side catalog without consulting expected-side data."""

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, JSONDecodeError) as exc:
        raise Stage21InitialReportReferenceError(
            "JAVA_INITIAL_REPORT_RECIPE_UNREADABLE",
            "Stage 21 initial TestReport recipe catalog is not readable JSON",
        ) from exc
    if not isinstance(payload, dict) or set(payload) != _ROOT_FIELDS:
        raise Stage21InitialReportReferenceError(
            "JAVA_INITIAL_REPORT_RECIPE_INVALID",
            "Stage 21 initial TestReport recipe catalog has an invalid root shape",
        )
    if payload.get("schemaVersion") != "stage21-initial-report-recipe/v1":
        raise Stage21InitialReportReferenceError(
            "JAVA_INITIAL_REPORT_RECIPE_INVALID",
            "Stage 21 initial TestReport recipe catalog has an unsupported schema version",
        )
    rows = payload.get("recipes")
    if not isinstance(rows, list) or not rows:
        raise Stage21InitialReportReferenceError(
            "JAVA_INITIAL_REPORT_RECIPE_INVALID",
            "Stage 21 initial TestReport recipe catalog must contain recipes",
        )

    recipes: dict[str, Stage21InitialReportRecipe] = {}
    for index, row in enumerate(rows):
        if not isinstance(row, dict) or set(row) != _RECIPE_FIELDS:
            raise Stage21InitialReportReferenceError(
                "JAVA_INITIAL_REPORT_RECIPE_INVALID",
                f"initial TestReport recipe row {index} has an invalid shape",
            )
        resource_key = row.get("resourceKey")
        resource_type = row.get("resourceType")
        lifecycle = row.get("lifecycle")
        case_id = row.get("caseId")
        if (
            not isinstance(resource_key, str)
            or _RESOURCE_KEY_RE.fullmatch(resource_key) is None
            or not isinstance(resource_type, str)
            or resource_type != "TEST_REPORT"
            or not isinstance(lifecycle, str)
            or lifecycle != "STAGE21_INITIAL"
            or not isinstance(case_id, str)
            or case_id != f"stage21-initial-report:{resource_key}"
        ):
            raise Stage21InitialReportReferenceError(
                "JAVA_INITIAL_REPORT_RECIPE_INVALID",
                f"initial TestReport recipe row {index} has invalid typed fields",
            )
        if resource_key in recipes:
            raise Stage21InitialReportReferenceError(
                "JAVA_INITIAL_REPORT_RECIPE_INVALID",
                f"initial TestReport resource key is duplicated: {resource_key}",
            )
        recipes[resource_key] = Stage21InitialReportRecipe(
            resource_key=resource_key,
            resource_type=resource_type,
            lifecycle=lifecycle,
            case_id=case_id,
        )
    return recipes


def resolve_stage21_initial_report_reference(
    task: BenchmarkTask,
) -> Stage21InitialReportReference | None:
    """Validate the input-side symbolic reference without reading expected-side data."""

    if not is_stage21_initial_report_task(task):
        return None
    references = tuple(
        entry
        for entry in task.initial_state.entries
        if (
            isinstance(entry, JavaResourceReference)
            and entry.ref.startswith("java://test-report/")
            and "/stage21-initial/" in entry.ref
        )
    )
    if len(references) != 1:
        raise Stage21InitialReportReferenceError(
            "JAVA_INITIAL_REPORT_REFERENCE_INVALID",
            f"{task.benchmark_task_id} must declare exactly one initial TestReport reference",
        )
    source_reference = references[0].ref
    match = _REFERENCE_RE.fullmatch(source_reference)
    if match is None:
        raise Stage21InitialReportReferenceError(
            "JAVA_INITIAL_REPORT_REFERENCE_INVALID",
            f"{task.benchmark_task_id} must use its project-scoped "
            "symbolic initial report reference",
        )
    resource_key = match.group("resource")
    recipe = load_stage21_initial_report_recipes().get(resource_key)
    if recipe is None:
        raise Stage21InitialReportReferenceError(
            "JAVA_INITIAL_REPORT_RECIPE_UNKNOWN",
            f"no approved initial TestReport recipe matches resource key {resource_key}",
        )
    project_id = _task_project_id(task)
    source_project_id = int(match.group("project"))
    if project_id is None or project_id != source_project_id:
        raise Stage21InitialReportReferenceError(
            "JAVA_INITIAL_REPORT_PROJECT_MISMATCH",
            "initial TestReport project does not match the trusted project for "
            f"{task.benchmark_task_id}",
        )
    return Stage21InitialReportReference(
        source_reference=source_reference,
        project_id=project_id,
        resource_key=recipe.resource_key,
        case_id=recipe.case_id,
    )


def _task_project_id(task: BenchmarkTask) -> int | None:
    for entry in task.initial_state.entries:
        if isinstance(entry, LiteralSetup) and entry.key == "projectId":
            if (
                isinstance(entry.value, int)
                and not isinstance(entry.value, bool)
                and entry.value > 0
            ):
                return entry.value
    return None


__all__ = [
    "DEFAULT_STAGE21_INITIAL_REPORT_RECIPE_PATH",
    "Stage21InitialReportRecipe",
    "Stage21InitialReportReference",
    "Stage21InitialReportReferenceError",
    "is_stage21_initial_report_task",
    "load_stage21_initial_report_recipes",
    "resolve_stage21_initial_report_reference",
]
