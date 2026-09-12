"""Small, independent Golden Task and GroundTruth fixture loaders."""

from __future__ import annotations

from pathlib import Path
from typing import TypeVar

from app.evaluator import GroundTruth

from .models import BenchmarkTask, JavaResourceReference, PythonFixtureReference

_MODEL = TypeVar("_MODEL")
_PACKAGE_ROOT = Path(__file__).resolve().parents[2]
GOLDEN_FIXTURE_ROOT = _PACKAGE_ROOT / "tests" / "benchmark" / "fixtures"
GOLDEN_TASK_FIXTURE_DIR = GOLDEN_FIXTURE_ROOT / "tasks"
GOLDEN_GROUND_TRUTH_FIXTURE_DIR = GOLDEN_FIXTURE_ROOT / "ground_truth"


def _json_files(directory: Path) -> tuple[Path, ...]:
    if not directory.is_dir():
        raise FileNotFoundError(f"fixture directory does not exist: {directory}")
    return tuple(sorted(directory.glob("*.json")))


def _load_models(directory: Path, model_type: type[_MODEL]) -> tuple[_MODEL, ...]:
    values: list[_MODEL] = []
    for path in _json_files(directory):
        values.append(
            model_type.model_validate_json(path.read_text(encoding="utf-8"))  # type: ignore[attr-defined]
        )
    return tuple(values)


def load_golden_tasks(directory: Path | None = None) -> tuple[BenchmarkTask, ...]:
    tasks = _load_models(directory or GOLDEN_TASK_FIXTURE_DIR, BenchmarkTask)
    ids = [task.benchmark_task_id for task in tasks]
    if len(ids) != len(set(ids)):
        raise ValueError("Golden benchmarkTaskId values must be unique")
    for task in tasks:
        validate_initial_state_references(task)
    return tasks


def load_golden_ground_truths(directory: Path | None = None) -> tuple[GroundTruth, ...]:
    truths = _load_models(directory or GOLDEN_GROUND_TRUTH_FIXTURE_DIR, GroundTruth)
    keys = [(truth.ground_truth_id, truth.version) for truth in truths]
    if len(keys) != len(set(keys)):
        raise ValueError("Golden GroundTruth ID/version pairs must be unique")
    return truths


def validate_initial_state_references(
    task: BenchmarkTask,
    *,
    repository_root: Path | None = None,
) -> None:
    """Validate local Python fixture references; Java resources remain authority refs."""

    root = repository_root or _PACKAGE_ROOT.parent
    for entry in task.initial_state.entries:
        if isinstance(entry, JavaResourceReference):
            if not entry.ref.strip():
                raise ValueError(f"empty Java resource reference for {entry.key!r}")
        elif isinstance(entry, PythonFixtureReference):
            resolve_python_fixture(entry.ref, repository_root=root)


def resolve_python_fixture(ref: str, *, repository_root: Path | None = None) -> Path:
    """Resolve a repository-relative fixture without allowing implicit machine state."""

    relative = Path(ref)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError("Python fixture references must be repository-relative")
    root = (repository_root or _PACKAGE_ROOT.parent).resolve()
    candidate = (root / relative).resolve()
    if root not in candidate.parents or not candidate.is_file():
        raise FileNotFoundError(f"Python fixture reference is not resolvable: {ref}")
    return candidate


__all__ = [
    "GOLDEN_FIXTURE_ROOT",
    "GOLDEN_GROUND_TRUTH_FIXTURE_DIR",
    "GOLDEN_TASK_FIXTURE_DIR",
    "load_golden_ground_truths",
    "load_golden_tasks",
    "resolve_python_fixture",
    "validate_initial_state_references",
]
