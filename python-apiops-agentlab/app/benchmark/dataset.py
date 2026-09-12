"""Stage 21 Dataset manifest, loader, and deterministic quality lint."""

from __future__ import annotations

import json
import re
from collections import Counter
from collections.abc import Iterable
from pathlib import Path
from typing import Literal

from jsonschema import Draft202012Validator
from pydantic import ValidationError

from app.evaluator import GroundTruth, MetricName, SafetyOutcome

from .golden import (
    GOLDEN_FIXTURE_ROOT,
    load_golden_ground_truths,
    load_golden_tasks,
    validate_initial_state_references,
)
from .mapping import BenchmarkMappingError, resolve_ground_truth
from .models import (
    BenchmarkTask,
    DatasetDifficulty,
    DatasetManifest,
    DatasetManifestEntry,
    DatasetSplit,
    TaskType,
    _BenchmarkModel,
)

_PACKAGE_ROOT = Path(__file__).resolve().parents[2]
_REPOSITORY_ROOT = _PACKAGE_ROOT.parent
_SCHEMA_PATH = _REPOSITORY_ROOT / "shared-schemas" / "evaluation-task-schema.json"
DEFAULT_DATASET_MANIFEST_PATH = GOLDEN_FIXTURE_ROOT / "dataset-manifest.json"
DEFAULT_DATASET_SMOKE_MANIFEST_PATH = GOLDEN_FIXTURE_ROOT / "dataset-manifest-smoke.json"

DATASET_V1_TASK_COUNT = 40
DATASET_V1_CATEGORY_TARGETS = {
    TaskType.TESTCASE_GENERATION.value: 10,
    TaskType.FAILURE_DIAGNOSIS.value: 10,
    TaskType.TOOL_SAFETY.value: 9,
    TaskType.RAG_EVIDENCE_RETRIEVAL.value: 7,
    TaskType.E2E_APIOPS.value: 4,
}
DATASET_V1_SPLIT_TARGETS = {
    DatasetSplit.DEV.value: 30,
    DatasetSplit.HELD_OUT.value: 10,
}
DATASET_FORMAL_MIN_TASK_COUNT = 100


class BenchmarkDataset(_BenchmarkModel):
    manifest: DatasetManifest
    tasks: tuple[BenchmarkTask, ...]
    ground_truths: tuple[GroundTruth, ...]


class DatasetQualityIssue(_BenchmarkModel):
    code: str
    severity: Literal["ERROR", "WARNING"]
    message: str
    benchmark_task_id: str | None = None


class DatasetCoverageSummary(_BenchmarkModel):
    task_count: int
    category_counts: dict[str, int]
    difficulty_counts: dict[str, int]
    split_counts: dict[str, int]


class DatasetQualityReport(_BenchmarkModel):
    manifest: DatasetManifest | None
    issues: tuple[DatasetQualityIssue, ...]
    coverage: DatasetCoverageSummary

    @property
    def is_valid(self) -> bool:
        return not any(issue.severity == "ERROR" for issue in self.issues)

    @property
    def structurally_valid(self) -> bool:
        """No structural or reference errors were found."""

        return self.is_valid

    @property
    def duplicate_candidates(self) -> tuple[str, ...]:
        return tuple(
            issue.message
            for issue in self.issues
            if issue.code in {"OBVIOUS_DUPLICATE", "DUPLICATE_CANDIDATE"}
        )

    @property
    def leakage_candidates(self) -> tuple[str, ...]:
        return tuple(issue.message for issue in self.issues if issue.code == "LEAKAGE_CANDIDATE")

    @property
    def review_status_counts(self) -> dict[str, int]:
        if self.manifest is None:
            return {}
        return dict(Counter(entry.review_status.value for entry in self.manifest.tasks))

    @property
    def dataset_ready(self) -> bool:
        """Readiness after structural, coverage, and review gates pass."""

        blocking_codes = {
            "CATEGORY_TARGET_MISMATCH",
            "DIFFICULTY_UNASSIGNED",
            "HELD_OUT_CATEGORY_COVERAGE",
            "LEAKAGE_CANDIDATE",
            "REPLACEMENT_REQUIRED",
            "REVIEW_REQUIRED",
            "SPLIT_TARGET_MISMATCH",
            "SPLIT_UNASSIGNED",
            "TASK_COUNT_MISMATCH",
        }
        all_tasks_approved = bool(self.manifest) and all(
            entry.review_status.value == "APPROVED" for entry in self.manifest.tasks
        )
        return (
            self.structurally_valid
            and all_tasks_approved
            and not any(issue.code in blocking_codes for issue in self.issues)
        )


def load_dataset_manifest(
    path: Path | None = None,
) -> DatasetManifest:
    manifest_path = path or DEFAULT_DATASET_MANIFEST_PATH
    return DatasetManifest.model_validate_json(manifest_path.read_text(encoding="utf-8"))


def load_dataset(path: Path | None = None) -> BenchmarkDataset:
    """Load one manifest and reuse the existing Golden task/Truth loaders."""

    manifest_path = path or DEFAULT_DATASET_MANIFEST_PATH
    manifest = load_dataset_manifest(manifest_path)
    task_paths = tuple(_entry_path(manifest_path, entry.task_file) for entry in manifest.tasks)
    truth_paths = tuple(
        _entry_path(manifest_path, entry.ground_truth_file) for entry in manifest.tasks
    )
    for fixture_path in (*task_paths, *truth_paths):
        if not fixture_path.is_file():
            raise FileNotFoundError(f"dataset manifest fixture does not exist: {fixture_path}")

    loaded_tasks = {
        task.benchmark_task_id: task
        for task in _load_tasks_from_directories({path.parent for path in task_paths})
    }
    loaded_truths = _load_truths_from_directories({path.parent for path in truth_paths})
    tasks: list[BenchmarkTask] = []
    truths: dict[tuple[str, str], GroundTruth] = {
        (truth.ground_truth_id, truth.version): truth for truth in loaded_truths
    }

    for entry, task_path in zip(manifest.tasks, task_paths, strict=True):
        task = BenchmarkTask.model_validate_json(task_path.read_text(encoding="utf-8"))
        if task.benchmark_task_id != entry.benchmark_task_id:
            raise ValueError(f"manifest task ID does not match {task_path}")
        if task.benchmark_task_id not in loaded_tasks:
            raise ValueError(f"task is not present in the existing Golden loader: {task_path}")
        if task.schema_version != manifest.task_schema_version:
            raise ValueError(f"task schema version does not match manifest: {task_path}")
        truth_key = (entry.ground_truth_ref.ground_truth_id, entry.ground_truth_ref.version)
        truth_from_path = GroundTruth.model_validate_json(
            _entry_path(manifest_path, entry.ground_truth_file).read_text(encoding="utf-8")
        )
        if (truth_from_path.ground_truth_id, truth_from_path.version) != truth_key:
            raise ValueError(f"manifest GroundTruth file does not match {truth_key}")
        truth = truths.get(truth_key)
        if truth is None:
            raise ValueError(f"manifest GroundTruth reference is not resolvable: {truth_key}")
        resolve_ground_truth(task, (truth,))
        tasks.append(task)

    selected_truths = tuple(
        truths[(entry.ground_truth_ref.ground_truth_id, entry.ground_truth_ref.version)]
        for entry in manifest.tasks
    )
    return BenchmarkDataset(
        manifest=manifest,
        tasks=tuple(tasks),
        ground_truths=selected_truths,
    )


def lint_dataset(
    path: Path | None = None, *, schema_path: Path | None = None,
) -> DatasetQualityReport:
    """Run deterministic, fail-closed quality checks without executing tasks."""

    manifest_path = path or DEFAULT_DATASET_MANIFEST_PATH
    issues: list[DatasetQualityIssue] = []
    try:
        manifest = load_dataset_manifest(manifest_path)
    except (OSError, ValueError, ValidationError, json.JSONDecodeError) as exc:
        return _report(
            None,
            [
                _issue(
                    "MANIFEST_INVALID",
                    "ERROR",
                    f"cannot load dataset manifest: {exc}",
                )
            ],
        )

    try:
        schema = json.loads((schema_path or _SCHEMA_PATH).read_text(encoding="utf-8"))
        schema_validator = Draft202012Validator(schema)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return _report(
            manifest,
            [_issue("SCHEMA_INVALID", "ERROR", f"cannot load shared schema: {exc}")],
        )

    task_records: list[tuple[DatasetManifestEntry, Path, dict[str, object], BenchmarkTask]] = []
    truth_records: list[tuple[DatasetManifestEntry, Path, GroundTruth]] = []
    listed_task_paths: set[Path] = set()
    listed_truth_paths: set[Path] = set()

    for entry in manifest.tasks:
        task_path = _check_manifest_path(
            manifest_path,
            entry.task_file,
            listed_task_paths,
            issues,
            entry.benchmark_task_id,
        )
        if task_path is not None and task_path.is_file():
            raw_task = _read_json(task_path, issues, entry.benchmark_task_id)
            if raw_task is not None:
                schema_errors = list(schema_validator.iter_errors(raw_task))
                if schema_errors:
                    _append_issue(
                        issues,
                        "SCHEMA_INVALID",
                        "ERROR",
                        _schema_error_message(schema_errors),
                        entry.benchmark_task_id,
                    )
                else:
                    try:
                        task = BenchmarkTask.model_validate_json(json.dumps(raw_task))
                    except ValidationError as exc:
                        code = (
                            "EVALUATION_SPEC_INVALID"
                            if "evaluation" in str(exc).lower() or "metrics" in str(exc).lower()
                            else "TASK_MODEL_INVALID"
                        )
                        _append_issue(
                            issues,
                            code,
                            "ERROR",
                            str(exc),
                            entry.benchmark_task_id,
                        )
                    else:
                        task_records.append((entry, task_path, raw_task, task))

        truth_path = _check_manifest_path(
            manifest_path,
            entry.ground_truth_file,
            listed_truth_paths,
            issues,
            entry.benchmark_task_id,
        )
        if truth_path is not None and truth_path.is_file():
            raw_truth = _read_json(truth_path, issues, entry.benchmark_task_id)
            if raw_truth is not None:
                try:
                    truth = GroundTruth.model_validate_json(json.dumps(raw_truth))
                except ValidationError as exc:
                    _append_issue(
                        issues,
                        "GROUND_TRUTH_INVALID",
                        "ERROR",
                        str(exc),
                        entry.benchmark_task_id,
                    )
                else:
                    truth_records.append((entry, truth_path, truth))

    _check_manifest_file_coverage(listed_task_paths, "task", issues)
    _check_manifest_file_coverage(listed_truth_paths, "GroundTruth", issues)
    _check_task_records(task_records, manifest, issues)
    _check_truth_records(truth_records, issues)
    _check_task_quality(task_records, truth_records, manifest, issues)
    issues.extend(_split_leakage_issues(task_records))

    return _report(manifest, issues, task_records)


def _load_tasks_from_directories(directories: Iterable[Path]) -> tuple[BenchmarkTask, ...]:
    values: list[BenchmarkTask] = []
    for directory in directories:
        values.extend(load_golden_tasks(directory))
    return tuple(values)


def _load_truths_from_directories(directories: Iterable[Path]) -> tuple[GroundTruth, ...]:
    values: list[GroundTruth] = []
    for directory in directories:
        values.extend(load_golden_ground_truths(directory))
    return tuple(values)


def _entry_path(manifest_path: Path, reference: str) -> Path:
    candidate = (manifest_path.parent / _relative_path(reference)).resolve()
    try:
        candidate.relative_to(manifest_path.parent.resolve())
    except ValueError as exc:
        raise ValueError(f"manifest path escapes manifest directory: {reference}") from exc
    return candidate


def _relative_path(reference: str) -> Path:
    relative = Path(reference)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError(f"manifest paths must be repository-relative: {reference}")
    return relative


def _check_manifest_path(
    manifest_path: Path,
    reference: str,
    listed_paths: set[Path],
    issues: list[DatasetQualityIssue],
    task_id: str,
) -> Path | None:
    try:
        resolved = _entry_path(manifest_path, reference)
    except ValueError as exc:
        _append_issue(issues, "MANIFEST_INCONSISTENT", "ERROR", str(exc), task_id)
        return None
    listed_paths.add(resolved)
    if not resolved.is_file():
        _append_issue(
            issues,
            "FIXTURE_MISSING",
            "ERROR",
            f"manifest reference does not exist: {reference}",
            task_id,
        )
    return resolved


def _read_json(
    path: Path,
    issues: list[DatasetQualityIssue],
    task_id: str,
) -> dict[str, object] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        _append_issue(issues, "SCHEMA_INVALID", "ERROR", f"invalid JSON: {exc}", task_id)
        return None
    if not isinstance(value, dict):
        _append_issue(issues, "SCHEMA_INVALID", "ERROR", "fixture root must be an object", task_id)
        return None
    return value


def _schema_error_message(errors: list[object]) -> str:
    messages = [getattr(error, "message", str(error)) for error in errors[:3]]
    suffix = "" if len(errors) <= 3 else f" (+{len(errors) - 3} more)"
    return "; ".join(messages) + suffix


def _check_manifest_file_coverage(
    listed_paths: set[Path],
    kind: str,
    issues: list[DatasetQualityIssue],
) -> None:
    if not listed_paths:
        return
    for directory in {path.parent for path in listed_paths}:
        discovered = {path.resolve() for path in directory.glob("*.json")}
        unlisted = sorted(discovered - listed_paths)
        if unlisted:
            _append_issue(
                issues,
                "MANIFEST_INCONSISTENT",
                "ERROR",
                f"unlisted {kind} fixture(s): {', '.join(path.name for path in unlisted)}",
            )


def _check_task_records(
    records: list[tuple[DatasetManifestEntry, Path, dict[str, object], BenchmarkTask]],
    manifest: DatasetManifest,
    issues: list[DatasetQualityIssue],
) -> None:
    ids = [task.benchmark_task_id for _, _, _, task in records]
    for task_id, count in Counter(ids).items():
        if count > 1:
            _append_issue(
                issues,
                "DUPLICATE_TASK_ID",
                "ERROR",
                f"benchmarkTaskId appears {count} times",
                task_id,
            )
    fingerprints: dict[str, str] = {}
    for entry, path, raw_task, task in records:
        if task.schema_version != manifest.task_schema_version:
            _append_issue(
                issues,
                "MANIFEST_INCONSISTENT",
                "ERROR",
                f"task schemaVersion {task.schema_version!r} differs from manifest "
                f"{manifest.task_schema_version!r}",
                task.benchmark_task_id,
            )
        if task.benchmark_task_id != entry.benchmark_task_id:
            _append_issue(
                issues,
                "MANIFEST_INCONSISTENT",
                "ERROR",
                f"manifest ID does not match task file {path.name}",
                entry.benchmark_task_id,
            )
        fingerprint_data = {
            key: value for key, value in raw_task.items() if key != "benchmarkTaskId"
        }
        fingerprint = json.dumps(
            fingerprint_data,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        previous = fingerprints.get(fingerprint)
        if previous is not None:
            _append_issue(
                issues,
                "OBVIOUS_DUPLICATE",
                "ERROR",
                f"task content is identical apart from benchmarkTaskId to {previous}",
                task.benchmark_task_id,
            )
        else:
            fingerprints[fingerprint] = task.benchmark_task_id


def _check_truth_records(
    records: list[tuple[DatasetManifestEntry, Path, GroundTruth]],
    issues: list[DatasetQualityIssue],
) -> None:
    for entry, _, truth in records:
        truth_key = (truth.ground_truth_id, truth.version)
        reference_key = (
            entry.ground_truth_ref.ground_truth_id,
            entry.ground_truth_ref.version,
        )
        if truth_key != reference_key:
            _append_issue(
                issues,
                "MANIFEST_INCONSISTENT",
                "ERROR",
                "manifest GroundTruth file content does not match groundTruthRef",
                entry.benchmark_task_id,
            )

    unique_records: list[tuple[DatasetManifestEntry, Path, GroundTruth]] = []
    seen_paths: set[Path] = set()
    for record in records:
        path = record[1].resolve()
        if path not in seen_paths:
            seen_paths.add(path)
            unique_records.append(record)
    keys = [(truth.ground_truth_id, truth.version) for _, _, truth in unique_records]
    for key, count in Counter(keys).items():
        if count > 1:
            _append_issue(
                issues,
                "GROUND_TRUTH_DUPLICATE",
                "ERROR",
                f"GroundTruth ID/version appears {count} times: {key[0]}@{key[1]}",
            )


def _check_task_quality(
    task_records: list[tuple[DatasetManifestEntry, Path, dict[str, object], BenchmarkTask]],
    truth_records: list[tuple[DatasetManifestEntry, Path, GroundTruth]],
    manifest: DatasetManifest,
    issues: list[DatasetQualityIssue],
) -> None:
    truths = {(truth.ground_truth_id, truth.version): truth for _, _, truth in truth_records}
    for entry, _, _, task in task_records:
        if entry.ground_truth_ref != task.ground_truth_ref:
            _append_issue(
                issues,
                "MANIFEST_INCONSISTENT",
                "ERROR",
                "manifest GroundTruth reference differs from task GroundTruth reference",
                task.benchmark_task_id,
            )

        try:
            validate_initial_state_references(task, repository_root=_REPOSITORY_ROOT)
        except (FileNotFoundError, ValueError) as exc:
            _append_issue(issues, "FIXTURE_MISSING", "ERROR", str(exc), task.benchmark_task_id)

        expected_tools = {call.tool_name for call in task.expected_tool_calls}
        if not expected_tools.issubset(task.allowed_tools):
            _append_issue(
                issues,
                "TOOL_POLICY_INCONSISTENT",
                "ERROR",
                "expected tools outside allowedTools: "
                f"{sorted(expected_tools - set(task.allowed_tools))}",
                task.benchmark_task_id,
            )
        if expected_tools.intersection(task.forbidden_actions):
            _append_issue(
                issues,
                "TOOL_POLICY_INCONSISTENT",
                "ERROR",
                "expected tool is also listed in forbiddenActions",
                task.benchmark_task_id,
            )

        truth_key = (task.ground_truth_ref.ground_truth_id, task.ground_truth_ref.version)
        truth = truths.get(truth_key)
        if truth is None:
            _append_issue(
                issues,
                "GROUND_TRUTH_INCOMPLETE",
                "ERROR",
                f"GroundTruth reference is not resolvable: {truth_key[0]}@{truth_key[1]}",
                task.benchmark_task_id,
            )
            continue

        if set(truth.expected_tools) != expected_tools:
            _append_issue(
                issues,
                "TOOL_POLICY_INCONSISTENT",
                "ERROR",
                "GroundTruth expected_tools differ from task expectedToolCalls",
                task.benchmark_task_id,
            )
        try:
            resolve_ground_truth(task, (truth,))
        except BenchmarkMappingError as exc:
            _append_issue(
                issues,
                "GROUND_TRUTH_INCOMPLETE",
                "ERROR",
                str(exc),
                task.benchmark_task_id,
            )

        if not _has_ground_truth_expectation(truth):
            _append_issue(
                issues,
                "GROUND_TRUTH_INCOMPLETE",
                "ERROR",
                "GroundTruth contains no expected facts",
                task.benchmark_task_id,
            )
        selected = set(task.evaluation_spec.selected_metrics)
        fact_values = {fact.name: fact.value for fact in truth.expected_facts}
        if entry.scenario == "ZERO_HIT":
            if fact_values.get("authorization_outcome") != "AUTHORIZED":
                _append_issue(
                    issues,
                    "RAG_SEMANTICS_INCONSISTENT",
                    "ERROR",
                    "ZERO_HIT must record successful authorization before retrieval",
                    task.benchmark_task_id,
                )
            if fact_values.get("retrieval_expectation") != "ZERO_HIT":
                _append_issue(
                    issues,
                    "RAG_SEMANTICS_INCONSISTENT",
                    "ERROR",
                    "ZERO_HIT must remain distinct from access denial",
                    task.benchmark_task_id,
                )
            if fact_values.get("expected_evidence_count") != 0:
                _append_issue(
                    issues,
                    "RAG_SEMANTICS_INCONSISTENT",
                    "ERROR",
                    "ZERO_HIT must explicitly record zero expected evidence identities",
                    task.benchmark_task_id,
                )
        elif entry.scenario == "WRONG_PROJECT":
            if truth.expected_safety_outcome is not SafetyOutcome.JAVA_DENIED:
                _append_issue(
                    issues,
                    "RAG_SEMANTICS_INCONSISTENT",
                    "ERROR",
                    "WRONG_PROJECT must retain Java authorization denial authority",
                    task.benchmark_task_id,
                )
            if fact_values.get("retrieval_expectation") == "ZERO_HIT":
                _append_issue(
                    issues,
                    "RAG_SEMANTICS_INCONSISTENT",
                    "ERROR",
                    "WRONG_PROJECT must not be represented as ordinary ZERO_HIT",
                    task.benchmark_task_id,
                )
            if fact_values.get("retrieval_expectation") != "ACCESS_DENIED":
                _append_issue(
                    issues,
                    "RAG_SEMANTICS_INCONSISTENT",
                    "ERROR",
                    "WRONG_PROJECT must record access denial as its retrieval outcome",
                    task.benchmark_task_id,
                )
            if fact_values.get("project_isolation") != "NO_CROSS_PROJECT_HIT":
                _append_issue(
                    issues,
                    "RAG_SEMANTICS_INCONSISTENT",
                    "ERROR",
                    "WRONG_PROJECT must record project isolation",
                    task.benchmark_task_id,
                )
            if fact_values.get("evidence_leakage") is not False:
                _append_issue(
                    issues,
                    "RAG_SEMANTICS_INCONSISTENT",
                    "ERROR",
                    "WRONG_PROJECT must explicitly forbid evidence leakage",
                    task.benchmark_task_id,
                )
        elif entry.scenario == "INSUFFICIENT_EVIDENCE":
            if fact_values.get("sufficient_evidence") is not False:
                _append_issue(
                    issues,
                    "DIAGNOSIS_SEMANTICS_INCONSISTENT",
                    "ERROR",
                    "insufficient-evidence diagnosis must set sufficient_evidence=false",
                    task.benchmark_task_id,
                )
            if fact_values.get("sufficientEvidence") is not False:
                _append_issue(
                    issues,
                    "DIAGNOSIS_SEMANTICS_INCONSISTENT",
                    "ERROR",
                    "insufficient-evidence diagnosis must map "
                    "DiagnosisReport.sufficientEvidence=false",
                    task.benchmark_task_id,
                )
            if truth.diagnosis_contract is None and fact_values.get("rootCauseHypotheses") != []:
                _append_issue(
                    issues,
                    "DIAGNOSIS_SEMANTICS_INCONSISTENT",
                    "ERROR",
                    "insufficient-evidence diagnosis must not assert unsupported root hypotheses",
                    task.benchmark_task_id,
                )
            if fact_values.get("limitations_required") is not True:
                _append_issue(
                    issues,
                    "DIAGNOSIS_SEMANTICS_INCONSISTENT",
                    "ERROR",
                    "insufficient-evidence diagnosis must retain a limitation",
                    task.benchmark_task_id,
                )
        if MetricName.EVIDENCE_HIT in selected and truth.expected_evidence_ids is None:
            _append_issue(
                issues,
                "GROUND_TRUTH_INCOMPLETE",
                "ERROR",
                "EVIDENCE_HIT requires expected evidence identities",
                task.benchmark_task_id,
            )
        if MetricName.DIAGNOSIS_ACCURACY in selected and truth.expected_diagnosis is None:
            _append_issue(
                issues,
                "GROUND_TRUTH_INCOMPLETE",
                "ERROR",
                "DIAGNOSIS_ACCURACY requires expected diagnosis",
                task.benchmark_task_id,
            )
        if MetricName.SAFETY_ACCURACY in selected and truth.expected_safety_outcome is None:
            _append_issue(
                issues,
                "GROUND_TRUTH_INCOMPLETE",
                "ERROR",
                "SAFETY_ACCURACY requires expected safety outcome",
                task.benchmark_task_id,
            )

        if set(task.metrics) != selected:
            _append_issue(
                issues,
                "EVALUATION_SPEC_INVALID",
                "ERROR",
                "metrics and evaluationSpec.selectedMetrics differ",
                task.benchmark_task_id,
            )

    present_categories = {task.task_type for _, _, _, task in task_records}
    missing_categories = [
        category.value for category in TaskType if category not in present_categories
    ]
    if missing_categories:
        _append_issue(
            issues,
            "CATEGORY_COVERAGE",
            "ERROR",
            f"missing task categories: {missing_categories}",
        )
    if manifest.task_schema_version != "0.2.0":
        _append_issue(
            issues,
            "MANIFEST_INCONSISTENT",
            "WARNING",
            f"dataset manifest taskSchemaVersion is {manifest.task_schema_version!r}",
        )

    category_counts = Counter(task.task_type.value for _, _, _, task in task_records)
    if manifest.dataset_version == "v1":
        if len(task_records) != DATASET_V1_TASK_COUNT:
            _append_issue(
                issues,
                "TASK_COUNT_MISMATCH",
                "ERROR",
                f"dataset v1 requires {DATASET_V1_TASK_COUNT} tasks, found {len(task_records)}",
            )
        if dict(category_counts) != DATASET_V1_CATEGORY_TARGETS:
            _append_issue(
                issues,
                "CATEGORY_TARGET_MISMATCH",
                "ERROR",
                "dataset v1 category targets do not match: "
                f"expected {DATASET_V1_CATEGORY_TARGETS}, found {dict(category_counts)}",
            )
    elif len(task_records) < DATASET_FORMAL_MIN_TASK_COUNT:
        _append_issue(
            issues,
            "TASK_COUNT_MISMATCH",
            "ERROR",
            f"formal dataset requires at least {DATASET_FORMAL_MIN_TASK_COUNT} tasks, "
            f"found {len(task_records)}",
        )

    difficulty_counts = Counter(entry.difficulty.value for entry in manifest.tasks)
    if DatasetDifficulty.UNASSIGNED.value in difficulty_counts:
        _append_issue(
            issues,
            "DIFFICULTY_UNASSIGNED",
            "ERROR",
            "dataset requires a difficulty assignment for every task",
        )
    split_counts = Counter(entry.split.value for entry in manifest.tasks)
    if DatasetSplit.UNASSIGNED.value in split_counts:
        _append_issue(
            issues,
            "SPLIT_UNASSIGNED",
            "ERROR",
            "dataset requires DEV or HELD_OUT for every task",
        )
    actual_split_counts = Counter(
        entry.split.value
        for entry, _, _, _ in task_records
        if entry.split is not DatasetSplit.UNASSIGNED
    )
    if manifest.dataset_version == "v1":
        if dict(actual_split_counts) != DATASET_V1_SPLIT_TARGETS:
            _append_issue(
                issues,
                "SPLIT_TARGET_MISMATCH",
                "ERROR",
                "dataset v1 split targets do not match: "
                f"expected {DATASET_V1_SPLIT_TARGETS}, found {dict(actual_split_counts)}",
            )
    elif not {
        DatasetSplit.DEV.value,
        DatasetSplit.HELD_OUT.value,
    }.issubset(actual_split_counts):
        _append_issue(
            issues,
            "SPLIT_TARGET_MISMATCH",
            "ERROR",
            "formal dataset requires both DEV and HELD_OUT tasks",
        )

    held_out_categories = {
        task.task_type for entry, _, _, task in task_records if entry.split is DatasetSplit.HELD_OUT
    }
    missing_held_out = [
        category.value for category in TaskType if category not in held_out_categories
    ]
    if missing_held_out:
        _append_issue(
            issues,
            "HELD_OUT_CATEGORY_COVERAGE",
            "ERROR",
            f"held-out split is missing categories: {missing_held_out}",
        )

    if len(task_records) != len(manifest.tasks):
        _append_issue(
            issues,
            "MANIFEST_INCONSISTENT",
            "ERROR",
            "every manifest entry must resolve to one valid task fixture",
        )

    for entry in manifest.tasks:
        if entry.review_status.value != "APPROVED":
            code = (
                "REPLACEMENT_REQUIRED"
                if entry.review_status.value == "REPLACE_REQUIRED"
                else "REVIEW_REQUIRED"
            )
            _append_issue(
                issues,
                code,
                "WARNING",
                "task requires human approval before Dataset Freeze",
                entry.benchmark_task_id,
            )


def _split_leakage_issues(
    task_records: list[tuple[DatasetManifestEntry, Path, dict[str, object], BenchmarkTask]],
) -> list[DatasetQualityIssue]:
    issues: list[DatasetQualityIssue] = []
    dev = [record for record in task_records if record[0].split is DatasetSplit.DEV]
    held_out = [record for record in task_records if record[0].split is DatasetSplit.HELD_OUT]
    signatures: dict[str, str] = {}
    normalized_instructions: dict[str, str] = {}

    for entry, _, _, task in task_records:
        signature = json.dumps(
            {
                "initialState": task.initial_state.model_dump(),
                "groundTruthRef": task.ground_truth_ref.model_dump(),
                "expectedToolCalls": [call.model_dump() for call in task.expected_tool_calls],
                "allowedTools": task.allowed_tools,
                "forbiddenActions": task.forbidden_actions,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        signatures[entry.benchmark_task_id] = signature
        normalized_instructions[entry.benchmark_task_id] = _normalize_instruction(task.instruction)

    for dev_entry, _, _, dev_task in dev:
        for held_entry, _, _, held_task in held_out:
            if signatures[dev_entry.benchmark_task_id] == signatures[held_entry.benchmark_task_id]:
                issues.append(
                    _issue(
                        "LEAKAGE_CANDIDATE",
                        "WARNING",
                        f"DEV {dev_entry.benchmark_task_id} and HELD_OUT "
                        f"{held_entry.benchmark_task_id} share fixture/Truth/tool identity",
                        held_entry.benchmark_task_id,
                    )
                )
            if (
                dev_task.task_type == held_task.task_type
                and normalized_instructions[dev_entry.benchmark_task_id]
                == normalized_instructions[held_entry.benchmark_task_id]
            ):
                issues.append(
                    _issue(
                        "LEAKAGE_CANDIDATE",
                        "WARNING",
                        f"DEV {dev_entry.benchmark_task_id} and HELD_OUT "
                        f"{held_entry.benchmark_task_id} have near-identical "
                        "normalized instructions",
                        held_entry.benchmark_task_id,
                    )
                )

    for entry, _, _, _ in task_records:
        if entry.split is DatasetSplit.UNASSIGNED:
            continue
        for other_entry, _, _, _ in task_records:
            if entry.benchmark_task_id >= other_entry.benchmark_task_id:
                continue
            if signatures[entry.benchmark_task_id] == signatures[other_entry.benchmark_task_id]:
                issues.append(
                    _issue(
                        "DUPLICATE_CANDIDATE",
                        "WARNING",
                        f"{entry.benchmark_task_id} and {other_entry.benchmark_task_id} "
                        "share fixture/Truth/tool identity",
                        entry.benchmark_task_id,
                    )
                )
    return issues


def _normalize_instruction(instruction: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", instruction.lower()).strip()


def _has_ground_truth_expectation(truth: GroundTruth) -> bool:
    return bool(
        truth.expected_tools
        or truth.expected_tool_arguments
        or truth.expected_evidence_ids
        or truth.expected_diagnosis
        or truth.expected_safety_outcome
        or truth.expected_facts
    )


def _report(
    manifest: DatasetManifest | None,
    issues: list[DatasetQualityIssue],
    task_records: list[tuple[DatasetManifestEntry, Path, dict[str, object], BenchmarkTask]]
    | None = None,
) -> DatasetQualityReport:
    task_records = task_records or []
    category_counts = {category.value: 0 for category in TaskType}
    for _, _, _, task in task_records:
        category_counts[task.task_type.value] += 1
    difficulty_counts = (
        Counter(entry.difficulty.value for entry in manifest.tasks) if manifest else {}
    )
    split_counts = Counter(entry.split.value for entry in manifest.tasks) if manifest else {}
    return DatasetQualityReport(
        manifest=manifest,
        issues=tuple(issues),
        coverage=DatasetCoverageSummary(
            task_count=len(task_records),
            category_counts=dict(category_counts),
            difficulty_counts=dict(difficulty_counts),
            split_counts=dict(split_counts),
        ),
    )


def _issue(
    code: str,
    severity: Literal["ERROR", "WARNING"],
    message: str,
    task_id: str | None = None,
) -> DatasetQualityIssue:
    return DatasetQualityIssue(
        code=code,
        severity=severity,
        message=message,
        benchmark_task_id=task_id,
    )


def _append_issue(
    issues: list[DatasetQualityIssue],
    code: str,
    severity: Literal["ERROR", "WARNING"],
    message: str,
    task_id: str | None = None,
) -> None:
    issues.append(_issue(code, severity, message, task_id))


__all__ = [
    "BenchmarkDataset",
    "DEFAULT_DATASET_MANIFEST_PATH",
    "DEFAULT_DATASET_SMOKE_MANIFEST_PATH",
    "DATASET_FORMAL_MIN_TASK_COUNT",
    "DATASET_V1_CATEGORY_TARGETS",
    "DATASET_V1_SPLIT_TARGETS",
    "DATASET_V1_TASK_COUNT",
    "DatasetCoverageSummary",
    "DatasetQualityIssue",
    "DatasetQualityReport",
    "lint_dataset",
    "load_dataset",
    "load_dataset_manifest",
]
