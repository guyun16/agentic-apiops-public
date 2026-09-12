from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from pydantic import ValidationError

from app.benchmark import (
    BenchmarkTask,
    load_dataset,
    load_golden_ground_truths,
    load_golden_tasks,
    resolve_ground_truth,
)
from app.evaluator import MetricName

ROOT = Path(__file__).resolve().parents[3]
SCHEMA_PATH = ROOT / "shared-schemas" / "evaluation-task-schema.json"
TASK_DIR = Path(__file__).parent / "fixtures" / "tasks"


def _raw_task(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def test_all_golden_tasks_validate_against_shared_schema_and_strict_model() -> None:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema)
    tasks = load_golden_tasks()

    assert len(tasks) == 40
    assert len({task.benchmark_task_id for task in tasks}) == len(tasks)
    for path in sorted(TASK_DIR.glob("*.json")):
        instance = _raw_task(path)
        errors = list(validator.iter_errors(instance))
        assert not errors, f"{path.name}: {[error.message for error in errors]}"
        assert BenchmarkTask.model_validate_json(path.read_text(encoding="utf-8"))

    formal_dataset = load_dataset()
    assert len(formal_dataset.tasks) == 105
    assert len(formal_dataset.ground_truths) == 105


def test_unknown_task_fields_are_rejected() -> None:
    path = next(TASK_DIR.glob("*.json"))
    candidate = _raw_task(path)
    candidate["unknownField"] = True
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

    assert list(Draft202012Validator(schema).iter_errors(candidate))
    with pytest.raises(ValidationError):
        BenchmarkTask.model_validate_json(json.dumps(candidate))


def test_ground_truth_references_resolve() -> None:
    tasks = load_golden_tasks()
    truths = load_golden_ground_truths()
    assert all(resolve_ground_truth(task, truths) for task in tasks)


@pytest.mark.parametrize(
    "unsupported",
    (
        "executable",
        "diagnosis_top_k",
        "safety_violation_count",
        "average_steps",
        "collateral_damage",
    ),
)
def test_unsupported_metrics_are_rejected_without_silent_aliases(unsupported: str) -> None:
    assert unsupported not in {metric.value for metric in MetricName}
    path = next(TASK_DIR.glob("*.json"))
    candidate = deepcopy(_raw_task(path))
    candidate["evaluationSpec"]["selectedMetrics"] = [unsupported]  # type: ignore[index]
    candidate["metrics"] = [unsupported]
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

    assert list(Draft202012Validator(schema).iter_errors(candidate))
    with pytest.raises(ValidationError):
        BenchmarkTask.model_validate_json(json.dumps(candidate))


def test_legacy_0_1_task_remains_schema_compatible() -> None:
    legacy = ROOT / "examples" / "evaluation-task-valid.json"
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    errors = list(
        Draft202012Validator(schema).iter_errors(json.loads(legacy.read_text(encoding="utf-8")))
    )
    assert not errors
