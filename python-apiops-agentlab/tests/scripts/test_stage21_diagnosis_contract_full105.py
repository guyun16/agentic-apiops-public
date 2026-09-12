"""Offline checks of version composition and model retention inventory."""

import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

PACKAGE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PACKAGE / "scripts"))
SPEC = importlib.util.spec_from_file_location(
    "diagnosis_live",
    PACKAGE / "scripts/stage21_diagnosis_contract_full105.py",
)
live = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(live)


def test_real_benchmark_progress_dataclass_is_printed(capsys):
    from app.benchmark.runner import BenchmarkProgress, BenchmarkTaskStatus

    live.print_progress(
        BenchmarkProgress('run:one', 86, 105, 'task:one', BenchmarkTaskStatus.SUCCESS)
    )
    assert json.loads(capsys.readouterr().out) == {
        'evaluation_run_id': 'run:one', 'current': 86, 'total': 105,
        'benchmark_task_id': 'task:one', 'status': 'SUCCESS',
    }


def test_frozen_composition_preserves_105_order_splits_and_existing_content():
    dataset = live.validate_dataset()
    parent = live.read(live.FIXTURES / "dataset-manifest.json")
    scoped_root = live.FIXTURES / "revisions/insufficient-evidence-v1"
    scoped = live.read(scoped_root / "dataset-manifest.json")
    inputs = {entry["benchmarkTaskId"]: (live.FIXTURES, entry) for entry in parent["tasks"]}
    inputs.update({entry["benchmarkTaskId"]: (scoped_root, entry) for entry in scoped["tasks"]})
    assert len(dataset.tasks) == 105
    for entry in dataset.manifest.tasks:
        directory, original = inputs[entry.benchmark_task_id]
        assert entry.split.value == original["split"]
        assert (live.LIVE_FIXTURES / entry.task_file).read_bytes() == (
            directory / original["taskFile"]
        ).read_bytes()
        assert (live.LIVE_FIXTURES / entry.ground_truth_file).read_bytes() == (
            directory / original["groundTruthFile"]
        ).read_bytes()
    assert sum(truth.diagnosis_contract is not None for truth in dataset.ground_truths) == 8


def test_retention_inventory_rejects_tampering_and_orphans(tmp_path):
    call_id, task_id, trace_id = "model:one", "task:000", "trace:one"
    prompt, output = "actual prompt", '{"kind":"actual candidate"}'
    payload_in = {
        "modelCallId": call_id,
        "taskId": task_id,
        "traceId": trace_id,
        "originalInputDigest": live.canonical_json_hash(prompt),
        "retainedInputDigest": live.canonical_json_hash(prompt),
        "modelVisibleInputRedacted": prompt,
    }
    payload_out = {
        "modelCallId": call_id,
        "originalOutputDigest": live.canonical_json_hash(output),
        "retainedOutputDigest": live.canonical_json_hash(output),
        "modelOutputRedacted": output,
    }
    live.write_once(tmp_path / "retention/calls/one-input.json", payload_in)
    live.write_once(tmp_path / "retention/calls/one-output.json", payload_out)
    ids = tuple(f"task:{index:03}" for index in range(105))
    for index, identity in enumerate(ids):
        live.write_once(tmp_path / f"ledger/{index}.json", {"taskId": identity})
    result = SimpleNamespace(
        benchmark_task_id=task_id,
        trace_id=trace_id,
        evaluation_run_id="run:one",
        model_call_ids=(call_id,),
        formal_evidence=SimpleNamespace(
            normalized_evaluation_facts={},
            trace_evidence=[
                {
                    "record_type": "model_call",
                    "event": "TERMINAL",
                    "model_call_id": call_id,
                    "status": "SUCCESS",
                    "model_input": {"sha256": live.canonical_json_hash(prompt)},
                    "model_output": {"sha256": live.canonical_json_hash(output)},
                }
            ],
        ),
    )
    run = SimpleNamespace(results=(result,), evaluation_run_id="run:one", selected_task_ids=ids)
    assert live.retention_integrity(run, tmp_path)["terminalCalls"] == 1
    no_call = SimpleNamespace(
        benchmark_task_id="task:001",
        trace_id="trace:no-call",
        evaluation_run_id="run:one",
        model_call_ids=(),
        formal_evidence=None,
    )
    run.results = (result, no_call)
    assert live.retention_integrity(run, tmp_path)["terminalCalls"] == 1
    payload_out["modelOutputRedacted"] = "changed"
    (tmp_path / "retention/calls/one-output.json").write_text(json.dumps(payload_out))
    with pytest.raises(RuntimeError, match="digest mismatch"):
        live.retention_integrity(run, tmp_path)


def test_revision_drift_is_rejected(monkeypatch):
    monkeypatch.setattr(live, "source_identity", lambda: {"source": "changed"})
    with pytest.raises(RuntimeError, match="REVISION_DRIFT"):
        live.assert_source({"sourceInventory": {"source": "frozen"}})


def test_persisted_task_missing_duplicate_and_content_mismatch_rejected(tmp_path):
    payload = {"benchmarkTaskId": "task:one", "evaluationRunId": "run:one"}
    result = SimpleNamespace(benchmark_task_id="task:one", model_dump=lambda **kwargs: payload)
    run = SimpleNamespace(results=(result,))
    with pytest.raises(RuntimeError, match="missing or duplicate"):
        live.persisted_task_integrity(run, tmp_path)
    live.write_once(tmp_path / "raw/task.json", payload)
    assert live.persisted_task_integrity(run, tmp_path) == 1
    live.write_once(tmp_path / "raw/duplicate.json", payload)
    with pytest.raises(RuntimeError, match="missing or duplicate"):
        live.persisted_task_integrity(run, tmp_path)
    (tmp_path / "raw/duplicate.json").unlink()
    (tmp_path / "raw/task.json").write_text(json.dumps({**payload, "unexpected": True}))
    with pytest.raises(RuntimeError, match="differs from execution"):
        live.persisted_task_integrity(run, tmp_path)
