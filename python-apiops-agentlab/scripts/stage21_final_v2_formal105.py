"""Freeze Stage 21 and execute exactly one V2 Formal105 run.

This is a thin operational wrapper around the existing baseline runner.  It
does not define a workflow, change prompts, or recalculate Stage 19 metrics.
The ``--finalize-existing`` mode only reads the persisted run and writes the
bounded Stage 21 projection/report artifacts; it never calls a model.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import subprocess
from collections import Counter
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import stage21_final_revision_gate as final_revision
import stage21_real_model_baseline as baseline

from app.benchmark.baseline import plan_baseline_artifact_paths
from app.benchmark.dataset import BenchmarkDataset, lint_dataset, load_dataset
from app.benchmark.outcome_v2 import (
    OutcomePolicy,
    OutcomeV2Projection,
    load_outcome_policy,
    load_persisted_formal105_run,
    project_outcome_v2,
    render_outcome_v2_summary,
)
from app.benchmark.provider_integrity import verify_provider_integrity
from app.benchmark.runner import (
    MAX_PLANNED_ARTIFACT_PATH,
    BenchmarkRun,
    BenchmarkTaskResult,
    BenchmarkTaskStatus,
    JavaExecutionStatus,
    physical_task_result_filename,
    preflight_artifact_paths,
)
from app.benchmark.success import TaskSuccessStatus
from app.clients.qwen_structured_output import (
    DIAGNOSIS_REPORT_OUTPUT_SPEC,
    DIAGNOSIS_REPORT_SCHEMA_NAME,
    TESTCASE_CANDIDATE_OUTPUT_SPEC,
    TESTCASE_CANDIDATE_SCHEMA_NAME,
    schema_digest,
)
from app.core.settings import AppSettings, get_settings
from app.evaluator import EVALUATOR_VERSION, MetricName, MetricStatus

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
MANIFEST_PATH = (
    REPOSITORY_ROOT / "python-apiops-agentlab/tests/benchmark/fixtures/dataset-manifest.json"
)
POLICY_PATH = (
    REPOSITORY_ROOT
    / "python-apiops-agentlab/tests/benchmark/fixtures/stage21-outcome-policy-v2.json"
)
EXECUTION_PREREQUISITE_PATH = (
    REPOSITORY_ROOT
    / "python-apiops-agentlab/tests/benchmark/fixtures/stage21-execution-prerequisites.json"
)
RAG_RUNTIME_RECIPE_PATH = (
    REPOSITORY_ROOT
    / "python-apiops-agentlab/tests/benchmark/fixtures/support/stage21-remaining-rag-recipes.json"
)
ACCURACY_REPAIR_CONTRACT_PATH = (
    REPOSITORY_ROOT / "docs/stage21-formal105-accuracy-repair-contract.md"
)
RAG_MANIFEST_PATH = (
    REPOSITORY_ROOT
    / (
        "java-apiops-platform/apiops-web/src/test/resources/"
        "stage21/rag-corpus-v2/corpus-manifest.json"
    )
)
RAG_ACCEPTANCE_PATH = REPOSITORY_ROOT / "artifacts/stage21/rag-v2-acceptance/acceptance.json"
TARGETED_SUMMARY_PATH = (
    REPOSITORY_ROOT / "artifacts/stage21/v2-required-tool-targeted/required-tool-summary.json"
)
AUTHORITY_CLOSURE_PATH = (
    REPOSITORY_ROOT / "artifacts/stage21/v2-authority-closure/outcome-authority-closure.json"
)
QWEN_ACCEPTANCE_DIR = (
    REPOSITORY_ROOT / "artifacts/stage21/qwen38-provider-acceptance-v3"
)
GENERATION_LIVE_METADATA_PATH = (
    REPOSITORY_ROOT
    / (
        "python-apiops-agentlab/tests/benchmark/fixtures/support/"
        "generation-live-runner-openapi-metadata.json"
    )
)
GENERATION_INPUT_RESOLVER_PATH = (
    REPOSITORY_ROOT / "python-apiops-agentlab/app/benchmark/generation_inputs.py"
)
GUARDED_TASK_PATH = (
    REPOSITORY_ROOT
    / (
        "python-apiops-agentlab/tests/benchmark/fixtures/tasks/"
        "bench_task_e2e_diagnosis_tool_guarded.json"
    )
)
GUARDED_GROUND_TRUTH_PATH = (
    REPOSITORY_ROOT
    / (
        "python-apiops-agentlab/tests/benchmark/fixtures/ground_truth/"
        "gt_stage21_e2e_diagnosis_tool_guarded.json"
    )
)
FORMAL_GUARDED_TASK_PATH = (
    REPOSITORY_ROOT
    / (
        "python-apiops-agentlab/tests/benchmark/fixtures/formal/tasks/"
        "bench_task_formal_e2e_generation_diagnosis_guarded.json"
    )
)
FORMAL_GUARDED_GROUND_TRUTH_PATH = (
    REPOSITORY_ROOT
    / (
        "python-apiops-agentlab/tests/benchmark/fixtures/formal/ground_truth/"
        "gt_stage21_e2e_generation_diagnosis_guarded.json"
    )
)
AUTHORITY_BINDING_SOURCE_PATH = (
    REPOSITORY_ROOT / "python-apiops-agentlab/app/evaluator/evaluator.py"
)
LIVE_RUNNER_GENERATION_TASK_IDS = (
    "bench_task_testcase_happy_create_order_runner",
    "bench_task_formal_testcase_inventory_conflict_runner",
)
EXACT_AUTHORITY_GROUND_TRUTH_IDS = (
    "gt_stage21_rag_evidence",
    "gt_stage21_formal_failure_report_constraint_primary",
    "gt_stage21_formal_rag_citation_report",
    "gt_stage21_formal_rag_distractor_filter",
    "gt_stage21_formal_rag_multi_constraint_summary",
    "gt_stage21_formal_rag_multi_report_index",
    "gt_stage21_formal_rag_near_match_exact",
    "gt_stage21_formal_rag_single_constraint",
    "gt_stage21_rag_near_match",
    "gt_stage21_formal_testcase_inventory_conflict_runner",
)
ACCURACY_REPAIR_WORKFLOW_SOURCES = (
    "python-apiops-agentlab/app/benchmark/generation_inputs.py",
    "python-apiops-agentlab/app/benchmark/outcome_projection.py",
    "python-apiops-agentlab/app/benchmark/outcome_v2.py",
    "python-apiops-agentlab/app/benchmark/real_model.py",
    "python-apiops-agentlab/app/benchmark/stage21_rag_runtime_recipes.py",
    "python-apiops-agentlab/app/evaluator/evaluator.py",
    "python-apiops-agentlab/app/workflows/diagnosis_workflow.py",
    "python-apiops-agentlab/app/workflows/tool_planning.py",
)
EXPECTED_QWEN_MODEL = "qwen3.8-max"
DEFAULT_OUTPUT_ROOT = REPOSITORY_ROOT / "artifacts/stage21"
PATH_PREFLIGHT_ARTIFACT_PARENT = (
    REPOSITORY_ROOT / "python-apiops-agentlab/artifacts/stage21"
)
HISTORICAL_OUTPUT_ROOTS = (
    REPOSITORY_ROOT / "artifacts/stage21/final-v2-formal105",
    REPOSITORY_ROOT / "artifacts/stage21/outcome-first-rag-enhanced-105",
    REPOSITORY_ROOT / "artifacts/stage21/formal-real-model-final",
)
FORMAL_TASK_COUNT = 105
EXPECTED_DEV_COUNT = 95
EXPECTED_HELD_OUT_COUNT = 10
EXPECTED_DENY_OUTCOMES = frozenset(
    {"JAVA_DENIED", "FORBIDDEN_INTENT_DENIED", "HUMAN_REJECTED", "APPROVAL_BYPASS_BLOCKED"}
)
TAXONOMY_CATEGORIES = (
    "INFRASTRUCTURE",
    "PROVIDER",
    "MODEL_OUTPUT",
    "REQUIRED_TOOL_MISS",
    "TOOL_EXECUTION",
    "JAVA_REQUIRED_PATH",
    "AUTHORIZATION",
    "EVALUATION_AUTHORITY",
    "OTHER",
)
COMMON_RUNTIME_ENVIRONMENT_NAMES = (
    "JAVA_APIOPS_BASE_URL",
    "STAGE21_NORMAL_USERNAME",
    "STAGE21_NORMAL_PASSWORD",
    "STAGE21_SAFETY41_USERNAME",
    "STAGE21_SAFETY41_PASSWORD",
    "STAGE21_SAFETY42_USERNAME",
    "STAGE21_SAFETY42_PASSWORD",
)
PROMPT_SOURCES = (
    {
        "name": "testcase_generate",
        "version": "v1",
        "files": (
            "python-apiops-agentlab/app/agents/prompts/testcase_generate_v1.txt",
        ),
    },
    {
        "name": "testcase_repair",
        "version": "v1",
        "files": ("python-apiops-agentlab/app/agents/prompts/testcase_repair_v1.txt",),
    },
    {
        "name": "diagnosis",
        "version": "1",
        "files": (
            "python-apiops-agentlab/app/agents/prompts/diagnosis_v1.txt",
        ),
    },
    {
        "name": "diagnosis_memory_refinement",
        "version": "v1",
        "files": (
            "python-apiops-agentlab/app/agents/prompts/diagnosis_memory_refinement_v1.txt",
        ),
    },
)

QWEN_GATE_MARKERS = (
    "QWEN_PROVIDER = PASS",
    "QWEN_RUNTIME_WIRING = PASS",
    "QWEN_DIAGNOSIS_SEMANTIC = PASS",
    "QWEN_TESTCASE_NATIVE_POSITIVE = PASS",
    "QWEN_TESTCASE_NATIVE_INTENTIONAL_INVALID = PASS",
    "DEEPSEEK_REGRESSION = PASS",
    "QWEN_PROVIDER_CHAIN = PASS",
    "FORMAL105_STATUS = NOT_RUN",
)
QWEN_SCHEMA_IDENTITIES = {
    "testcase": {
        "mode": "JSON_SCHEMA",
        "schemaName": TESTCASE_CANDIDATE_SCHEMA_NAME,
        "schemaDigest": schema_digest(TESTCASE_CANDIDATE_OUTPUT_SPEC.schema),
    },
    "diagnosisInitial": {
        "mode": "JSON_OBJECT",
        "allowedOutputs": ["DiagnosisReport", "ToolIntent"],
    },
    "diagnosisReportContinuation": {
        "mode": "JSON_SCHEMA",
        "schemaName": DIAGNOSIS_REPORT_SCHEMA_NAME,
        "schemaDigest": schema_digest(DIAGNOSIS_REPORT_OUTPUT_SPEC.schema),
    },
    "diagnosisMemoryRefinement": {
        "mode": "JSON_SCHEMA",
        "schemaName": DIAGNOSIS_REPORT_SCHEMA_NAME,
        "schemaDigest": schema_digest(DIAGNOSIS_REPORT_OUTPUT_SPEC.schema),
    },
    "diagnosisNativeCoverage": "REPORT_PATH_ONLY",
}
BENCHMARK_CONTRACT_REVISION = final_revision.FINAL_REVISION
SCHEMA_SOURCES = (
    "shared-schemas/diagnosis-report-schema.json",
    "shared-schemas/evaluation-task-schema.json",
    "shared-schemas/testcase-dsl-schema.json",
    "shared-schemas/tool-call-schema.json",
    "shared-schemas/tool-result-schema.json",
    "python-apiops-agentlab/app/schemas/diagnosis_report.py",
    "python-apiops-agentlab/app/schemas/testcase_dsl.py",
    "python-apiops-agentlab/app/schemas/tool_call.py",
    "python-apiops-agentlab/app/schemas/tool_result.py",
    "python-apiops-agentlab/app/clients/qwen_structured_output.py",
)


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _enum_value(value: object) -> object:
    return getattr(value, "value", value)


def _digest_paths(paths: list[tuple[str, Path]]) -> str:
    digest = hashlib.sha256()
    for label, path in paths:
        if not path.is_file():
            raise RuntimeError(f"freeze input is missing: {path}")
        digest.update(label.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _digest_strings(values: Iterable[str]) -> str:
    digest = hashlib.sha256()
    for value in values:
        digest.update(value.encode("utf-8"))
        digest.update(b"\0")
    return digest.hexdigest()


def _secret_present(value: object) -> bool:
    if value is None:
        return False
    getter = getattr(value, "get_secret_value", None)
    resolved = getter() if callable(getter) else value
    return bool(str(resolved).strip())


def _require_provider(provider: str | None) -> str:
    """Require the provider identity frozen for the current Formal105 revision."""

    if provider is None:
        raise RuntimeError("Stage21 Formal105 live run requires explicit --provider")
    if provider != "qwen":
        raise RuntimeError(
            "Stage21 Formal105 provider identity is frozen to qwen; "
            f"received: {provider}"
        )
    return provider


def _ensure_new_output_root(output_root: Path) -> Path:
    candidate = output_root.resolve()
    for historical in HISTORICAL_OUTPUT_ROOTS:
        historical_path = historical.resolve()
        if (
            candidate == historical_path
            or historical_path in candidate.parents
            or candidate in historical_path.parents
        ):
            raise RuntimeError(
                "Formal105 output root overlaps a historical artifact; refusing write: "
                f"{candidate}"
            )
    if candidate.exists():
        raise RuntimeError(
            "Formal105 output root already exists; refusing a second run: " f"{candidate}"
        )
    return candidate


STAGE21_FINAL_ARTIFACT_NAMES = (
    "freeze-manifest.json",
    "outcome-v2.json",
    "outcome-v2-summary.md",
    "tool-use-analysis.json",
    "failure-taxonomy.json",
    "formal105-summary.json",
    "formal105-summary.md",
    "provider-evidence.json",
    "run-manifest.json",
    "metrics.json",
    "reproducibility.json",
    "final-acceptance.md",
    "stage21-final-acceptance.md",
)


def _planned_formal105_artifact_paths(
    output_root: Path,
    evaluation_run_id: str,
    task_ids: Iterable[str],
) -> list[tuple[str, Path]]:
    """Plan the primary baseline and Stage21 projection artifacts."""

    ordered_task_ids = tuple(task_ids)
    paths = plan_baseline_artifact_paths(
        output_root / "full-105",
        evaluation_run_id,
        ordered_task_ids,
    )
    paths.extend(
        (
            f"stage21:task-projection:{index:03d}:{task_id}",
            output_root / "task-results" / physical_task_result_filename(
                evaluation_run_id,
                task_id,
            ),
        )
        for index, task_id in enumerate(ordered_task_ids, start=1)
    )
    paths.extend(
        (f"stage21:{name}", output_root / name) for name in STAGE21_FINAL_ARTIFACT_NAMES
    )
    return paths


def _formal105_path_preflight(
    output_root: Path,
    evaluation_run_id: str,
    task_ids: Iterable[str],
) -> dict[str, object]:
    """Preflight all 105 paths before constructing a live provider runner."""

    ordered_task_ids = tuple(task_ids)
    if len(ordered_task_ids) != FORMAL_TASK_COUNT:
        raise RuntimeError("Formal105 path preflight requires exactly 105 tasks")
    if len(set(ordered_task_ids)) != FORMAL_TASK_COUNT:
        raise RuntimeError("Formal105 path preflight requires unique task IDs")
    planned = _planned_formal105_artifact_paths(output_root, evaluation_run_id, ordered_task_ids)
    report = preflight_artifact_paths(planned)
    entries = report["paths"]
    primary_task_entries = [
        entry for entry in entries if str(entry["label"]).startswith("baseline:task:")
    ]
    projection_entries = [
        entry for entry in entries if str(entry["label"]).startswith("stage21:task-projection:")
    ]
    run_level_entries = [
        entry
        for entry in entries
        if entry not in primary_task_entries and entry not in projection_entries
    ]
    if len(primary_task_entries) != FORMAL_TASK_COUNT:
        raise RuntimeError("Formal105 path preflight did not plan 105 primary task paths")
    task_paths = [str(entry["path"]) for entry in primary_task_entries]
    if len(set(task_paths)) != FORMAL_TASK_COUNT:
        raise RuntimeError("Formal105 path preflight found colliding task paths")
    return {
        "schemaVersion": "stage21-formal105-path-preflight/v1",
        "evaluationRunId": evaluation_run_id,
        "plannedOutputRoot": str(output_root.resolve()),
        "taskCount": FORMAL_TASK_COUNT,
        "uniqueTaskPaths": len(set(task_paths)),
        "taskPaths": [
            {
                "manifestIndex": index,
                "taskId": task_id,
                "path": entry["path"],
                "length": entry["length"],
            }
            for index, (task_id, entry) in enumerate(
                zip(ordered_task_ids, primary_task_entries, strict=True),
                start=1,
            )
        ],
        "taskProjectionPaths": [
            {
                "manifestIndex": index,
                "taskId": task_id,
                "path": entry["path"],
                "length": entry["length"],
            }
            for index, (task_id, entry) in enumerate(
                zip(ordered_task_ids, projection_entries, strict=True),
                start=1,
            )
        ],
        "runLevelPathsChecked": run_level_entries,
        "plannedPathCount": report["pathCount"],
        "maxPathLength": report["maxPathLength"],
        "maxPath": report["maxPath"],
        "pathBudget": MAX_PLANNED_ARTIFACT_PATH,
        "overBudgetCount": report["overBudgetCount"],
        "providerCalls": 0,
        "javaExecutions": 0,
    }


def _render_path_preflight(record: dict[str, object]) -> str:
    return "\n".join(
        [
            "# Formal105 Artifact Path Preflight",
            "",
            f"- Evaluation run identity: `{record['evaluationRunId']}`",
            f"- Planned output root: `{record['plannedOutputRoot']}`",
            f"- Task count: `{record['taskCount']}`",
            f"- Unique primary task paths: `{record['uniqueTaskPaths']}`",
            f"- Maximum planned path: `{record['maxPathLength']}` characters",
            f"- Path budget: `{record['pathBudget']}` characters",
            f"- Over-budget paths: `{record['overBudgetCount']}`",
            f"- Provider calls: `{record['providerCalls']}`",
            f"- Java executions: `{record['javaExecutions']}`",
            "",
            "## Run-level paths checked",
            "",
            "```json",
            json.dumps(record["runLevelPathsChecked"], ensure_ascii=False, indent=2),
            "```",
            "",
            "## Longest task identity",
            "",
            "```json",
            json.dumps(
                max(record["taskPaths"], key=lambda entry: entry["length"]),
                ensure_ascii=False,
                indent=2,
            ),
            "```",
            "",
            "`FULL105_PATH_PREFLIGHT = PASS`",
            "",
        ]
    )


def _scan_artifact_secrets(root: Path, secret_values: Iterable[str]) -> list[Path]:
    """Return only paths containing known secret values; never return the values."""

    needles = tuple(value.encode("utf-8") for value in secret_values if value)
    if not needles or not root.is_dir():
        return []
    matches: list[Path] = []
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        try:
            content = path.read_bytes()
        except OSError:
            continue
        if any(needle in content for needle in needles):
            matches.append(path)
    return matches


def _git_snapshot() -> dict[str, object]:
    def run(args: list[str]) -> bytes:
        completed = subprocess.run(
            args,
            cwd=REPOSITORY_ROOT,
            capture_output=True,
            check=False,
            timeout=10,
        )
        if completed.returncode != 0:
            raise RuntimeError(f"git command failed: {' '.join(args)}")
        return completed.stdout

    head = run(["git", "rev-parse", "HEAD"]).decode("utf-8", errors="replace").strip()
    status = run(["git", "status", "--porcelain=v1", "--untracked-files=all"])
    branch = run(["git", "branch", "--show-current"]).decode(
        "utf-8", errors="replace"
    ).strip()
    diff = run(["git", "diff", "--no-ext-diff", "--binary", "HEAD"])
    status_lines = status.decode("utf-8", errors="replace").splitlines()
    tracked_dirty = [line for line in status_lines if not line.startswith("?? ")]
    untracked = [line[3:] for line in status_lines if line.startswith("?? ")]
    return {
        "gitHead": head,
        "branch": branch or "UNAVAILABLE",
        "workingTreeDirty": bool(status.strip()),
        "dirtyDiffDigest": _sha256_bytes(status + b"\0" + diff),
        "gitDiffBinarySha256": _sha256_bytes(diff),
        "trackedDirtyPathCount": len(tracked_dirty),
        "untrackedPathCount": len(untracked),
        "trackedDirtyPathDigest": _digest_strings(tracked_dirty),
        "untrackedPathDigest": _digest_strings(untracked),
    }


def _java_version() -> str:
    completed = subprocess.run(
        ["java", "-version"],
        cwd=REPOSITORY_ROOT,
        capture_output=True,
        check=False,
        text=True,
        timeout=10,
    )
    text = (completed.stderr or completed.stdout).splitlines()
    return text[0].strip() if text else "UNAVAILABLE"


def _corpus_freeze() -> dict[str, object]:
    raw = _read_json(RAG_MANIFEST_PATH)
    document_paths = [("corpus-manifest.json", RAG_MANIFEST_PATH)]
    for document in raw.get("documents", []):
        relative = str(document["file"])
        document_paths.append((relative, RAG_MANIFEST_PATH.parent / relative))
    acceptance = _read_json(RAG_ACCEPTANCE_PATH)
    if acceptance.get("readiness") != "PASS":
        raise RuntimeError("current deterministic RAG acceptance is not PASS")
    threshold = float(acceptance["threshold"])
    configured_threshold = os.environ.get("APIOPS_RAG_MIN_RELEVANCE_SCORE", "").strip()
    if configured_threshold and float(configured_threshold) != threshold:
        raise RuntimeError("current RAG threshold differs from the accepted frozen threshold")
    return {
        "corpusVersion": raw["corpusVersion"],
        "manifestDigest": _sha256_file(RAG_MANIFEST_PATH),
        "corpusDigest": _digest_paths(document_paths),
        "documentCount": len(raw["documents"]),
        "embeddingProvider": raw["embeddingProvider"],
        "embeddingModel": raw["embeddingModel"],
        "embeddingDimension": raw["embeddingDimension"],
        "threshold": threshold,
        "acceptanceArtifact": str(RAG_ACCEPTANCE_PATH),
        "acceptanceDigest": _sha256_file(RAG_ACCEPTANCE_PATH),
    }


def _prompt_freeze() -> list[dict[str, object]]:
    values: list[dict[str, object]] = []
    for prompt in PROMPT_SOURCES:
        files = [
            (relative, REPOSITORY_ROOT / relative)
            for relative in prompt["files"]
        ]
        values.append(
            {
                "name": prompt["name"],
                "version": prompt["version"],
                "files": list(prompt["files"]),
                "digest": _digest_paths(files),
            }
        )
    return values


def _accuracy_repair_contract_freeze() -> dict[str, object]:
    prerequisite = _read_json(EXECUTION_PREREQUISITE_PATH)
    recipes = _read_json(RAG_RUNTIME_RECIPE_PATH)
    generation_metadata = _read_json(GENERATION_LIVE_METADATA_PATH)
    guarded_task = _read_json(GUARDED_TASK_PATH)
    guarded_ground_truth = _read_json(GUARDED_GROUND_TRUTH_PATH)
    formal_guarded_task = _read_json(FORMAL_GUARDED_TASK_PATH)
    formal_guarded_ground_truth = _read_json(FORMAL_GUARDED_GROUND_TRUTH_PATH)
    prerequisite_tasks = prerequisite.get("tasks", [])
    recipe_rows = recipes.get("recipes", [])
    if not isinstance(prerequisite_tasks, list) or len(prerequisite_tasks) != FORMAL_TASK_COUNT:
        raise RuntimeError("execution prerequisite freeze requires exactly 105 tasks")
    if not isinstance(recipe_rows, list) or not recipe_rows:
        raise RuntimeError("RAG runtime recipe freeze requires recipe rows")
    required_tool_tasks = sum(
        isinstance(row, dict)
        and "TOOL_CALL" in row.get("requiredOperations", [])
        for row in prerequisite_tasks
    )
    schema_paths = [
        (relative, REPOSITORY_ROOT / relative)
        for relative in SCHEMA_SOURCES
    ]
    workflow_paths = [
        (relative, REPOSITORY_ROOT / relative)
        for relative in ACCURACY_REPAIR_WORKFLOW_SOURCES
    ]
    if guarded_task.get("benchmarkTaskId") != "bench_task_e2e_diagnosis_tool_guarded":
        raise RuntimeError("guarded-task freeze identity mismatch")
    if (
        guarded_ground_truth.get("ground_truth_id")
        != "gt_stage21_e2e_diagnosis_tool_guarded"
        or guarded_ground_truth.get("version") != "v4"
    ):
        raise RuntimeError("guarded-task GroundTruth freeze identity mismatch")
    if (
        formal_guarded_task.get("benchmarkTaskId")
        != "bench_task_formal_e2e_generation_diagnosis_guarded"
        or formal_guarded_ground_truth.get("ground_truth_id")
        != "gt_stage21_formal_e2e_generation_diagnosis_guarded"
        or formal_guarded_ground_truth.get("version") != "v2"
    ):
        raise RuntimeError("formal guarded-task freeze identity mismatch")
    return {
        "revision": BENCHMARK_CONTRACT_REVISION,
        "parentOfficialBaseline": "official-20260903T173410Z",
        "changeRecord": {
            "path": str(ACCURACY_REPAIR_CONTRACT_PATH),
            "digest": _sha256_file(ACCURACY_REPAIR_CONTRACT_PATH),
            "reason": (
                "freeze the accuracy repairs, exact authority bindings, live Runner "
                "metadata, diagnosis semantics, and the bounded guarded-task correction"
            ),
            "changesTaskSemantics": True,
            "modelOutputBasis": False,
            "boundedSemanticCorrections": [
                {
                    "benchmarkTaskId": "bench_task_e2e_diagnosis_tool_guarded",
                    "groundTruthId": "gt_stage21_e2e_diagnosis_tool_guarded",
                    "groundTruthVersion": "v4",
                    "basis": "JAVA_REPORT_AND_DENY_AUTHORITY_CONSISTENCY",
                    "reason": (
                        "a Java-denied retrieval cannot simultaneously be required as "
                        "returned evidence; diagnosis remains grounded in the current "
                        "Java report and the denied attempt remains safety authority"
                    ),
                },
                {
                    "benchmarkTaskId": (
                        "bench_task_formal_e2e_generation_diagnosis_guarded"
                    ),
                    "groundTruthId": (
                        "gt_stage21_formal_e2e_generation_diagnosis_guarded"
                    ),
                    "groundTruthVersion": "v2",
                    "basis": "HAPPY_PATH_JAVA_REPORT_AND_DENY_AUTHORITY_CONSISTENCY",
                    "reason": (
                        "the happy-path Java Runner report proves no execution failure, "
                        "while a cross-project RAG denial cannot return its evidence; "
                        "diagnosis is NONE and the denied attempt remains safety authority"
                    ),
                },
            ],
        },
        "executionPrerequisites": {
            "schemaVersion": prerequisite.get("sidecarVersion"),
            "schemaIdentity": "stage21-execution-prerequisites-sidecar",
            "path": str(EXECUTION_PREREQUISITE_PATH),
            "digest": _sha256_file(EXECUTION_PREREQUISITE_PATH),
            "taskCount": len(prerequisite_tasks),
            "requiredToolTaskCount": required_tool_tasks,
        },
        "ragRuntimeRecipes": {
            "schemaVersion": recipes.get("schemaVersion"),
            "path": str(RAG_RUNTIME_RECIPE_PATH),
            "digest": _sha256_file(RAG_RUNTIME_RECIPE_PATH),
            "recipeCount": len(recipe_rows),
        },
        "generationMetadata": {
            "schemaIdentity": generation_metadata.get("schemaVersion"),
            "path": str(GENERATION_LIVE_METADATA_PATH),
            "digest": _sha256_file(GENERATION_LIVE_METADATA_PATH),
            "resolverPath": str(GENERATION_INPUT_RESOLVER_PATH),
            "resolverDigest": _sha256_file(GENERATION_INPUT_RESOLVER_PATH),
            "taskIds": list(LIVE_RUNNER_GENERATION_TASK_IDS),
            "authority": "LIVE_JAVA_RUNNER_ENDPOINT_CONTRACT",
        },
        "authorityBindings": {
            "mode": "EXACT_GROUND_TRUTH_IDENTITY_AND_AUTHORITY_FACTS",
            "source": str(AUTHORITY_BINDING_SOURCE_PATH),
            "digest": _sha256_file(AUTHORITY_BINDING_SOURCE_PATH),
            "groundTruthIds": list(EXACT_AUTHORITY_GROUND_TRUTH_IDS),
            "directOutcomeAuthority": False,
        },
        "guardedTaskContract": {
            "taskPath": str(GUARDED_TASK_PATH),
            "taskDigest": _sha256_file(GUARDED_TASK_PATH),
            "groundTruthPath": str(GUARDED_GROUND_TRUTH_PATH),
            "groundTruthDigest": _sha256_file(GUARDED_GROUND_TRUTH_PATH),
            "groundTruthId": guarded_ground_truth["ground_truth_id"],
            "groundTruthVersion": guarded_ground_truth["version"],
            "authorityBasis": "JAVA_REPORT_AND_DENY_AUTHORITY_CONSISTENCY",
        },
        "guardedTaskContracts": [
            {
                "taskPath": str(GUARDED_TASK_PATH),
                "taskDigest": _sha256_file(GUARDED_TASK_PATH),
                "groundTruthPath": str(GUARDED_GROUND_TRUTH_PATH),
                "groundTruthDigest": _sha256_file(GUARDED_GROUND_TRUTH_PATH),
                "groundTruthId": guarded_ground_truth["ground_truth_id"],
                "groundTruthVersion": guarded_ground_truth["version"],
                "authorityBasis": "JAVA_REPORT_AND_DENY_AUTHORITY_CONSISTENCY",
            },
            {
                "taskPath": str(FORMAL_GUARDED_TASK_PATH),
                "taskDigest": _sha256_file(FORMAL_GUARDED_TASK_PATH),
                "groundTruthPath": str(FORMAL_GUARDED_GROUND_TRUTH_PATH),
                "groundTruthDigest": _sha256_file(FORMAL_GUARDED_GROUND_TRUTH_PATH),
                "groundTruthId": formal_guarded_ground_truth["ground_truth_id"],
                "groundTruthVersion": formal_guarded_ground_truth["version"],
                "authorityBasis": (
                    "HAPPY_PATH_JAVA_REPORT_AND_DENY_AUTHORITY_CONSISTENCY"
                ),
            },
        ],
        "workflowSources": {
            "files": list(ACCURACY_REPAIR_WORKFLOW_SOURCES),
            "digest": _digest_paths(workflow_paths),
        },
        "schemas": {
            "files": list(SCHEMA_SOURCES),
            "digest": _digest_paths(schema_paths),
            "qwenStructuredOutput": QWEN_SCHEMA_IDENTITIES,
        },
    }


def _environment_readiness(
    settings: AppSettings,
    provider: str,
) -> dict[str, object]:
    """Report provider-specific presence only; credentials never enter an artifact."""

    _require_provider(provider)
    provider_checks = {
        "QWEN_API_KEY": _secret_present(settings.qwen_api_key),
        "QWEN_BASE_URL": bool(settings.qwen_base_url.strip()),
        "QWEN_MODEL": settings.qwen_model == EXPECTED_QWEN_MODEL,
        "QWEN_TIMEOUT_SECONDS": settings.qwen_timeout_seconds > 0,
    }
    optional = {
        "DEEPSEEK_API_KEY": _secret_present(settings.deepseek_api_key),
    }
    common_checks = {
        "JAVA_APIOPS_BASE_URL": bool(settings.java_apiops_base_url.strip()),
        **{
            name: bool(os.environ.get(name, "").strip())
            for name in COMMON_RUNTIME_ENVIRONMENT_NAMES
            if name != "JAVA_APIOPS_BASE_URL"
        },
    }
    required = {**provider_checks, **common_checks}
    return {
        "provider": provider,
        **provider_checks,
        "required": required,
        "optional": optional,
        "ready": all(required.values()),
    }


def _qwen_provider_gate(
    settings: AppSettings,
    acceptance_dir: Path = QWEN_ACCEPTANCE_DIR,
) -> dict[str, object]:
    """Validate the already-produced Qwen chain evidence before any model call."""

    if settings.qwen_model != EXPECTED_QWEN_MODEL:
        raise RuntimeError(
            "Qwen provider gate model identity mismatch: "
            f"expected {EXPECTED_QWEN_MODEL}, got {settings.qwen_model}"
        )
    acceptance_dir = acceptance_dir.resolve()
    final_gate = acceptance_dir / "final-gate.md"
    source_freeze = acceptance_dir / "source-freeze.json"
    quality_gate = acceptance_dir / "quality-gate.json"
    if not final_gate.is_file() or not source_freeze.is_file() or not quality_gate.is_file():
        raise RuntimeError(f"Qwen acceptance gate artifacts are incomplete: {acceptance_dir}")
    final_gate_text = final_gate.read_text(encoding="utf-8")
    missing = [marker for marker in QWEN_GATE_MARKERS if marker not in final_gate_text]
    if missing:
        raise RuntimeError(
            "Qwen acceptance gate is not PASS; missing marker(s): " + ", ".join(missing)
        )
    source = _read_json(source_freeze)
    source_provider = source.get("provider")
    if not isinstance(source_provider, dict):
        raise RuntimeError("Qwen acceptance gate source-freeze provider identity is missing")
    if (
        source_provider.get("provider") != "Qwen"
        or source_provider.get("model") != EXPECTED_QWEN_MODEL
    ):
        raise RuntimeError("Qwen acceptance gate source-freeze model identity mismatch")
    if source.get("formal105Status") != "NOT_RUN":
        raise RuntimeError("Qwen acceptance gate must record FORMAL105_STATUS = NOT_RUN")
    if source.get("structuredOutputProfile") != QWEN_SCHEMA_IDENTITIES:
        raise RuntimeError("Qwen acceptance gate schema identity has drifted")
    if any(
        source.get(name) != 0
        for name in ("mismatchCount", "fallbackCount", "unprovenCount")
    ):
        raise RuntimeError("Qwen acceptance gate provider-integrity counts are not zero")
    freeze_flags = source.get("freeze")
    if not isinstance(freeze_flags, dict) or not all(freeze_flags.values()):
        raise RuntimeError("Qwen acceptance gate source-freeze is not fully frozen")
    quality = _read_json(quality_gate)
    if quality.get("overall") != "PASS" or quality.get("formal105Status") != "NOT_RUN":
        raise RuntimeError("Qwen acceptance gate quality-gate is not PASS/NOT_RUN")
    quality_checks = quality.get("checks")
    if not isinstance(quality_checks, dict) or not quality_checks or not all(
        quality_checks.values()
    ):
        raise RuntimeError("Qwen acceptance gate quality checks are incomplete")
    return {
        "status": "PASS",
        "provider": "Qwen",
        "model": EXPECTED_QWEN_MODEL,
        "acceptanceArtifact": str(final_gate),
        "acceptanceDigest": _sha256_file(final_gate),
        "sourceFreezeArtifact": str(source_freeze),
        "sourceFreezeDigest": _sha256_file(source_freeze),
        "qualityGateArtifact": str(quality_gate),
        "qualityGateDigest": _sha256_file(quality_gate),
        "formal105Status": "NOT_RUN",
        "markers": {marker: "PASS" for marker in QWEN_GATE_MARKERS},
        "structuredOutputProfile": QWEN_SCHEMA_IDENTITIES,
    }


def _fixture_path(reference: str) -> Path:
    candidate = (MANIFEST_PATH.parent / reference).resolve()
    try:
        candidate.relative_to(MANIFEST_PATH.parent.resolve())
    except ValueError as exc:
        raise RuntimeError(f"dataset fixture path escapes manifest directory: {reference}") from exc
    return candidate


def _dataset_freeze(dataset: BenchmarkDataset, policy: OutcomePolicy) -> dict[str, object]:
    report = lint_dataset(MANIFEST_PATH)
    if not report.dataset_ready:
        codes = sorted({issue.code for issue in report.issues if issue.severity == "ERROR"})
        raise RuntimeError("dataset quality gate is not ready: " + ", ".join(codes))
    entries = tuple(dataset.manifest.tasks)
    task_ids = tuple(task.benchmark_task_id for task in dataset.tasks)
    manifest_ids = tuple(entry.benchmark_task_id for entry in entries)
    policy_ids = tuple(task.benchmark_task_id for task in policy.tasks)
    if len(task_ids) != FORMAL_TASK_COUNT or len(set(task_ids)) != FORMAL_TASK_COUNT:
        raise RuntimeError("Formal105 dataset must contain 105 unique task IDs")
    if task_ids != manifest_ids or set(policy_ids) != set(task_ids):
        raise RuntimeError("Formal105 dataset, manifest, and policy task IDs do not match")
    split_counts = Counter(entry.split.value.upper() for entry in entries)
    if (
        split_counts.get("DEV", 0) != EXPECTED_DEV_COUNT
        or split_counts.get("HELD_OUT", 0) != EXPECTED_HELD_OUT_COUNT
    ):
        raise RuntimeError("Formal105 split contract requires DEV=95 and HELD_OUT=10")
    task_paths = [
        (entry.benchmark_task_id, _fixture_path(entry.task_file)) for entry in entries
    ]
    truth_paths = [
        (
            f"{entry.ground_truth_ref.ground_truth_id}@{entry.ground_truth_ref.version}",
            _fixture_path(entry.ground_truth_file),
        )
        for entry in entries
    ]
    if any(not path.is_file() for _, path in (*task_paths, *truth_paths)):
        raise RuntimeError("Formal105 dataset references a missing task or GroundTruth file")
    review_counts = Counter(entry.review_status.value for entry in entries)
    if review_counts != Counter({"APPROVED": FORMAL_TASK_COUNT}):
        raise RuntimeError("Formal105 dataset requires APPROVED review status for every task")
    return {
        "datasetId": dataset.manifest.dataset_id,
        "datasetVersion": dataset.manifest.dataset_version,
        "schemaVersion": dataset.manifest.task_schema_version,
        "manifestDigest": _sha256_file(MANIFEST_PATH),
        "taskFilesDigest": _digest_paths(task_paths),
        "groundTruthDigest": _digest_paths(truth_paths),
        "orderedTaskIdsDigest": _digest_strings(task_ids),
        "policyTaskIdsDigest": _digest_strings(policy_ids),
        "taskCount": len(task_ids),
        "devCount": split_counts.get("DEV", 0),
        "heldOutCount": split_counts.get("HELD_OUT", 0),
        "splitCounts": dict(sorted(split_counts.items())),
        "reviewStatusCounts": dict(sorted(review_counts.items())),
        "groundTruthReferenceCount": len(dataset.ground_truths),
        "qualityGate": {
            "status": "PASS",
            "issueCount": len(report.issues),
            "blockingIssueCount": sum(issue.severity == "ERROR" for issue in report.issues),
        },
    }


def _evaluation_freeze(policy: OutcomePolicy) -> dict[str, object]:
    outcome_source = REPOSITORY_ROOT / "python-apiops-agentlab/app/benchmark/outcome_v2.py"
    evaluator_source = REPOSITORY_ROOT / "python-apiops-agentlab/app/evaluator/evaluator.py"
    semantic_source = (
        REPOSITORY_ROOT / "python-apiops-agentlab/app/benchmark/semantic_adjudication.py"
    )
    tool_source = REPOSITORY_ROOT / "python-apiops-agentlab/app/workflows/tool_planning.py"
    diagnosis_source = REPOSITORY_ROOT / "python-apiops-agentlab/app/agents/diagnosis.py"
    return {
        "evaluator": {
            "name": "RuleBasedEvaluator",
            "version": EVALUATOR_VERSION,
            "source": "python-apiops-agentlab/app/evaluator/evaluator.py",
            "digest": _sha256_file(evaluator_source),
        },
        "outcomePolicy": {
            "version": policy.policy_version,
            "datasetId": policy.dataset_id,
            "datasetVersion": policy.dataset_version,
            "taskSchemaVersion": policy.task_schema_version,
            "digest": _sha256_file(POLICY_PATH),
        },
        "semanticAdjudication": {
            "status": "NOT_APPLICABLE",
            "reason": (
                "existing Formal105 baseline constructs BenchmarkRunner without "
                "Judge configuration"
            ),
            "source": "python-apiops-agentlab/app/benchmark/semantic_adjudication.py",
            "digest": _sha256_file(semantic_source),
        },
        "toolPlanning": {
            "source": "python-apiops-agentlab/app/workflows/tool_planning.py",
            "digest": _sha256_file(tool_source),
        },
        "diagnosisSemanticValidator": {
            "source": "python-apiops-agentlab/app/agents/diagnosis.py",
            "digest": _sha256_file(diagnosis_source),
        },
        "safetyPolicy": {
            "source": "python-apiops-agentlab/app/evaluator/evaluator.py",
            "digest": _sha256_file(evaluator_source),
        },
        "v2Projector": {
            "schemaVersion": "stage21-outcome-v2-projection/v1",
            "source": "python-apiops-agentlab/app/benchmark/outcome_v2.py",
            "digest": _sha256_file(outcome_source),
        },
    }


def _runtime_preflight_evidence(path: Path) -> dict[str, object]:
    """Validate an existing Stage21 runtime audit; do not create a second harness."""

    candidate = path.resolve()
    run_path = candidate / "run.json" if candidate.is_dir() else candidate
    if not run_path.is_file():
        raise RuntimeError(f"runtime preflight run.json is missing: {run_path}")
    summary = _read_json(run_path)
    status = summary.get("status")
    pending = summary.get("pendingClassificationCount")
    non_ready = summary.get("nonReadyTaskIds")
    if status != "STAGE21_ALL_105_INPUT_AUDIT_COMPLETE" or pending != 0:
        raise RuntimeError(
            "runtime preflight is not complete: "
            f"status={status!r}, pendingClassificationCount={pending!r}"
        )
    if not isinstance(non_ready, list) or non_ready:
        raise RuntimeError(
            "runtime preflight is not ready for execution: "
            f"nonReadyTaskIds={non_ready!r}"
        )
    verification = summary.get("verification")
    if not isinstance(verification, dict):
        raise RuntimeError("runtime preflight verification is missing")
    unresolved = verification.get("unresolvedJavaResourceCount")
    if unresolved != 0:
        raise RuntimeError(
            "runtime preflight has unresolved Java resources: "
            f"unresolvedJavaResourceCount={unresolved!r}"
        )
    evidence: dict[str, object] = {
        "status": "PASS",
        "artifact": str(run_path),
        "artifactDigest": _sha256_file(run_path),
        "auditStatus": status,
        "pendingClassificationCount": pending,
        "classificationCounts": summary.get("classificationCounts", {}),
        "nonReadyTaskIds": (),
        "unresolvedJavaResourceCount": 0,
    }
    for name in (
        "runtime-probe-snapshot.json",
        "runtime-prerequisite-audit-verification.json",
    ):
        artifact = run_path.parent / name
        if artifact.is_file():
            evidence[name] = {
                "path": str(artifact),
                "digest": _sha256_file(artifact),
            }
    return evidence


def _freeze_manifest(
    settings: AppSettings,
    dataset: BenchmarkDataset,
    policy: OutcomePolicy,
    *,
    provider: str = "qwen",
    qwen_gate: dict[str, object] | None = None,
    environment_readiness: dict[str, object] | None = None,
    runtime_preflight: dict[str, object] | None = None,
    git_snapshot: dict[str, object] | None = None,
    frozen_at: str,
) -> dict[str, object]:
    _require_provider(provider)
    if settings.qwen_model != EXPECTED_QWEN_MODEL:
        raise RuntimeError("Qwen provider freeze model identity mismatch")
    if qwen_gate is None or qwen_gate.get("status") != "PASS":
        raise RuntimeError("Qwen acceptance gate is required before a Qwen freeze")
    model_provider = {"provider": "Qwen", "model": settings.qwen_model}
    model_parameters = {
        "responseFormat": "provider-specific",
        "structuredOutputProfile": qwen_gate.get(
            "structuredOutputProfile", QWEN_SCHEMA_IDENTITIES
        ),
        "enableThinking": False,
        "stream": False,
        "timeoutSeconds": settings.qwen_timeout_seconds,
    }
    dataset_identity = _dataset_freeze(dataset, policy)
    evaluation_identity = _evaluation_freeze(policy)
    git = git_snapshot or _git_snapshot()
    success_source = REPOSITORY_ROOT / "python-apiops-agentlab/app/benchmark/success.py"
    return {
        "schemaVersion": "stage21-final-formal105-freeze/v5",
        "finalRevision": BENCHMARK_CONTRACT_REVISION,
        "freezeStatus": "FROZEN_BEFORE_FORMAL105",
        "runtimeTimestamp": frozen_at,
        "sourceOfTruth": "local dirty worktree",
        "dataset": dataset_identity,
        "v2Policy": {
            "version": policy.policy_version,
            "digest": _sha256_file(POLICY_PATH),
            "taskCount": len(policy.tasks),
            "datasetId": policy.dataset_id,
            "datasetVersion": policy.dataset_version,
        },
        "v1PolicyIdentity": {
            "name": "evaluate_task_success / TaskSuccessResult",
            "source": "python-apiops-agentlab/app/benchmark/success.py",
            "digest": _sha256_file(success_source),
        },
        "ragCorpusV2": _corpus_freeze(),
        "modelProvider": model_provider,
        "modelParameters": model_parameters,
        "promptIdentities": _prompt_freeze(),
        "accuracyRepairContract": _accuracy_repair_contract_freeze(),
        "workflowIdentity": {
            "name": "RealModelStage20WorkflowAdapter",
            "version": baseline.WORKFLOW_VERSION,
        },
        "toolCatalogIdentity": {
            "name": "ToolCatalog",
            "version": baseline.TOOL_CATALOG_VERSION,
        },
        "evaluation": evaluation_identity,
        "stage19Evaluator": evaluation_identity["evaluator"],
        "v2Projector": evaluation_identity["v2Projector"],
        "providerGate": qwen_gate,
        **git,
        "pythonVersion": platform.python_version(),
        "javaVersion": _java_version(),
        "environmentReadiness": environment_readiness
        or _environment_readiness(settings, provider),
        "runtimePreflight": runtime_preflight
        or {"status": "NOT_PROVIDED"},
    }


def _metric_observation(result: BenchmarkTaskResult, name: str) -> object | None:
    if result.evaluation_result is None:
        return None
    return next(
        (metric for metric in result.evaluation_result.metrics if metric.metric.value == name),
        None,
    )


def _metric_json(metric: object | None) -> object:
    if metric is None:
        return {"status": "MISSING", "reason": "metric is absent"}
    return metric.model_dump(mode="json")  # type: ignore[attr-defined]


def _aggregate_metric(overall: dict[str, Any], name: str) -> dict[str, Any]:
    for metric in overall.get("metrics", []):
        if metric.get("metric") == name:
            return metric
    return {"metric": name, "status": "MISSING", "reason": "aggregate metric is absent"}


def _ground_truths(dataset: BenchmarkDataset) -> dict[str, object]:
    by_ref = {(item.ground_truth_id, item.version): item for item in dataset.ground_truths}
    return {
        task.benchmark_task_id: by_ref[
            (task.ground_truth_ref.ground_truth_id, task.ground_truth_ref.version)
        ]
        for task in dataset.tasks
    }


def _expected_deny(truth: object) -> bool:
    outcome = getattr(truth, "expected_safety_outcome", None)
    return getattr(outcome, "value", outcome) in EXPECTED_DENY_OUTCOMES


def _rate_json(rate: object) -> dict[str, Any]:
    return rate.model_dump(mode="json")  # type: ignore[attr-defined]


def _status_counts(values: list[str], names: tuple[str, ...]) -> dict[str, int]:
    counts = Counter(values)
    return {name: counts.get(name, 0) for name in names}


def _task_result_map(run: BenchmarkRun) -> dict[str, BenchmarkTaskResult]:
    return {result.benchmark_task_id: result for result in run.results}


def _tool_analysis(
    run: BenchmarkRun,
    projection: OutcomeV2Projection,
    dataset: BenchmarkDataset,
) -> dict[str, object]:
    results = _task_result_map(run)
    truths = _ground_truths(dataset)
    required_classes = Counter()
    required_rows: list[dict[str, object]] = []
    optional_rows: list[dict[str, object]] = []
    unsafe_task_ids: list[str] = []
    for task in projection.tasks:
        result = results[task.benchmark_task_id]
        expected_deny = _expected_deny(truths[task.benchmark_task_id])
        statuses_by_tool: dict[str, list[str]] = {}
        for observation in result.tool_result_observations:
            statuses_by_tool.setdefault(observation.tool_name, []).append(
                str(_enum_value(observation.status))
            )
        for requirement in task.tool_requirements:
            statuses = statuses_by_tool.get(requirement.tool_name, [])
            row = {
                "benchmarkTaskId": task.benchmark_task_id,
                "toolName": requirement.tool_name,
                "requirement": requirement.requirement.value,
                "invoked": requirement.invoked,
                "observedToolCallIds": list(requirement.observed_tool_call_ids),
                "toolResultStatuses": statuses,
                "expectedSecurityDeny": expected_deny,
            }
            if requirement.requirement.value == "REQUIRED":
                if not requirement.invoked:
                    classification = "NOT_CALLED_REQUIRED_MISS"
                elif expected_deny and "FORBIDDEN" in statuses:
                    classification = "CALLED_EXPECTED_DENY"
                elif "SUCCESS" in statuses:
                    classification = "CALLED_SUCCESS"
                else:
                    classification = "CALLED_TOOL_FAILURE"
                required_classes[classification] += 1
                row["classification"] = classification
                required_rows.append(row)
            elif requirement.requirement.value == "OPTIONAL":
                optional_rows.append(row)

        safety = _metric_observation(result, MetricName.SAFETY_ACCURACY.value)
        if (
            expected_deny
            and safety is not None
            and getattr(safety, "status", None) is MetricStatus.VALUE
            and float(getattr(safety, "value", 1.0)) == 0.0
        ):
            unsafe_task_ids.append(task.benchmark_task_id)

    required = projection.required_tool_count
    optional = projection.optional_tool_count
    overall = projection.tool_invocation_rate
    optional_rate = (
        _rate_json(
            type(overall)(
                status="VALUE",
                value=projection.optional_tool_invocation_count / optional,
                numerator=projection.optional_tool_invocation_count,
                denominator=optional,
                unknownCount=0,
            )
        )
        if optional
        else {"status": "NOT_APPLICABLE", "numerator": 0, "denominator": 0, "unknownCount": 0}
    )
    return {
        "schemaVersion": "stage21-tool-use-analysis/v1",
        "required": {
            "count": required,
            "invoked": projection.required_tool_invocation_count,
            "miss": projection.required_tool_miss_count,
            "coverage": _rate_json(
                type(projection.required_tool_miss_rate)(
                    status="VALUE",
                    value=(
                        projection.required_tool_invocation_count / required
                        if required
                        else None
                    ),
                    numerator=projection.required_tool_invocation_count,
                    denominator=required,
                    unknownCount=0,
                )
                if required
                else projection.required_tool_miss_rate
            ),
            "missRate": _rate_json(projection.required_tool_miss_rate),
            "classificationCounts": dict(sorted(required_classes.items())),
        },
        "optional": {
            "count": optional,
            "invoked": projection.optional_tool_invocation_count,
            "invocationRate": optional_rate,
        },
        "overall": {"invocationRate": _rate_json(overall)},
        "requiredTaskDetails": required_rows,
        "optionalTaskDetails": optional_rows,
        "expectedDeny": {
            "taskCount": sum(_expected_deny(truth) for truth in truths.values()),
            "observedExpectedDeny": required_classes["CALLED_EXPECTED_DENY"],
        },
        "unexpectedUnsafeBehavior": {
            "count": len(unsafe_task_ids),
            "taskIds": unsafe_task_ids,
        },
    }


def _classification_by_task(tool_analysis: dict[str, object]) -> dict[str, str]:
    rows = tool_analysis["requiredTaskDetails"]
    return {str(row["benchmarkTaskId"]): str(row["classification"]) for row in rows}  # type: ignore[index]


def _failure_taxonomy(
    run: BenchmarkRun,
    projection: OutcomeV2Projection,
    tool_analysis: dict[str, object],
    dataset: BenchmarkDataset,
) -> dict[str, object]:
    results = _task_result_map(run)
    projected = {item.benchmark_task_id: item for item in projection.tasks}
    truths = _ground_truths(dataset)
    required_class = _classification_by_task(tool_analysis)
    category_ids: dict[str, list[str]] = {name: [] for name in TAXONOMY_CATEGORIES}
    for task_id, result in results.items():
        task_projection = projected[task_id]
        statuses = {
            str(_enum_value(observation.status))
            for observation in result.tool_result_observations
        }
        text = " ".join(
            str(value or "")
            for value in (result.failure_code, result.failure_category, result.error_summary)
        ).upper()
        category: str | None = None
        if required_class.get(task_id) == "NOT_CALLED_REQUIRED_MISS":
            category = "REQUIRED_TOOL_MISS"
        elif result.java_execution_status is JavaExecutionStatus.EXECUTION_FAILED:
            category = "JAVA_REQUIRED_PATH"
        elif any(marker in text for marker in ("PROVIDER", "DEEPSEEK", "RATE_LIMIT")):
            category = "PROVIDER"
        elif any(marker in text for marker in ("MODEL", "STRUCTURED_OUTPUT", "PARSE")):
            category = "MODEL_OUTPUT"
        elif _expected_deny(truths[task_id]) and "FORBIDDEN" in statuses:
            category = "AUTHORIZATION"
        elif statuses and statuses - {"SUCCESS"}:
            category = "TOOL_EXECUTION"
        elif task_projection.outcome_authority_gap:
            category = "EVALUATION_AUTHORITY"
        elif result.status is not BenchmarkTaskStatus.SUCCESS:
            category = (
                "INFRASTRUCTURE"
                if str(result.failure_category or "").upper()
                in {"INFRASTRUCTURE_FAILURE", "SETUP_FAILURE", "TIMEOUT", "CLEANUP_FAILURE"}
                else "OTHER"
            )
        if category is not None:
            category_ids[category].append(task_id)
    return {
        "schemaVersion": "stage21-failure-taxonomy/v1",
        "categories": {
            name: {"count": len(category_ids[name]), "taskIds": category_ids[name]}
            for name in TAXONOMY_CATEGORIES
        },
        "uncategorizedTaskCount": sum(
            1 for task_id in results if not any(task_id in ids for ids in category_ids.values())
        ),
    }


def _numeric_fact_stats(results: tuple[BenchmarkTaskResult, ...], field: str) -> dict[str, object]:
    values = [
        float(getattr(result, field))
        for result in results
        if getattr(result, field) is not None
    ]
    return {
        "status": "VALUE" if values else "UNKNOWN",
        "count": len(values),
        "unknownCount": len(results) - len(values),
        "sum": sum(values) if values else None,
        "mean": (sum(values) / len(values)) if values else None,
    }


def _category_summary(
    run: BenchmarkRun,
    projection: OutcomeV2Projection,
    dataset: BenchmarkDataset,
    tool_analysis: dict[str, object],
) -> dict[str, object]:
    task_splits = {
        entry.benchmark_task_id: entry.split.value.upper()
        for entry in dataset.manifest.tasks
    }
    result_by_id = _task_result_map(run)
    projection_by_id = {task.benchmark_task_id: task for task in projection.tasks}
    required_rows = {
        str(row["benchmarkTaskId"]): row for row in tool_analysis["requiredTaskDetails"]  # type: ignore[index]
    }
    output: dict[str, object] = {}
    for split in ("DEV", "HELD_OUT"):
        ids = [task_id for task_id, value in task_splits.items() if value == split]
        split_results = [result_by_id[task_id] for task_id in ids]
        split_tasks = [projection_by_id[task_id] for task_id in ids]
        output[split] = {
            "taskCount": len(ids),
            "runtimeStatus": dict(
                Counter(result.status.value for result in split_results)
            ),
            "v1StrictTaskSuccess": dict(
                Counter(
                    result.task_success.status.value
                    if result.task_success is not None
                    else TaskSuccessStatus.UNKNOWN.value
                    for result in split_results
                )
            ),
            "v2Outcome": dict(Counter(task.v2_status.value for task in split_tasks)),
            "outcomeAccuracy": _rate_from_tasks(split_tasks),
            "requiredToolMiss": sum(
                row.get("classification") == "NOT_CALLED_REQUIRED_MISS"
                for row in (required_rows.get(task_id, {}) for task_id in ids)
            ),
        }
    return output


def _rate_from_tasks(tasks: list[object]) -> dict[str, object]:
    passes = sum(getattr(task, "v2_status").value == "PASS" for task in tasks)
    fails = sum(getattr(task, "v2_status").value == "FAIL" for task in tasks)
    unknown = sum(getattr(task, "v2_status").value == "UNKNOWN" for task in tasks)
    denominator = passes + fails
    return {
        "status": "VALUE" if denominator else "NOT_APPLICABLE",
        "value": passes / denominator if denominator else None,
        "numerator": passes,
        "denominator": denominator,
        "unknownCount": unknown,
    }


def _baseline_record(run_path: Path) -> dict[str, Any]:
    path = run_path.parent / "baseline-run.json"
    if not path.is_file():
        raise RuntimeError(f"persisted baseline record is missing: {path}")
    return _read_json(path)


def _persist_task_results(
    output_root: Path,
    run: BenchmarkRun,
    *,
    provider: str | None = None,
    model: str | None = None,
) -> int:
    task_root = output_root / "task-results"
    task_root.mkdir(parents=True, exist_ok=True)
    for result in run.results:
        payload = result.model_dump(mode="json")
        if provider is not None and model is not None:
            payload.update(
                {
                    "provider": provider,
                    "model": model,
                    "providerIdentitySource": "frozen-final-run-configuration",
                }
            )
        _write_json(
            task_root / physical_task_result_filename(
                run.evaluation_run_id,
                result.benchmark_task_id,
            ),
            payload,
        )
    return len(list(task_root.glob("*.json")))


def _find_run(output_root: Path) -> Path:
    candidates = sorted((output_root / "full-105" / "results").glob("*/run.json"))
    if len(candidates) != 1:
        raise RuntimeError(
            "Formal105 output must contain exactly one run.json; found "
            f"{len(candidates)} under {output_root / 'full-105' / 'results'}"
        )
    return candidates[0]


def _outcome_metrics(projection: OutcomeV2Projection) -> dict[str, object]:
    counts = {
        "PASS": projection.v2_status_counts.get("PASS", 0),
        "FAIL": projection.v2_status_counts.get("FAIL", 0),
        "UNKNOWN": projection.v2_status_counts.get("UNKNOWN", 0),
    }
    total = sum(counts.values())
    decisive = counts["PASS"] + counts["FAIL"]
    return {
        **{name.lower(): value for name, value in counts.items()},
        "total": total,
        "outcomeAccuracy": counts["PASS"] / decisive if decisive else None,
        "decisiveCoverage": decisive / total if total else None,
        "unknownRate": counts["UNKNOWN"] / total if total else None,
    }


def _task_type_results(projection: OutcomeV2Projection) -> dict[str, object]:
    names = (
        "TESTCASE_GENERATION",
        "FAILURE_DIAGNOSIS",
        "TOOL_SAFETY",
        "RAG_EVIDENCE_RETRIEVAL",
        "E2E_APIOPS",
    )
    values: dict[str, object] = {}
    for name in names:
        tasks = [task for task in projection.tasks if task.task_type.value == name]
        counts = Counter(task.v2_status.value for task in tasks)
        passed = counts.get("PASS", 0)
        failed = counts.get("FAIL", 0)
        unknown = counts.get("UNKNOWN", 0)
        decisive = passed + failed
        values[name] = {
            "taskCount": len(tasks),
            "PASS": passed,
            "FAIL": failed,
            "UNKNOWN": unknown,
            "outcomeAccuracy": passed / decisive if decisive else None,
            "decisiveCoverage": decisive / len(tasks) if tasks else None,
            "unknownRate": unknown / len(tasks) if tasks else None,
        }
    return values


def _provider_evidence(
    output_root: Path,
    run_path: Path,
    run: BenchmarkRun,
    freeze: dict[str, object],
) -> dict[str, object]:
    expected = freeze.get("modelProvider", {})
    configured_provider = expected.get("provider") if isinstance(expected, dict) else None
    configured_model = expected.get("model") if isinstance(expected, dict) else None
    config_path = run_path.parent / "baseline-config.json"
    config = _read_json(config_path)
    model_identity = config.get("modelIdentity", {})
    baseline_identity = (
        model_identity.get("value", {}) if isinstance(model_identity, dict) else {}
    )
    baseline_provider = (
        baseline_identity.get("provider") if isinstance(baseline_identity, dict) else None
    )
    baseline_model = (
        baseline_identity.get("model") if isinstance(baseline_identity, dict) else None
    )
    integrity = verify_provider_integrity(
        run.results,
        expected_provider=str(configured_provider or ""),
        expected_model=str(configured_model or ""),
    )
    configuration_mismatch = (
        configured_provider != baseline_provider or configured_model != baseline_model
    )
    if configuration_mismatch:
        integrity = {
            **integrity,
            "status": "PROVIDER_MISMATCH",
            "configurationMismatch": True,
            "silentFallbackDetected": False,
        }
    return {
        "expectedProvider": configured_provider,
        "expectedModel": configured_model,
        "qwenProviderChain": freeze.get("providerGate", {}).get("markers", {}).get(
            "QWEN_PROVIDER_CHAIN = PASS", "UNKNOWN"
        )
        if isinstance(freeze.get("providerGate"), dict)
        else "UNKNOWN",
        "qwenRuntimeWiring": freeze.get("providerGate", {}).get("markers", {}).get(
            "QWEN_RUNTIME_WIRING = PASS", "UNKNOWN"
        )
        if isinstance(freeze.get("providerGate"), dict)
        else "UNKNOWN",
        "qwenDiagnosisSemantic": freeze.get("providerGate", {}).get("markers", {}).get(
            "QWEN_DIAGNOSIS_SEMANTIC = PASS", "UNKNOWN"
        )
        if isinstance(freeze.get("providerGate"), dict)
        else "UNKNOWN",
        "qwenTestCasePositive": freeze.get("providerGate", {}).get("markers", {}).get(
            "QWEN_TESTCASE_NATIVE_POSITIVE = PASS", "UNKNOWN"
        )
        if isinstance(freeze.get("providerGate"), dict)
        else "UNKNOWN",
        "qwenTestCaseIntentionalInvalid": freeze.get("providerGate", {})
        .get("markers", {})
        .get("QWEN_TESTCASE_NATIVE_INTENTIONAL_INVALID = PASS", "UNKNOWN")
        if isinstance(freeze.get("providerGate"), dict)
        else "UNKNOWN",
        "configuredFormalProvider": configured_provider,
        "configuredFormalModel": configured_model,
        "baselineConfiguredProvider": baseline_provider,
        "baselineConfiguredModel": baseline_model,
        "tasksWithModelCalls": sum(bool(result.model_call_ids) for result in run.results),
        "totalModelCalls": sum(result.model_call_count for result in run.results),
        "tasksMissingModelCalls": integrity["noModelCallTaskIds"],
        "observedProviderIdentityStatus": integrity["status"],
        "providerIntegrityStatus": integrity["status"],
        "identitySource": (
            "persisted ModelCall terminal trace plus provider response metadata"
        ),
        "silentFallbackDetected": integrity["silentFallbackDetected"],
        "providerIntegrity": integrity,
        "acceptanceArtifact": freeze.get("providerGate", {}).get("acceptanceArtifact")
        if isinstance(freeze.get("providerGate"), dict)
        else None,
        "acceptanceDigest": freeze.get("providerGate", {}).get("acceptanceDigest")
        if isinstance(freeze.get("providerGate"), dict)
        else None,
        "qualityGateArtifact": freeze.get("providerGate", {}).get("qualityGateArtifact")
        if isinstance(freeze.get("providerGate"), dict)
        else None,
        "qualityGateDigest": freeze.get("providerGate", {}).get("qualityGateDigest")
        if isinstance(freeze.get("providerGate"), dict)
        else None,
        "outputRoot": str(output_root.resolve()),
    }


def _formal_summary(
    output_root: Path,
    run_path: Path,
    run: BenchmarkRun,
    projection: OutcomeV2Projection,
    baseline_record: dict[str, Any],
    tool_analysis: dict[str, object],
    taxonomy: dict[str, object],
    categories: dict[str, object],
    freeze: dict[str, object],
    rag_acceptance: dict[str, Any],
    task_artifact_count: int,
) -> dict[str, object]:
    overall = baseline_record["overallMetrics"]
    v1_values = [
        result.task_success.status.value
        if result.task_success is not None
        else TaskSuccessStatus.UNKNOWN.value
        for result in run.results
    ]
    status_values = [result.status.value for result in run.results]
    fixture_reports = [
        result.benchmark_task_id
        for result in run.results
        if result.report_id is not None and result.report_id.startswith("fixture:")
    ]
    required_classification = tool_analysis["required"]["classificationCounts"]  # type: ignore[index]
    systemic = bool(
        run.aborted
        or len(run.selected_task_ids) != FORMAL_TASK_COUNT
        or len(run.results) != FORMAL_TASK_COUNT
        or task_artifact_count != FORMAL_TASK_COUNT
        or not any(result.model_call_ids for result in run.results)
        or all(
            str(result.failure_category or "").upper()
            in {"INFRASTRUCTURE_FAILURE", "SETUP_FAILURE", "TIMEOUT", "CLEANUP_FAILURE"}
            for result in run.results
        )
    )
    baseline_frozen = not systemic and not fixture_reports
    return {
        "schemaVersion": "stage21-final-v2-formal105-summary/v1",
        "sourceArtifact": str(run_path),
        "freezeManifest": str(output_root / "freeze-manifest.json"),
        "evaluationRunId": run.evaluation_run_id,
        "selected": len(run.selected_task_ids),
        "executed": len(run.results),
        "persistedTaskArtifacts": task_artifact_count,
        "runtimeStatus": _status_counts(
            status_values, ("SUCCESS", "FAILED", "TIMEOUT", "ABORTED")
        ),
        "v2Outcome": {
            **_status_counts(
                [value for value in (item.v2_status.value for item in projection.tasks)],
                ("PASS", "FAIL", "UNKNOWN"),
            ),
            "NOT_APPLICABLE": 0,
        },
        "outcomeAccuracy": _rate_json(projection.outcome_accuracy),
        "outcomeMetrics": _outcome_metrics(projection),
        "v1StrictTaskSuccess": _status_counts(
            v1_values, ("PASS", "FAIL", "UNKNOWN", "NOT_APPLICABLE")
        ),
        "toolUse": {
            "TOOL_REQUIRED": projection.required_tool_count,
            "Required Tool Invoked": projection.required_tool_invocation_count,
            "Required Tool Miss": projection.required_tool_miss_count,
            "Required Tool Coverage": tool_analysis["required"]["coverage"],  # type: ignore[index]
            "Required Tool Miss Rate": _rate_json(projection.required_tool_miss_rate),
            "OPTIONAL tasks": projection.optional_tool_count,
            "Optional Tool Invocation Rate": tool_analysis["optional"]["invocationRate"],  # type: ignore[index]
            "overall Tool Invocation Rate": _rate_json(projection.tool_invocation_rate),
            "classificationCounts": required_classification,
        },
        "evaluationMetrics": {
            name: _aggregate_metric(overall, name)
            for name in (
                MetricName.TOOL_PRECISION.value,
                MetricName.TOOL_RECALL.value,
                MetricName.PARAMETER_ACCURACY.value,
                MetricName.EVIDENCE_HIT.value,
                MetricName.DIAGNOSIS_ACCURACY.value,
                MetricName.SAFETY_ACCURACY.value,
            )
        },
        "evidenceHit": {
            "formal105": _aggregate_metric(overall, MetricName.EVIDENCE_HIT.value),
            "deterministicRag": rag_acceptance.get("metrics", {}),
        },
        "expectedDeny": tool_analysis["expectedDeny"],  # type: ignore[index]
        "unexpectedUnsafeBehavior": tool_analysis["unexpectedUnsafeBehavior"],  # type: ignore[index]
        "collateralDamage": baseline_record.get("collateralDamage", {}),
        "model": {
            "tasksWithModelCalls": sum(bool(result.model_call_ids) for result in run.results),
            "totalModelCalls": sum(result.model_call_count for result in run.results),
            "latency": _numeric_fact_stats(tuple(run.results), "model_latency_ms"),
            "promptTokens": _numeric_fact_stats(tuple(run.results), "prompt_tokens"),
            "completionTokens": _numeric_fact_stats(tuple(run.results), "completion_tokens"),
            "totalTokens": _numeric_fact_stats(tuple(run.results), "total_tokens"),
            "cost": _aggregate_metric(overall, MetricName.COST.value),
        },
        "categories": categories,
        "taskTypeResults": _task_type_results(projection),
        "fiveCategories": baseline_record.get("categoryMetrics", []),
        "failureTaxonomy": taxonomy,
        "boundaryChecks": {
            "fixtureFallback": {"observedCount": len(fixture_reports), "taskIds": fixture_reports},
            "pythonBypass": False,
            "realResultPersistence": task_artifact_count == FORMAL_TASK_COUNT,
            "systemicInfrastructureBlocker": systemic,
        },
        "baselineFrozen": baseline_frozen,
        "preFormalReadinessEvidence": {
            "targetedToolSummary": str(TARGETED_SUMMARY_PATH),
            "authorityClosure": str(AUTHORITY_CLOSURE_PATH),
            "ragAcceptance": str(RAG_ACCEPTANCE_PATH),
        },
        "freeze": freeze,
    }


def _run_manifest(
    freeze: dict[str, object],
    run: BenchmarkRun,
    *,
    command: str | None,
) -> dict[str, object]:
    model_provider = freeze.get("modelProvider", {})
    provider_gate = freeze.get("providerGate", {})
    dataset = freeze.get("dataset", {})
    evaluation = freeze.get("evaluation", {})
    rag = freeze.get("ragCorpusV2", {})
    return {
        "schemaVersion": "stage21-final-formal105-run/v1",
        "evaluationRunId": run.evaluation_run_id,
        "startedAt": run.started_at.isoformat(),
        "completedAt": run.completed_at.isoformat(),
        "source": {
            "HEAD": freeze.get("gitHead"),
            "branch": freeze.get("branch"),
            "workingTreeDirty": freeze.get("workingTreeDirty"),
            "dirtyDiffDigest": freeze.get("dirtyDiffDigest"),
            "trackedDirtyPathDigest": freeze.get("trackedDirtyPathDigest"),
            "untrackedPathDigest": freeze.get("untrackedPathDigest"),
        },
        "dataset": {
            "datasetId": dataset.get("datasetId"),
            "datasetVersion": dataset.get("datasetVersion"),
            "schemaVersion": dataset.get("schemaVersion"),
            "taskCount": dataset.get("taskCount"),
            "devCount": dataset.get("devCount"),
            "heldOutCount": dataset.get("heldOutCount"),
            "manifestDigest": dataset.get("manifestDigest"),
            "tasksDigest": dataset.get("taskFilesDigest"),
            "groundTruthDigest": dataset.get("groundTruthDigest"),
        },
        "evaluation": {
            "evaluatorVersion": freeze.get("stage19Evaluator", {}).get("version")
            if isinstance(freeze.get("stage19Evaluator"), dict)
            else None,
            "evaluatorDigest": evaluation.get("evaluator", {}).get("digest")
            if isinstance(evaluation.get("evaluator"), dict)
            else None,
            "outcomePolicyVersion": freeze.get("v2Policy", {}).get("version")
            if isinstance(freeze.get("v2Policy"), dict)
            else None,
            "outcomePolicyDigest": freeze.get("v2Policy", {}).get("digest")
            if isinstance(freeze.get("v2Policy"), dict)
            else None,
            "semanticAdjudicationDigest": evaluation.get("semanticAdjudication", {}).get(
                "digest"
            )
            if isinstance(evaluation.get("semanticAdjudication"), dict)
            else None,
        },
        "provider": {
            "provider": model_provider.get("provider")
            if isinstance(model_provider, dict)
            else None,
            "model": model_provider.get("model") if isinstance(model_provider, dict) else None,
            "acceptanceArtifact": provider_gate.get("acceptanceArtifact")
            if isinstance(provider_gate, dict)
            else None,
            "acceptanceDigest": provider_gate.get("acceptanceDigest")
            if isinstance(provider_gate, dict)
            else None,
        },
        "prompt": {
            "identities": freeze.get("promptIdentities", []),
        },
        "rag": {
            "corpusVersion": rag.get("corpusVersion") if isinstance(rag, dict) else None,
            "acceptanceDigest": rag.get("acceptanceDigest") if isinstance(rag, dict) else None,
            "threshold": rag.get("threshold") if isinstance(rag, dict) else None,
        },
        "runtime": {
            "workflow": freeze.get("workflowIdentity"),
            "toolCatalog": freeze.get("toolCatalogIdentity"),
            "pythonVersion": freeze.get("pythonVersion"),
            "javaVersion": freeze.get("javaVersion"),
            "preflight": freeze.get("runtimePreflight"),
        },
        "execution": {
            "selected": len(run.selected_task_ids),
            "executed": len(run.results),
            "persisted": len(run.results),
            "aborted": run.aborted,
        },
        "exactCommand": command,
    }


def _artifact_inventory(
    output_root: Path,
    *,
    excluded_names: Iterable[str] = (),
) -> list[dict[str, object]]:
    excluded = set(excluded_names)
    values: list[dict[str, object]] = []
    for path in sorted(item for item in output_root.rglob("*") if item.is_file()):
        relative = path.relative_to(output_root).as_posix()
        if relative in excluded:
            continue
        values.append(
            {
                "path": relative,
                "sha256": _sha256_file(path),
                "bytes": path.stat().st_size,
            }
        )
    return values


def _reproducibility_record(
    freeze: dict[str, object],
    run: BenchmarkRun,
    *,
    command: str | None,
    artifact_inventory: list[dict[str, object]],
) -> dict[str, object]:
    model_provider = freeze.get("modelProvider", {})
    return {
        "schemaVersion": "stage21-final-formal105-reproducibility/v1",
        "source": {
            "HEAD": freeze.get("gitHead"),
            "branch": freeze.get("branch"),
            "workingTreeDirty": freeze.get("workingTreeDirty"),
            "dirtyDiffDigest": freeze.get("dirtyDiffDigest"),
            "gitDiffBinarySha256": freeze.get("gitDiffBinarySha256"),
            "trackedDirtyPathDigest": freeze.get("trackedDirtyPathDigest"),
            "untrackedPathDigest": freeze.get("untrackedPathDigest"),
        },
        "dataset": freeze.get("dataset"),
        "policy": freeze.get("v2Policy"),
        "prompt": freeze.get("promptIdentities"),
        "rag": freeze.get("ragCorpusV2"),
        "provider": model_provider,
        "runtime": {
            "pythonVersion": freeze.get("pythonVersion"),
            "javaVersion": freeze.get("javaVersion"),
            "preflight": freeze.get("runtimePreflight"),
        },
        "exactCommand": command,
        "environmentReadiness": freeze.get("environmentReadiness"),
        "execution": {
            "evaluationRunId": run.evaluation_run_id,
            "selected": len(run.selected_task_ids),
            "executed": len(run.results),
            "persisted": len(run.results),
        },
        "artifactInventory": artifact_inventory,
        "inventoryExcludes": [
            "reproducibility.json",
            "final-acceptance.md",
            "stage21-final-acceptance.md",
        ],
    }


def _known_secret_values(settings: AppSettings | None = None) -> tuple[str, ...]:
    values: list[str] = []
    if settings is not None:
        for name in ("qwen_api_key", "deepseek_api_key", "java_apiops_token"):
            value = getattr(settings, name, None)
            getter = getattr(value, "get_secret_value", None)
            if callable(getter):
                text = getter().strip()
                if text:
                    values.append(text)
    for name, value in os.environ.items():
        upper = name.upper()
        if any(marker in upper for marker in ("API_KEY", "PASSWORD", "TOKEN", "SECRET")):
            if value.strip():
                values.append(value.strip())
    return tuple(dict.fromkeys(values))


def _render_formal_summary(summary: dict[str, object]) -> str:
    tool = summary["toolUse"]
    runtime = summary["runtimeStatus"]
    v2 = summary["v2Outcome"]
    v1 = summary["v1StrictTaskSuccess"]
    lines = [
        "# Stage21 V2 Formal105",
        "",
        "This is the single clean Formal105 execution after the pre-run freeze. "
        "The run uses the existing BenchmarkRunner, workflow adapter, and Stage 19 evaluator.",
        "",
        f"- Evaluation run: `{summary['evaluationRunId']}`",
        f"- Selected / executed / persisted task artifacts: `{summary['selected']} / "
        f"{summary['executed']} / {summary['persistedTaskArtifacts']}`",
        f"- Runtime SUCCESS / FAILED / TIMEOUT / ABORTED: `{runtime['SUCCESS']} / "
        f"{runtime['FAILED']} / {runtime['TIMEOUT']} / {runtime['ABORTED']}`",
        f"- V2 PASS / FAIL / UNKNOWN / N/A: `{v2['PASS']} / {v2['FAIL']} / "
        f"{v2['UNKNOWN']} / {v2['NOT_APPLICABLE']}`",
        f"- Outcome Accuracy: `{summary['outcomeAccuracy']}`",
        f"- V1 Strict PASS / FAIL / UNKNOWN / N/A: `{v1['PASS']} / {v1['FAIL']} / "
        f"{v1['UNKNOWN']} / {v1['NOT_APPLICABLE']}`",
        "",
        "## Tool-use",
        "",
        f"- TOOL_REQUIRED: `{tool['TOOL_REQUIRED']}`",
        f"- Required Tool Invoked / Miss: `"
        f"{tool['Required Tool Invoked']} / {tool['Required Tool Miss']}`",
        f"- Required Tool Coverage: `{tool['Required Tool Coverage']}`",
        f"- Required Tool Miss Rate: `{tool['Required Tool Miss Rate']}`",
        f"- OPTIONAL tasks: `{tool['OPTIONAL tasks']}`",
        f"- Optional Tool Invocation Rate: `{tool['Optional Tool Invocation Rate']}`",
        f"- Overall Tool Invocation Rate: `{tool['overall Tool Invocation Rate']}`",
        f"- Classification: `{tool['classificationCounts']}`",
        "",
        "## Existing Stage 19 metrics",
        "",
        f"- Tool Precision: `{summary['evaluationMetrics']['tool_precision']}`",
        f"- Tool Recall: `{summary['evaluationMetrics']['tool_recall']}`",
        f"- Parameter Accuracy: `{summary['evaluationMetrics']['parameter_accuracy']}`",
        f"- Evidence Hit: `{summary['evidenceHit']}`",
        f"- Diagnosis Accuracy: `{summary['evaluationMetrics']['diagnosis_accuracy']}`",
        f"- Safety Accuracy: `{summary['evaluationMetrics']['safety_accuracy']}`",
        f"- Expected DENY: `{summary['expectedDeny']}`",
        f"- Unexpected unsafe behavior: `{summary['unexpectedUnsafeBehavior']}`",
        f"- Collateral Damage: `{summary['collateralDamage']}`",
        "",
        "## DEV / HELD_OUT",
        "",
        "```json\n"
        f"{json.dumps(summary['categories'], ensure_ascii=False, indent=2, sort_keys=True)}"
        "\n```",
        "",
        "## Five task categories",
        "",
        "This section reuses the existing Stage 19 category aggregate; "
        "it does not redefine metric formulas.",
        "",
        "```json\n"
        f"{json.dumps(summary['fiveCategories'], ensure_ascii=False, indent=2, sort_keys=True)}"
        "\n```",
        "",
        "## Model usage",
        "",
        "```json\n"
        f"{json.dumps(summary['model'], ensure_ascii=False, indent=2, sort_keys=True)}"
        "\n```",
        "",
        "## Failure taxonomy",
        "",
        "```json\n"
        f"{json.dumps(summary['failureTaxonomy'], ensure_ascii=False, indent=2, sort_keys=True)}"
        "\n```",
        "",
        f"- BASELINE_FROZEN: `{summary['baselineFrozen']}`",
    ]
    return "\n".join(lines) + "\n"


def _final_verdict(
    summary: dict[str, object],
    provider_evidence: dict[str, object],
    *,
    rag: dict[str, Any],
    authority: dict[str, Any],
    leakage_paths: list[Path],
) -> str:
    boundary = summary["boundaryChecks"]
    freeze = summary["freeze"]
    runtime = freeze.get("runtimePreflight", {})
    authority_summary = authority.get("summary", {})
    model_provider = freeze.get("modelProvider", {})
    selected_provider = model_provider.get("provider") if isinstance(model_provider, dict) else None
    provider_gate = freeze.get("providerGate", {})
    provider_gate_pass = (
        provider_gate.get("status") == "PASS"
        if selected_provider == "Qwen" and isinstance(provider_gate, dict)
        else provider_gate.get("status") == "NOT_APPLICABLE"
        if isinstance(provider_gate, dict)
        else False
    )
    integrity_pass = all(
        (
            summary["selected"] == FORMAL_TASK_COUNT,
            summary["executed"] == FORMAL_TASK_COUNT,
            summary["persistedTaskArtifacts"] == FORMAL_TASK_COUNT,
            not bool(boundary["systemicInfrastructureBlocker"]),  # type: ignore[index]
            bool(summary["baselineFrozen"]),
            provider_evidence.get("providerIntegrityStatus") == "PROVIDER_PROVEN",
            provider_evidence.get("silentFallbackDetected") is False,
            selected_provider in {"Qwen", "DeepSeek"},
            bool(model_provider.get("model")) if isinstance(model_provider, dict) else False,
            rag.get("readiness") == "PASS",
            rag.get("threshold") == 0.516365,
            not leakage_paths,
            provider_gate_pass,
            runtime.get("status") == "PASS" if isinstance(runtime, dict) else False,
            authority_summary.get("unexplainedAuthorityGap") == 0,
            authority_summary.get("missingV2MetricMapping") == 0,
            boundary.get("pythonBypass") is False,  # type: ignore[union-attr]
        )
    )
    if not integrity_pass:
        return "FAIL"
    performance_limited = bool(
        summary["outcomeMetrics"].get("unknown", 0)  # type: ignore[union-attr]
        or summary["toolUse"]["Required Tool Miss"]  # type: ignore[index]
        or summary["unexpectedUnsafeBehavior"].get("count", 0)  # type: ignore[union-attr]
        or summary["outcomeMetrics"].get("outcomeAccuracy") not in {1.0, None}  # type: ignore[union-attr]
    )
    return "PASS_WITH_LIMITATIONS" if performance_limited else "PASS"


def _render_final_acceptance(
    summary: dict[str, object],
    *,
    authority: dict[str, Any],
    targeted: dict[str, Any],
    rag: dict[str, Any],
    provider_evidence: dict[str, object],
    runtime_preflight: dict[str, object],
    verdict: str,
    leakage_paths: list[Path],
    artifact_names: list[str],
    reproducibility: dict[str, object],
) -> str:
    def json_block(value: object) -> str:
        return "```json\n" + json.dumps(
            value,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ) + "\n```"

    freeze = summary["freeze"]
    execution = {
        "evaluationRunId": summary["evaluationRunId"],
        "selected": summary["selected"],
        "executed": summary["executed"],
        "persisted": summary["persistedTaskArtifacts"],
    }
    authority_summary = authority.get("summary", {})
    rag_summary = {
        "readiness": rag.get("readiness"),
        "threshold": rag.get("threshold"),
        "metrics": rag.get("metrics", {}),
        "citationMismatches": rag.get("citationMismatches"),
        "projectIsolationViolations": rag.get("projectIsolationViolations"),
    }
    freeze_identity = {
        "source": freeze.get("sourceOfTruth"),
        "HEAD": freeze.get("gitHead"),
        "branch": freeze.get("branch"),
        "workingTreeDirty": freeze.get("workingTreeDirty"),
        "dirtyDiffDigest": freeze.get("dirtyDiffDigest"),
        "provider": freeze.get("modelProvider"),
    }
    limitations = {
        "outcomeMetrics": summary["outcomeMetrics"],
        "requiredToolMiss": summary["toolUse"]["Required Tool Miss"],
        "unexpectedUnsafeBehavior": summary["unexpectedUnsafeBehavior"],
    }
    status = (
        "COMPLETED"
        if execution["selected"] == FORMAL_TASK_COUNT
        and execution["executed"] == FORMAL_TASK_COUNT
        and execution["persisted"] == FORMAL_TASK_COUNT
        else "BLOCKED"
    )
    tool_metrics = {
        "tool": summary["toolUse"],
        "evaluation": summary["evaluationMetrics"],
        "evidenceHit": summary["evidenceHit"],
        "expectedDeny": summary["expectedDeny"],
        "unexpectedUnsafeBehavior": summary["unexpectedUnsafeBehavior"],
    }
    integrity = {
        "heldoutTuning": "NO",
        "groundTruthLeakage": "NO",
        "secretLeakagePaths": [str(path) for path in leakage_paths],
        "securityWeakening": "NO",
        "postScoreTuning": "NO",
        "pythonBypass": summary["boundaryChecks"]["pythonBypass"],
    }
    lines = [
        "# Stage21 Final Formal105 Acceptance",
        "",
        "## 1. Current State",
        "",
        "This acceptance uses the existing provider-neutral Formal105 wrapper and "
        "existing provider-neutral baseline Runner. No parallel Qwen runner or pipeline was used.",
        "",
        "## 2. Freeze Identity",
        "",
        json_block(freeze_identity),
        "",
        "## 3. Dataset / GroundTruth",
        "",
        json_block(freeze.get("dataset", {})),
        (
            "GroundTruth contents are not copied into the final artifact; only references "
            "and digests are frozen."
        ),
        "",
        "## 4. Evaluation / Outcome Policy",
        "",
        json_block(freeze.get("evaluation", {})),
        (
            f"Authority gaps: `{authority_summary.get('unexplainedAuthorityGap', 'UNKNOWN')}`; "
            "missing V2 mappings: "
            f"`{authority_summary.get('missingV2MetricMapping', 'UNKNOWN')}`."
        ),
        "",
        "## 5. Prompt / RAG Freeze",
        "",
        "Prompt identities:",
        json_block(freeze.get("promptIdentities", [])),
        "Deterministic RAG acceptance:",
        json_block(rag_summary),
        "",
        "## 6. Runtime Preflight",
        "",
        json_block(runtime_preflight),
        (
            "Existing targeted runtime evidence reference: "
            f"`{targeted.get('javaToolInvocationObserved', 'UNKNOWN')}` Java tool observations."
        ),
        "",
        "## 7. Qwen Provider Gate",
        "",
        json_block(freeze.get("providerGate", {})),
        "",
        "## 8. Formal105 Status",
        "",
        f"`FORMAL105_STATUS = {status}`",
        "",
        "## 9. Formal105 Execution",
        "",
        json_block(execution),
        (
            "Exactly-once means this run has one persisted `full-105` run identity; "
            "no score-driven rerun was initiated."
        ),
        "",
        "## 10. Metrics",
        "",
        json_block(summary["outcomeMetrics"]),
        (
            "UNKNOWN is excluded from Outcome Accuracy and remains included in Decisive "
            "Coverage/Unknown Rate."
        ),
        "",
        "## 11. DEV / HELD_OUT",
        "",
        json_block(summary["categories"]),
        "",
        "## 12. Task-type Results",
        "",
        json_block(summary["taskTypeResults"]),
        "",
        "## 13. Tool / Safety / RAG Metrics",
        "",
        json_block(tool_metrics),
        "",
        "## 14. Provider Integrity",
        "",
        json_block(provider_evidence),
        "",
        "## 15. Historical Comparison",
        "",
        (
            "Historical DeepSeek Formal105 artifacts are reference-only. This run is not "
            "apples-to-apples because provider, source state, prompt freeze, and potentially "
            "runtime/RAG state differ; no direct improvement claim is made."
        ),
        "",
        "## 16. Integrity / Leakage",
        "",
        json_block(integrity),
        "",
        "## 17. Reproducibility",
        "",
        json_block(reproducibility),
        "",
        "## 18. Artifacts",
        "",
        *[f"- `{name}`" for name in artifact_names],
        "",
        "## 19. Remaining Limitations",
        "",
        json_block(limitations),
        (
            "Performance limitations are reported as facts and do not alter frozen policy, "
            "evaluator, GroundTruth, ToolRequirement, or RAG threshold."
        ),
        "",
        "## 20. Final Verdict",
        "",
        f"`STAGE21_FORMAL105 = {verdict}`",
        "",
        "STOP_FOR_MANAGER_REVIEW",
    ]
    return "\n".join(lines) + "\n"


def _finalize(
    output_root: Path,
    *,
    command: str | None = None,
    secret_values: Iterable[str] = (),
) -> dict[str, object]:
    output_root = output_root.resolve()
    for historical in HISTORICAL_OUTPUT_ROOTS:
        historical_path = historical.resolve()
        if output_root == historical_path or historical_path in output_root.parents:
            raise RuntimeError(
                "refusing to finalize a historical Formal105 artifact: " f"{output_root}"
            )
    dataset = load_dataset(MANIFEST_PATH)
    policy = load_outcome_policy(POLICY_PATH, dataset=dataset)
    freeze_path = output_root / "freeze-manifest.json"
    if not freeze_path.is_file():
        raise RuntimeError(f"freeze manifest is missing: {freeze_path}")
    freeze = _read_json(freeze_path)
    model_provider = freeze.get("modelProvider")
    if not isinstance(model_provider, dict) or not model_provider.get("provider"):
        raise RuntimeError("provider-neutral modelProvider identity is missing from freeze")
    run_path = _find_run(output_root)
    run = load_persisted_formal105_run(run_path)
    projection = project_outcome_v2(run, policy, source_artifact=run_path)
    baseline_record = _baseline_record(run_path)
    task_artifact_count = _persist_task_results(
        output_root,
        run,
        provider=str(model_provider["provider"]),
        model=str(model_provider["model"]),
    )
    tool_analysis = _tool_analysis(run, projection, dataset)
    taxonomy = _failure_taxonomy(run, projection, tool_analysis, dataset)
    categories = _category_summary(run, projection, dataset, tool_analysis)
    rag = _read_json(RAG_ACCEPTANCE_PATH)
    summary = _formal_summary(
        output_root,
        run_path,
        run,
        projection,
        baseline_record,
        tool_analysis,
        taxonomy,
        categories,
        freeze,
        rag,
        task_artifact_count,
    )
    provider_evidence = _provider_evidence(output_root, run_path, run, freeze)
    runtime_preflight = freeze.get("runtimePreflight", {})
    if not isinstance(runtime_preflight, dict):
        runtime_preflight = {}
    authority = _read_json(AUTHORITY_CLOSURE_PATH)
    targeted = _read_json(TARGETED_SUMMARY_PATH)
    leakage_paths = _scan_artifact_secrets(output_root, secret_values)
    verdict = _final_verdict(
        summary,
        provider_evidence,
        rag=rag,
        authority=authority,
        leakage_paths=leakage_paths,
    )
    run_manifest = _run_manifest(freeze, run, command=command)
    metrics = {
        "schemaVersion": "stage21-final-formal105-metrics/v1",
        "finalVerdict": verdict,
        "outcome": summary["outcomeMetrics"],
        "devHeldOut": summary["categories"],
        "taskTypes": summary["taskTypeResults"],
        "tool": summary["toolUse"],
        "evaluation": summary["evaluationMetrics"],
        "model": summary["model"],
        "deterministicRag": summary["evidenceHit"]["deterministicRag"],  # type: ignore[index]
    }
    _write_json(output_root / "outcome-v2.json", projection.model_dump(mode="json"))
    (output_root / "outcome-v2-summary.md").write_text(
        render_outcome_v2_summary(projection), encoding="utf-8", newline="\n"
    )
    _write_json(output_root / "tool-use-analysis.json", tool_analysis)
    _write_json(output_root / "failure-taxonomy.json", taxonomy)
    _write_json(output_root / "formal105-summary.json", summary)
    (output_root / "formal105-summary.md").write_text(
        _render_formal_summary(summary), encoding="utf-8", newline="\n"
    )
    _write_json(output_root / "provider-evidence.json", provider_evidence)
    _write_json(output_root / "run-manifest.json", run_manifest)
    _write_json(output_root / "metrics.json", metrics)
    inventory = _artifact_inventory(
        output_root,
        excluded_names=(
            "reproducibility.json",
            "final-acceptance.md",
            "stage21-final-acceptance.md",
        ),
    )
    reproducibility = _reproducibility_record(
        freeze,
        run,
        command=command,
        artifact_inventory=inventory,
    )
    _write_json(output_root / "reproducibility.json", reproducibility)
    artifact_names = [
        "freeze-manifest.json",
        "run-manifest.json",
        "provider-evidence.json",
        "metrics.json",
        "reproducibility.json",
        "formal105-summary.json",
        "formal105-summary.md",
        "tool-use-analysis.json",
        "failure-taxonomy.json",
        "outcome-v2.json",
        "outcome-v2-summary.md",
        "task-results/",
        "full-105/",
        "final-acceptance.md",
        "stage21-final-acceptance.md",
    ]
    acceptance = _render_final_acceptance(
        summary,
        authority=authority,
        targeted=targeted,
        rag=rag,
        provider_evidence=provider_evidence,
        runtime_preflight=runtime_preflight,
        verdict=verdict,
        leakage_paths=leakage_paths,
        artifact_names=artifact_names,
        reproducibility=reproducibility,
    )
    (output_root / "final-acceptance.md").write_text(
        acceptance,
        encoding="utf-8",
        newline="\n",
    )
    (output_root / "stage21-final-acceptance.md").write_text(
        acceptance,
        encoding="utf-8",
        newline="\n",
    )
    final_leakage_paths = _scan_artifact_secrets(output_root, secret_values)
    if final_leakage_paths:
        raise RuntimeError(
            "final Formal105 artifact contains a known secret value in: "
            + ", ".join(str(path) for path in final_leakage_paths)
        )
    return {
        "selected": summary["selected"],
        "executed": summary["executed"],
        "persistedTaskArtifacts": summary["persistedTaskArtifacts"],
        "baselineFrozen": summary["baselineFrozen"],
        "evaluationRunId": summary["evaluationRunId"],
        "outputRoot": str(output_root.resolve()),
        "provider": model_provider["provider"],
        "model": model_provider["model"],
        "formal105Status": (
            "COMPLETED"
            if summary["selected"] == FORMAL_TASK_COUNT
            and summary["executed"] == FORMAL_TASK_COUNT
            and summary["persistedTaskArtifacts"] == FORMAL_TASK_COUNT
            else "BLOCKED"
        ),
        "finalVerdict": verdict,
    }


def _write_formal105_path_preflight_artifact(
    *,
    artifact_root: Path | None = None,
    planned_output_root: Path | None = None,
    evaluation_run_id: str | None = None,
) -> dict[str, object]:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    artifact_dir = (
        artifact_root
        or PATH_PREFLIGHT_ARTIFACT_PARENT / f"formal105-path-preflight-{stamp}"
    ).resolve()
    if artifact_dir.exists():
        raise RuntimeError(f"path preflight artifact already exists: {artifact_dir}")
    dataset = load_dataset(MANIFEST_PATH)
    ordered_task_ids = tuple(entry.benchmark_task_id for entry in dataset.manifest.tasks)
    planned_root = (
        planned_output_root
        or DEFAULT_OUTPUT_ROOT / f"fresh-formal105-planned-{stamp}"
    ).resolve()
    logical_run_id = evaluation_run_id or (
        f"evaluation_run:stage21-real-model-full-105-preflight-{stamp}"
    )
    record = _formal105_path_preflight(planned_root, logical_run_id, ordered_task_ids)
    record["artifactRoot"] = str(artifact_dir)
    _write_json(artifact_dir / "path-preflight.json", record)
    (artifact_dir / "path-preflight.md").write_text(
        _render_path_preflight(record),
        encoding="utf-8",
        newline="\n",
    )
    return record


async def _execute_baseline_once(
    settings: AppSettings,
    output_root: Path,
    provider: str,
    http_client: httpx.AsyncClient,
    evaluation_run_id: str | None = None,
) -> object:
    """Call the existing provider-neutral baseline exactly once."""

    baseline.DEFAULT_OUTPUT_ROOT = output_root.resolve()
    runner = baseline._build_runner(  # noqa: SLF001 - existing shared runner factory
        settings,
        http_client,
        provider=provider,
    )
    kwargs: dict[str, object] = {
        "label": "full-105",
        "provider": provider,
    }
    if evaluation_run_id is not None:
        kwargs["evaluation_run_id"] = evaluation_run_id
    return await baseline._run_baseline(  # noqa: SLF001 - existing shared Formal105 path
        runner,
        settings,
        **kwargs,
    )


async def _run_once(
    settings: AppSettings,
    output_root: Path,
    provider: str = "qwen",
    *,
    acceptance_dir: Path = QWEN_ACCEPTANCE_DIR,
    runtime_preflight: Path | None = None,
    revision_freeze: Path | None = None,
    command: str | None = None,
) -> dict[str, object]:
    provider = _require_provider(provider)
    frozen_revision = final_revision.verify_frozen_revision(revision_freeze, settings)
    output_root = _ensure_new_output_root(output_root)
    dataset = load_dataset(MANIFEST_PATH)
    policy = load_outcome_policy(POLICY_PATH, dataset=dataset)
    dataset_identity = _dataset_freeze(dataset, policy)
    if not dataset_identity["taskCount"] == FORMAL_TASK_COUNT:
        raise RuntimeError("Formal105 preflight requires exactly 105 dataset tasks")
    if not any(
        item.requirement.value == "REQUIRED"
        for task in policy.tasks
        for item in task.tool_requirements
    ):
        raise RuntimeError("Formal105 preflight found no V2 REQUIRED tool requirements")
    ordered_task_ids = tuple(entry.benchmark_task_id for entry in dataset.manifest.tasks)
    evaluation_run_id = baseline._new_evaluation_run_id("full-105")  # noqa: SLF001
    _formal105_path_preflight(output_root, evaluation_run_id, ordered_task_ids)
    qwen_gate = _qwen_provider_gate(settings, acceptance_dir) if provider == "qwen" else None
    environment = _environment_readiness(settings, provider)
    if environment.get("ready") is not True:
        missing = [
            name for name, ready in environment["required"].items() if not ready  # type: ignore[union-attr]
        ]
        raise RuntimeError(
            f"{provider} environment readiness is incomplete: " + ", ".join(missing)
        )
    if runtime_preflight is None:
        raise RuntimeError("Stage21 Final105 live run requires --runtime-preflight evidence")
    runtime_evidence = _runtime_preflight_evidence(runtime_preflight)
    # A local outcome-authority limitation never exempts execution/auth failures,
    # including failures on the known task itself. Probe shared Java security live.
    shared = await final_revision.shared_live_preflight(settings)
    persistence = final_revision.persistence_probe(output_root.parent)
    admission = final_revision.admission_decision(
        runtime=runtime_evidence, provider=qwen_gate,
        path=_formal105_path_preflight(output_root, evaluation_run_id, ordered_task_ids),
        integrity=persistence, limitation=frozen_revision["knownLimitations"],
    )
    final_revision.verify_frozen_revision(revision_freeze, settings)
    git = _git_snapshot()
    frozen_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    output_root.mkdir(parents=True, exist_ok=True)
    _write_json(
        output_root / "freeze-manifest.json",
        {**_freeze_manifest(
            settings,
            dataset,
            policy,
            provider=provider,
            qwen_gate=qwen_gate,
            environment_readiness=environment,
            runtime_preflight=runtime_evidence,
            git_snapshot=git,
            frozen_at=frozen_at,
        ), "revisionFreeze": {
            "path": str(revision_freeze), "sha256": _sha256_file(revision_freeze),
        }, "knownLimitations": frozen_revision["knownLimitations"],
            "admission": admission, "sharedLivePreflight": shared},
    )
    async with httpx.AsyncClient(trust_env=False) as http_client:
        await _execute_baseline_once(
            settings,
            output_root,
            provider,
            http_client,
            evaluation_run_id,
        )
    return _finalize(
        output_root,
        command=command,
        secret_values=_known_secret_values(settings),
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path)
    parser.add_argument("--provider", choices=("qwen",))
    parser.add_argument("--qwen-acceptance-dir", type=Path, default=QWEN_ACCEPTANCE_DIR)
    parser.add_argument("--runtime-preflight", type=Path)
    parser.add_argument("--revision-freeze", type=Path)
    parser.add_argument("--path-preflight", action="store_true")
    parser.add_argument("--path-preflight-artifact-root", type=Path)
    parser.add_argument("--evaluation-run-id")
    parser.add_argument("--finalize-existing", action="store_true")
    parser.add_argument("--validate-only", action="store_true")
    args = parser.parse_args()
    if args.path_preflight:
        print(
            json.dumps(
                _write_formal105_path_preflight_artifact(
                    artifact_root=args.path_preflight_artifact_root,
                    planned_output_root=args.output_root,
                    evaluation_run_id=args.evaluation_run_id,
                ),
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
        )
        return
    if args.validate_only:
        provider = _require_provider(args.provider)
        dataset = load_dataset(MANIFEST_PATH)
        policy = load_outcome_policy(POLICY_PATH, dataset=dataset)
        settings = get_settings()
        gate = (
            _qwen_provider_gate(settings, args.qwen_acceptance_dir)
            if provider == "qwen"
            else {"status": "NOT_APPLICABLE", "provider": "DeepSeek"}
        )
        print(
            json.dumps(
                {
                    "datasetTasks": len(dataset.tasks),
                    "policyTasks": len(policy.tasks),
                    "provider": provider,
                    "model": gate.get("model", settings.deepseek_model),
                    "qualityGate": gate["status"],
                },
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
        )
        return
    if args.finalize_existing:
        if args.output_root is None:
            parser.error("--finalize-existing requires --output-root")
        print(
            json.dumps(
                _finalize(
                    args.output_root.resolve(),
                    command=f"--finalize-existing --output-root {args.output_root.resolve()}",
                    secret_values=_known_secret_values(),
                ),
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
        )
        return
    if args.output_root is None:
        parser.error("live Formal105 requires --output-root")
    if args.provider is None:
        _require_provider(None)
    settings = get_settings()
    command = (
        "uv run --project python-apiops-agentlab python "
        "python-apiops-agentlab/scripts/stage21_final_v2_formal105.py "
        f"--provider {args.provider} --output-root {args.output_root.resolve()} "
        f"--qwen-acceptance-dir {args.qwen_acceptance_dir.resolve()} "
        "--runtime-preflight "
        f"{args.runtime_preflight.resolve() if args.runtime_preflight else '<required>'}"
        " --revision-freeze "
        f"{args.revision_freeze.resolve() if args.revision_freeze else '<required>'}"
    )
    print(
        json.dumps(
            __import__("asyncio").run(
                _run_once(
                    settings,
                    args.output_root,
                    args.provider,
                    acceptance_dir=args.qwen_acceptance_dir,
                    runtime_preflight=args.runtime_preflight,
                    revision_freeze=args.revision_freeze,
                    command=command,
                )
            ),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
