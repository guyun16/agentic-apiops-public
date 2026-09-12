"""Integrity and estimate regressions for the single residual closure replay."""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.benchmark.outcome_v2 import OutcomeV2Projection, V2OutcomeStatus
from app.benchmark.runner import (
    BenchmarkRun,
    BenchmarkRunPolicy,
    BenchmarkTaskResult,
    JsonBenchmarkResultStore,
)

_SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))
import stage21_final_residual_closure as closure  # noqa: E402


def projection(statuses: dict[str, str]) -> OutcomeV2Projection:
    return OutcomeV2Projection.model_construct(tasks=tuple(
        SimpleNamespace(benchmark_task_id=key, v2_status=V2OutcomeStatus(value))
        for key, value in statuses.items()
    ))


def result(task_id: str = "task-a", **updates: object) -> BenchmarkTaskResult:
    values = {
        "evaluation_run_id": "run-closure", "benchmark_task_id": task_id,
        "task_type": "RAG_EVIDENCE_RETRIEVAL", "status": "SUCCESS",
        "agent_run_id": "agent-a", "trace_id": "trace-a", "case_id": "case-a",
        "setup_status": "SUCCESS", "cleanup_status": "SUCCESS", "duration_ms": 0.0,
    }
    values.update(updates)
    return BenchmarkTaskResult.model_validate_json(json.dumps(values))


def persist_run(root: Path) -> tuple[BenchmarkRun, Path]:
    store = JsonBenchmarkResultStore(root)
    item = result()
    task_path = store.persist_task(item)
    run = BenchmarkRun(
        evaluationRunId=item.evaluation_run_id, datasetId="dataset", datasetVersion="v1",
        taskSchemaVersion="v1", selectedTaskIds=(item.benchmark_task_id,), results=(item,),
        startedAt=datetime.now(UTC), completedAt=datetime.now(UTC), policy=BenchmarkRunPolicy(),
    )
    store.persist_run(run)
    return run, task_path


def test_estimate_overlays_each_task_once_and_keeps_regressions() -> None:
    official = projection({
        **{f"task-{i}": "PASS" for i in range(70)},
        **{f"task-{i}": "FAIL" for i in range(70, 95)},
        **{f"task-{i}": "UNKNOWN" for i in range(95, 105)},
    })
    estimate = closure._estimate((
        official,
        projection({"task-95": "PASS"}),
        projection({"task-70": "PASS", "task-95": "UNKNOWN"}),
        projection({"task-70": "FAIL", "task-71": "PASS"}),
    ))
    assert (estimate["pass"], estimate["fail"], estimate["unknown"]) == (71, 24, 10)
    assert estimate["isOfficialResult"] is False
    assert estimate["notice"] == "ESTIMATE != NEW OFFICIAL RESULT"
    with pytest.raises(closure.ClosureFailure, match="UNRECOGNIZED_TASK"):
        closure._estimate((official, projection({"unrecognized": "PASS"})))


def test_cohort_is_all_fifteen_previous_nonpass_not_a_handpicked_subset() -> None:
    previous = projection({
        **{f"pass-{i}": "PASS" for i in range(18)},
        **{f"fail-{i}": "FAIL" for i in range(7)},
        **{f"unknown-{i}": "UNKNOWN" for i in range(8)},
    })
    selected = closure._residual_cohort(previous)
    assert len(selected) == 15
    assert all(not key.startswith("pass-") for key in selected)
    with_controls = closure._selected_cohort(
        previous, {key: "PASS" for key in closure.REGRESSION_CONTROLS}
    )
    assert len(with_controls) == 18
    assert set(selected) <= set(with_controls)
    assert set(closure.REGRESSION_CONTROLS) <= set(with_controls)
    with pytest.raises(closure.ClosureFailure, match="REGRESSION_CONTROL_BASELINE_DRIFT"):
        closure._selected_cohort(previous, {})
    with pytest.raises(closure.ClosureFailure, match="BASELINE_DRIFT"):
        closure._residual_cohort(projection({"only-one": "FAIL"}))


def test_comparison_records_pass_control_regression_instead_of_counting_it_as_gain() -> None:
    control = closure.REGRESSION_CONTROLS[0]
    comparison = closure._comparison(
        {"residual": "FAIL", control: "PASS"},
        projection({"residual": "PASS", control: "FAIL"}),
    )
    assert comparison["oldFailToPass"] == 1
    assert comparison["transitionCounts"] == {"FAIL->PASS": 1, "PASS->FAIL": 1}
    assert control in comparison["regressionControlFailures"]
    assert next(row for row in comparison["tasks"] if row["benchmarkTaskId"] == control)[
        "role"
    ] == "REGRESSION_CONTROL"


def test_persisted_integrity_reads_task_files_not_only_run_envelope(tmp_path: Path) -> None:
    expected_run, task_path = persist_run(tmp_path)
    observed, checks = closure._read_persisted_run(tmp_path, "run-closure", ("task-a",))
    assert observed == expected_run
    assert checks["persisted"] == 1
    task_path.unlink()
    with pytest.raises(closure.ClosureFailure, match="ARTIFACT_INTEGRITY"):
        closure._read_persisted_run(tmp_path, "run-closure", ("task-a",))


@pytest.mark.parametrize("corruption", ["duplicate", "different_result", "wrong_run"])
def test_persistence_rejects_duplicates_and_envelope_drift(
    tmp_path: Path, corruption: str,
) -> None:
    _, path = persist_run(tmp_path)
    if corruption == "duplicate":
        (path.parent / "task-duplicate.json").write_bytes(path.read_bytes())
    else:
        change = {"report_id": "report:unmatched"} if corruption == "different_result" else {
            "evaluation_run_id": "wrong-run"
        }
        path.write_text(result(**change).model_dump_json(), encoding="utf-8")
    with pytest.raises(closure.ClosureFailure, match="ARTIFACT_INTEGRITY"):
        closure._read_persisted_run(tmp_path, "run-closure", ("task-a",))


def test_runtime_failure_persists_evidence_before_stopping(tmp_path: Path) -> None:
    store = closure.VerifiedStore(tmp_path, lambda: None)
    failed = result(status="FAILED", failure_category="INFRASTRUCTURE_FAILURE")
    with pytest.raises(closure.ClosureFailure, match="RUNTIME_FAILED"):
        store.persist_task(failed)
    path = store.task_path(failed.evaluation_run_id, failed.benchmark_task_id)
    assert BenchmarkTaskResult.model_validate_json(path.read_text(encoding="utf-8")) == failed
    assert store.executed == 1


def test_source_drift_stops_after_persistence_and_does_not_overwrite(tmp_path: Path) -> None:
    def drift() -> None:
        raise closure.ClosureFailure("SOURCE_REVISION_DRIFT")

    store = closure.VerifiedStore(tmp_path, drift)
    with pytest.raises(closure.ClosureFailure, match="SOURCE_REVISION_DRIFT"):
        store.persist_task(result())
    with pytest.raises(closure.ClosureFailure, match="DUPLICATE_TASK_PERSISTENCE"):
        store.persist_task(result())


def test_provider_without_response_identity_fails_closed_after_persistence(tmp_path: Path) -> None:
    store = closure.VerifiedStore(tmp_path, lambda: None)
    unproven = result(model_call_ids=("model-call-without-proof",), model_call_count=1)
    with pytest.raises(closure.ClosureFailure, match="PROVIDER_IDENTITY_FAILED"):
        store.persist_task(unproven)
    assert store.task_path(unproven.evaluation_run_id, unproven.benchmark_task_id).is_file()


def test_business_or_model_failure_is_not_relabelled_as_infrastructure() -> None:
    assert closure._runtime_clean(result(status="FAILED", failure_category="AGENT_FAILURE"))
    assert not closure._runtime_clean(result(status="TIMEOUT", failure_category="TIMEOUT"))


def zero_hit_projection(*, reason: str = "structured facts unavailable: evidence_leakage"):
    first = projection({key: "UNKNOWN" for key in closure.ZERO_HIT_TASKS})
    for row in first.tasks:
        row.outcome_metrics = (SimpleNamespace(
            status=V2OutcomeStatus.UNKNOWN, reason=reason,
        ),)
    return first


def test_zero_hit_confirmation_requires_exact_prior_unknown_reason_and_no_calls() -> None:
    results = tuple(result(key) for key in closure.ZERO_HIT_TASKS)
    closure._validate_zero_hit_confirmation(zero_hit_projection(), results)
    with pytest.raises(closure.ClosureFailure, match="REASON_MISMATCH"):
        closure._validate_zero_hit_confirmation(
            zero_hit_projection(reason="structured facts unavailable: business_error"), results
        )
    with pytest.raises(closure.ClosureFailure, match="BASELINE_MISMATCH"):
        closure._validate_zero_hit_confirmation(projection({"unrelated": "UNKNOWN"}), results)
    with pytest.raises(closure.ClosureFailure, match="PRIOR_MODEL_CALL"):
        closure._validate_zero_hit_confirmation(
            zero_hit_projection(),
            (result(closure.ZERO_HIT_TASKS[0], model_call_count=1), results[1]),
        )


def test_confirmation_store_allows_only_exact_two_tasks_and_zero_model_calls(
    tmp_path: Path,
) -> None:
    store = closure.VerifiedStore(tmp_path, lambda: None, zero_hit_confirmation=True)
    store.persist_task(result(closure.ZERO_HIT_TASKS[0]))
    with pytest.raises(closure.ClosureFailure, match="UNEXPECTED_TASK_OR_MODEL_CALL"):
        store.persist_task(result("other-rag-task"))
    with pytest.raises(closure.ClosureFailure, match="UNEXPECTED_TASK_OR_MODEL_CALL"):
        store.persist_task(result(closure.ZERO_HIT_TASKS[1], model_call_count=1))


def test_confirmation_provider_mode_does_not_relax_main_run_provider_proof() -> None:
    report = {"status": "NO_MODEL_CALL", "terminalModelCallCount": 0}
    assert closure._confirmation_has_no_model_calls((result(closure.ZERO_HIT_TASKS[0]),), report)
    assert not closure._provider_clean(report, require_call=True)
    assert not closure._confirmation_has_no_model_calls(
        (result(closure.ZERO_HIT_TASKS[0]),),
        {"status": "PROVIDER_PROVEN", "terminalModelCallCount": 1},
    )


def test_confirmation_overlay_keeps_first_run_regressions() -> None:
    official = projection({f"task-{i}": "PASS" for i in range(105)})
    earlier = projection({"task-0": "UNKNOWN", "task-1": "UNKNOWN"})
    first18 = projection({"task-0": "UNKNOWN", "task-1": "UNKNOWN", "task-2": "FAIL"})
    confirmation = projection({"task-0": "PASS", "task-1": "PASS"})
    estimate = closure._estimate((official, earlier, first18, confirmation))
    assert (estimate["pass"], estimate["fail"], estimate["unknown"]) == (104, 1, 0)
    compared = closure._comparison(
        {"task-0": "UNKNOWN", "task-1": "UNKNOWN"}, confirmation, controls=()
    )
    assert compared["oldUnknownToPass"] == 2
    assert compared["regressionControls"] == []
    assert compared["regressionControlFailures"] == []
