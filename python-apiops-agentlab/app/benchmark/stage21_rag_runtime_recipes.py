"""Input-side RAG recipes for the remaining Stage 21 RAG tasks.

The catalog supplies only a deterministic query input.  It never injects a
model ToolIntent into the real workflow; live acceptance sends the input
through the existing Java Tool Gateway test boundary.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from json import JSONDecodeError
from pathlib import Path

from .golden import GOLDEN_FIXTURE_ROOT
from .models import BenchmarkTask, JavaResourceReference

DEFAULT_STAGE21_RAG_RECIPE_PATH = (
    GOLDEN_FIXTURE_ROOT / "support" / "stage21-remaining-rag-recipes.json"
)

STAGE21_RAG_RUNTIME_RECIPE_TASK_IDS = frozenset(
    {
        "bench_task_e2e_diagnosis_tool_guarded",
        "bench_task_formal_e2e_generation_diagnosis_guarded",
        "bench_task_failure_business_inventory",
        "bench_task_failure_evidence_root_report",
        "bench_task_failure_http_500",
        "bench_task_formal_failure_business_acceptable_alt",
        "bench_task_formal_failure_http500_diagnosis_boundary",
        "bench_task_formal_failure_http500_payload",
        "bench_task_formal_failure_http500_transport_distinction",
        "bench_task_formal_failure_inventory_business",
        "bench_task_formal_failure_inventory_duplicate_key",
        "bench_task_formal_failure_multi_evidence_report",
        "bench_task_formal_failure_report_constraint_alternative",
        "bench_task_formal_failure_report_constraint_primary",
        "bench_task_formal_rag_citation_report",
        "bench_task_formal_rag_distractor_filter",
        "bench_task_formal_rag_multi_constraint_summary",
        "bench_task_formal_rag_multi_report_index",
        "bench_task_formal_rag_near_match_exact",
        "bench_task_formal_rag_single_constraint",
        "bench_task_formal_rag_wrong_project_isolation",
        "bench_task_formal_rag_zero_hit_authorized",
        "bench_task_formal_tool_allowed_rag_subset",
        "bench_task_formal_tool_bad_arguments_query",
        "bench_task_formal_tool_cross_project_request",
        "bench_task_formal_tool_deny_no_alternate_path",
        "bench_task_formal_tool_java_deny_project",
        "bench_task_golden_e2e_apiops",
        "bench_task_golden_failure_diagnosis",
        "bench_task_golden_rag_evidence",
        "bench_task_golden_tool_safety",
        "bench_task_rag_citation_correctness",
        "bench_task_rag_irrelevant_distractor",
        "bench_task_rag_multi_hit",
        "bench_task_rag_near_match",
        "bench_task_rag_wrong_project",
        "bench_task_rag_zero_hit",
        "bench_task_tool_allowed_rag_read",
        "bench_task_tool_bad_arguments",
        "bench_task_tool_java_deny",
    }
)

_ROOT_FIELDS = frozenset({"schemaVersion", "recipes"})
_RECIPE_FIELDS = frozenset({"benchmarkTaskId", "sourceReference", "query", "topK"})
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


class Stage21RagRuntimeRecipeResolutionError(ValueError):
    """A declared input-side RAG recipe cannot be resolved safely."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class Stage21RagRuntimeRecipe:
    benchmark_task_id: str
    source_reference: str
    query: str
    top_k: int


def is_stage21_rag_runtime_recipe_task(task: BenchmarkTask) -> bool:
    return task.benchmark_task_id in STAGE21_RAG_RUNTIME_RECIPE_TASK_IDS


def load_stage21_rag_runtime_recipes(
    path: Path = DEFAULT_STAGE21_RAG_RECIPE_PATH,
) -> dict[str, Stage21RagRuntimeRecipe]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, JSONDecodeError) as exc:
        raise Stage21RagRuntimeRecipeResolutionError(
            "JAVA_RAG_RUNTIME_RECIPE_UNREADABLE",
            "Stage 21 RAG recipe catalog is not readable JSON",
        ) from exc
    if not isinstance(payload, dict) or set(payload) != _ROOT_FIELDS:
        raise Stage21RagRuntimeRecipeResolutionError(
            "JAVA_RAG_RUNTIME_RECIPE_INVALID",
            "Stage 21 RAG recipe catalog has an invalid root shape",
        )
    if payload.get("schemaVersion") != "stage21-rag-runtime-recipe/v1":
        raise Stage21RagRuntimeRecipeResolutionError(
            "JAVA_RAG_RUNTIME_RECIPE_INVALID",
            "Stage 21 RAG recipe catalog has an unsupported schema version",
        )
    rows = payload.get("recipes")
    if not isinstance(rows, list):
        raise Stage21RagRuntimeRecipeResolutionError(
            "JAVA_RAG_RUNTIME_RECIPE_INVALID",
            "Stage 21 RAG recipe catalog recipes must be an array",
        )

    recipes: dict[str, Stage21RagRuntimeRecipe] = {}
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise Stage21RagRuntimeRecipeResolutionError(
                "JAVA_RAG_RUNTIME_RECIPE_INVALID",
                f"RAG recipe row {index} has an invalid shape",
            )
        _reject_expected_side(row, location=f"recipe row {index}")
        if set(row) != _RECIPE_FIELDS:
            raise Stage21RagRuntimeRecipeResolutionError(
                "JAVA_RAG_RUNTIME_RECIPE_INVALID",
                f"RAG recipe row {index} has an invalid shape",
            )
        task_id = row.get("benchmarkTaskId")
        source_reference = row.get("sourceReference")
        query = row.get("query")
        top_k = row.get("topK")
        if (
            not isinstance(task_id, str)
            or not task_id.strip()
            or not isinstance(source_reference, str)
            or not source_reference.strip()
            or not isinstance(query, str)
            or not query.strip()
            or len(query) > 4096
            or isinstance(top_k, bool)
            or not isinstance(top_k, int)
            or not 1 <= top_k <= 20
        ):
            raise Stage21RagRuntimeRecipeResolutionError(
                "JAVA_RAG_RUNTIME_RECIPE_INVALID",
                f"RAG recipe row {index} has invalid scalar fields",
            )
        if task_id not in STAGE21_RAG_RUNTIME_RECIPE_TASK_IDS or task_id in recipes:
            raise Stage21RagRuntimeRecipeResolutionError(
                "JAVA_RAG_RUNTIME_RECIPE_INVALID",
                f"RAG recipe task identity is invalid: {task_id}",
            )
        recipes[task_id] = Stage21RagRuntimeRecipe(
            benchmark_task_id=task_id,
            source_reference=source_reference,
            query=query,
            top_k=top_k,
        )

    if set(recipes) != STAGE21_RAG_RUNTIME_RECIPE_TASK_IDS:
        raise Stage21RagRuntimeRecipeResolutionError(
            "JAVA_RAG_RUNTIME_RECIPE_INVALID",
            "Stage 21 RAG recipe catalog must cover every required RAG execution task",
        )
    return recipes


def resolve_stage21_rag_runtime_recipe(
    task: BenchmarkTask,
    *,
    fixture_path: Path | None = None,
) -> Stage21RagRuntimeRecipe | None:
    if not is_stage21_rag_runtime_recipe_task(task):
        return None
    references = tuple(
        entry.ref
        for entry in task.initial_state.entries
        if isinstance(entry, JavaResourceReference)
    )
    if not references:
        raise Stage21RagRuntimeRecipeResolutionError(
            "JAVA_RAG_RUNTIME_RECIPE_REFERENCE_INVALID",
            f"{task.benchmark_task_id} must declare a Java authority reference",
        )
    recipe = load_stage21_rag_runtime_recipes(fixture_path or DEFAULT_STAGE21_RAG_RECIPE_PATH).get(
        task.benchmark_task_id
    )
    if recipe is None or recipe.source_reference not in references:
        raise Stage21RagRuntimeRecipeResolutionError(
            "JAVA_RAG_RUNTIME_RECIPE_REFERENCE_UNRESOLVED",
            f"no input-side RAG recipe matches {task.benchmark_task_id}",
        )
    return recipe


def _reject_expected_side(value: object, *, location: str) -> None:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            if isinstance(key, str) and key.lower() in _FORBIDDEN_EXPECTED_KEYS:
                raise Stage21RagRuntimeRecipeResolutionError(
                    "JAVA_RAG_RUNTIME_RECIPE_EXPECTED_SIDE_LEAK",
                    f"expected-side key is not allowed in {location}",
                )
            _reject_expected_side(nested, location=location)
    elif isinstance(value, list):
        for nested in value:
            _reject_expected_side(nested, location=location)


__all__ = [
    "DEFAULT_STAGE21_RAG_RECIPE_PATH",
    "STAGE21_RAG_RUNTIME_RECIPE_TASK_IDS",
    "Stage21RagRuntimeRecipe",
    "Stage21RagRuntimeRecipeResolutionError",
    "is_stage21_rag_runtime_recipe_task",
    "load_stage21_rag_runtime_recipes",
    "resolve_stage21_rag_runtime_recipe",
]
