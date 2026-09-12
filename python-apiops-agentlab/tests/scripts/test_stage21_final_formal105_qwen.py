"""Deterministic safeguards for the shared provider-neutral Stage21 Formal105 wrapper."""

from __future__ import annotations

import asyncio
import json
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path, PureWindowsPath
from runpy import run_path

import pytest
from pydantic import SecretStr

from app.benchmark import (
    MAX_PLANNED_ARTIFACT_PATH,
    BenchmarkExecutionMode,
    BenchmarkLifecycleStatus,
    BenchmarkRun,
    BenchmarkRunPolicy,
    BenchmarkTaskResult,
    BenchmarkTaskStatus,
    JavaExecutionStatus,
    JsonBenchmarkResultStore,
    TaskType,
    physical_task_result_filename,
)
from app.clients.qwen_structured_output import (
    DIAGNOSIS_REPORT_OUTPUT_SPEC,
    TESTCASE_CANDIDATE_OUTPUT_SPEC,
    schema_digest,
)
from app.core.settings import AppSettings

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "stage21_final_v2_formal105.py"
_ACCEPTANCE = (
    Path(__file__).resolve().parents[3]
    / "artifacts"
    / "stage21"
    / "qwen38-provider-acceptance-v3"
)
_HISTORICAL_ROOT = (
    Path(__file__).resolve().parents[3] / "artifacts" / "stage21" / "final-v2-formal105"
)


def _module() -> dict[str, object]:
    script_dir = str(_SCRIPT.parent)
    if script_dir not in sys.path:
        sys.path.insert(0, script_dir)
    return run_path(str(_SCRIPT))


def _settings(**overrides: object) -> AppSettings:
    values: dict[str, object] = {
        "qwen_api_key": SecretStr("test-qwen-key"),
        "deepseek_api_key": SecretStr("test-deepseek-key"),
        "java_apiops_base_url": "http://127.0.0.1:19090",
        "qwen_model": "qwen3.8-max",
    }
    values.update(overrides)
    return AppSettings(**values)


def test_final_revision_and_structured_output_identities_follow_runtime_schemas() -> None:
    module = _module()

    assert module["BENCHMARK_CONTRACT_REVISION"] == "stage21-formal105-final-closure-v5"
    identities = module["QWEN_SCHEMA_IDENTITIES"]
    assert identities["testcase"]["schemaDigest"] == schema_digest(
        TESTCASE_CANDIDATE_OUTPUT_SPEC.schema
    )
    assert identities["diagnosisReportContinuation"]["schemaDigest"] == schema_digest(
        DIAGNOSIS_REPORT_OUTPUT_SPEC.schema
    )


def _acceptance_for_current_model(tmp_path: Path) -> Path:
    """Copy the historical gate and update only its model identity for unit tests."""

    acceptance = tmp_path / "qwen-current-model-acceptance"
    acceptance.mkdir()
    for name in ("final-gate.md", "source-freeze.json", "quality-gate.json"):
        shutil.copyfile(_ACCEPTANCE / name, acceptance / name)
    source = json.loads((acceptance / "source-freeze.json").read_text(encoding="utf-8"))
    source["provider"]["model"] = "qwen3.8-max"
    (acceptance / "source-freeze.json").write_text(
        json.dumps(source, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return acceptance


def test_live_formal_requires_explicit_frozen_qwen_provider() -> None:
    module = _module()
    require = module["_require_provider"]

    with pytest.raises(RuntimeError, match="explicit --provider"):
        require(None)  # type: ignore[operator]
    assert require("qwen") == "qwen"  # type: ignore[operator]
    with pytest.raises(RuntimeError, match="frozen to qwen"):
        require("deepseek")  # type: ignore[operator]


def test_provider_propagates_to_existing_baseline(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module = _module()
    provider = "qwen"
    baseline = module["baseline"]
    calls: list[tuple[str, object]] = []

    def build_runner(settings: object, http_client: object, provider: str) -> object:
        del settings, http_client
        calls.append(("build", provider))
        return object()

    async def run_baseline(
        runner: object,
        settings: object,
        *,
        label: str,
        provider: str,
    ) -> str:
        del runner, settings
        calls.append((label, provider))
        return "completed"

    monkeypatch.setattr(baseline, "_build_runner", build_runner)
    monkeypatch.setattr(baseline, "_run_baseline", run_baseline)

    result = asyncio.run(
        module["_execute_baseline_once"](  # type: ignore[operator]
            _settings(),
            tmp_path,
            provider,
            object(),
        )
    )

    assert result == "completed"
    assert calls == [("build", provider), ("full-105", provider)]


def test_qwen_gate_failure_blocks_before_runner(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module = _module()
    acceptance = tmp_path / "acceptance"
    acceptance.mkdir()
    for name in ("final-gate.md", "source-freeze.json", "quality-gate.json"):
        shutil.copyfile(_ACCEPTANCE / name, acceptance / name)
    (acceptance / "final-gate.md").write_text("FORMAL105_STATUS = NOT_RUN\n", encoding="utf-8")

    with pytest.raises(RuntimeError, match="Qwen acceptance gate"):
        module["_qwen_provider_gate"](_settings(), acceptance)  # type: ignore[operator]


def test_wrong_qwen_model_identity_fails_closed() -> None:
    module = _module()

    with pytest.raises(RuntimeError, match="model identity"):
        module["_qwen_provider_gate"](  # type: ignore[operator]
            _settings(qwen_model="wrong-model"),
            _ACCEPTANCE,
        )


def test_qwen_environment_readiness_does_not_require_deepseek() -> None:
    module = _module()
    readiness = module["_environment_readiness"](_settings(), "qwen")  # type: ignore[operator]

    assert readiness["QWEN_API_KEY"] is True
    assert readiness["QWEN_BASE_URL"] is True
    assert readiness["QWEN_MODEL"] is True
    assert readiness["QWEN_TIMEOUT_SECONDS"] is True
    assert "DEEPSEEK_API_KEY" not in readiness["required"]

    missing = module["_environment_readiness"](  # type: ignore[operator]
        _settings(qwen_api_key=None),
        "qwen",
    )
    assert missing["QWEN_API_KEY"] is False


def test_qwen_freeze_manifest_has_provider_neutral_identity(tmp_path: Path) -> None:
    module = _module()
    dataset = module["load_dataset"](module["MANIFEST_PATH"])  # type: ignore[operator]
    policy = module["load_outcome_policy"](  # type: ignore[operator]
        module["POLICY_PATH"],
        dataset=dataset,
    )
    gate = module["_qwen_provider_gate"](  # type: ignore[operator]
        _settings(),
        _acceptance_for_current_model(tmp_path),
    )
    freeze = module["_freeze_manifest"](  # type: ignore[operator]
        _settings(),
        dataset,
        policy,
        provider="qwen",
        qwen_gate=gate,
        frozen_at="2026-09-02T00:00:00Z",
    )

    assert freeze["modelProvider"] == {
        "provider": "Qwen",
        "model": "qwen3.8-max",
    }
    assert "deepSeek" not in freeze
    assert "secret" not in json.dumps(freeze).lower()
    assert freeze["schemaVersion"] == "stage21-final-formal105-freeze/v5"
    contract = freeze["accuracyRepairContract"]
    assert contract["generationMetadata"]["taskIds"] == [
        "bench_task_testcase_happy_create_order_runner",
        "bench_task_formal_testcase_inventory_conflict_runner",
    ]
    assert contract["authorityBindings"]["directOutcomeAuthority"] is False
    assert contract["guardedTaskContract"]["groundTruthVersion"] == "v4"
    assert [row["groundTruthVersion"] for row in contract["guardedTaskContracts"]] == [
        "v4",
        "v2",
    ]
    assert contract["changeRecord"]["changesTaskSemantics"] is True
    assert contract["changeRecord"]["modelOutputBasis"] is False


def test_deepseek_freeze_is_rejected_for_v4_revision() -> None:
    module = _module()
    dataset = module["load_dataset"](module["MANIFEST_PATH"])  # type: ignore[operator]
    policy = module["load_outcome_policy"](  # type: ignore[operator]
        module["POLICY_PATH"],
        dataset=dataset,
    )
    with pytest.raises(RuntimeError, match="frozen to qwen"):
        module["_freeze_manifest"](  # type: ignore[operator]
            _settings(),
            dataset,
            policy,
            provider="deepseek",
            frozen_at="2026-09-02T00:00:00Z",
        )


def test_validate_only_and_finalize_existing_never_execute(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module = _module()
    calls: list[str] = []

    def fail_live(*args: object, **kwargs: object) -> None:
        del args, kwargs
        calls.append("live")
        raise AssertionError("live runner must not be called")

    def fake_finalize(path: Path, **kwargs: object) -> dict[str, object]:
        del kwargs
        calls.append(str(path))
        return {"status": "read-only"}

    globals_dict = module["main"].__globals__  # type: ignore[union-attr]
    monkeypatch.setitem(globals_dict, "_run_once", fail_live)
    monkeypatch.setitem(globals_dict, "_finalize", fake_finalize)

    monkeypatch.setattr(
        "sys.argv",
        [
            "stage21_final_v2_formal105.py",
            "--validate-only",
            "--provider",
            "qwen",
            "--qwen-acceptance-dir",
            str(_acceptance_for_current_model(tmp_path)),
        ],
    )
    module["main"]()  # type: ignore[operator]
    assert calls == []

    monkeypatch.setattr(
        "sys.argv",
        ["stage21_final_v2_formal105.py", "--finalize-existing", "--output-root", "run"],
    )
    module["main"]()  # type: ignore[operator]
    assert calls == [str(Path("run").resolve())]


def test_new_formal_output_rejects_existing_and_historical_roots(tmp_path: Path) -> None:
    module = _module()
    ensure_new = module["_ensure_new_output_root"]

    existing = tmp_path / "existing"
    existing.mkdir()
    (existing / "marker").write_text("x", encoding="utf-8")
    with pytest.raises(RuntimeError, match="already exists"):
        ensure_new(existing)  # type: ignore[operator]

    with pytest.raises(RuntimeError, match="historical"):
        ensure_new(_HISTORICAL_ROOT)  # type: ignore[operator]


def test_artifact_secret_scan_is_fail_closed(tmp_path: Path) -> None:
    module = _module()
    clean = tmp_path / "clean.json"
    clean.write_text('{"provider":"Qwen","model":"qwen3.8-max"}\n', encoding="utf-8")
    assert module["_scan_artifact_secrets"](tmp_path, ("test-secret",)) == []  # type: ignore[operator]
    clean.write_text('{"value":"test-secret"}\n', encoding="utf-8")
    assert module["_scan_artifact_secrets"](tmp_path, ("test-secret",)) == [clean]  # type: ignore[operator]


def test_original_261_char_path_regression_is_below_budget(tmp_path: Path) -> None:
    evaluation_run_id = "evaluation_run:stage21-real-model-full-105-20260902T125355Z"
    task_id = "bench_task_formal_failure_http500_transport_distinction"
    legacy_relative = (
        PureWindowsPath("python-apiops-agentlab/artifacts/stage21/final-formal105-qwen-20260902T125345Z")
        / "full-105/results"
        / evaluation_run_id.replace(":", "_")
        / f"{task_id}.json"
    )
    # Reproduce the 261-character Windows path independently of checkout location.
    legacy_root = PureWindowsPath("C:/") / ("r" * (261 - len(str(legacy_relative)) - 4))
    old_path = legacy_root / legacy_relative
    new_path = JsonBenchmarkResultStore(tmp_path / "results").task_path(
        evaluation_run_id,
        task_id,
    )

    assert len(str(old_path)) == 261
    assert len(str(new_path)) < MAX_PLANNED_ARTIFACT_PATH
    assert evaluation_run_id not in str(new_path)
    assert task_id not in str(new_path)


def test_full_105_manifest_path_preflight_is_deterministic(tmp_path: Path) -> None:
    module = _module()
    dataset = module["load_dataset"](module["MANIFEST_PATH"])  # type: ignore[operator]
    task_ids = tuple(entry.benchmark_task_id for entry in dataset.manifest.tasks)
    report = module["_formal105_path_preflight"](  # type: ignore[operator]
        tmp_path,
        "evaluation_run:stage21-real-model-full-105-20260902T125355Z",
        task_ids,
    )

    assert report["taskCount"] == 105
    assert report["uniqueTaskPaths"] == 105
    assert report["maxPathLength"] <= MAX_PLANNED_ARTIFACT_PATH
    assert report["overBudgetCount"] == 0
    assert report["providerCalls"] == 0
    assert report["javaExecutions"] == 0
    assert len(report["runLevelPathsChecked"]) >= 15  # type: ignore[arg-type]
    assert any("metrics.json" in entry["path"] for entry in report["runLevelPathsChecked"])  # type: ignore[index]


def test_planned_task_paths_are_unique_for_all_105_manifest_tasks(tmp_path: Path) -> None:
    module = _module()
    dataset = module["load_dataset"](module["MANIFEST_PATH"])  # type: ignore[operator]
    task_ids = tuple(entry.benchmark_task_id for entry in dataset.manifest.tasks)
    planned = module["_planned_formal105_artifact_paths"](  # type: ignore[operator]
        tmp_path,
        "evaluation_run:stage21-real-model-full-105-20260902T125355Z",
        task_ids,
    )
    task_paths = [str(path) for label, path in planned if label.startswith("baseline:task:")]

    assert len(task_paths) == 105
    assert len(set(task_paths)) == 105


def test_task_identity_survives_short_physical_filename(tmp_path: Path) -> None:
    module = _module()
    evaluation_run_id = "evaluation_run:stage21-real-model-full-105-20260902T125355Z"
    task_id = "bench_task_formal_failure_http500_transport_distinction"
    result = BenchmarkTaskResult(
        evaluationRunId=evaluation_run_id,
        benchmarkTaskId=task_id,
        taskType=TaskType.FAILURE_DIAGNOSIS,
        status=BenchmarkTaskStatus.SUCCESS,
        executionMode=BenchmarkExecutionMode.REAL_MODEL,
        javaExecutionStatus=JavaExecutionStatus.NOT_APPLICABLE,
        agentRunId="agent_run:full-identity",
        traceId="trace:full-identity",
        caseId=f"case:{evaluation_run_id}:{task_id}",
        setupStatus=BenchmarkLifecycleStatus.SUCCESS,
        cleanupStatus=BenchmarkLifecycleStatus.SUCCESS,
        durationMs=1.0,
    )
    store = JsonBenchmarkResultStore(tmp_path / "results")
    physical_path = store.persist_task(result)
    stored = json.loads(physical_path.read_text(encoding="utf-8"))

    assert physical_path.name == physical_task_result_filename(evaluation_run_id, task_id)
    assert physical_path.name != f"{task_id}.json"
    assert stored["benchmarkTaskId"] == task_id
    assert stored["evaluationRunId"] == evaluation_run_id
    assert stored["agentRunId"] == "agent_run:full-identity"
    assert stored["traceId"] == "trace:full-identity"
    assert stored["caseId"] == f"case:{evaluation_run_id}:{task_id}"

    run = BenchmarkRun(
        evaluationRunId=evaluation_run_id,
        datasetId="stage21-formal105",
        datasetVersion="v1",
        taskSchemaVersion="v1",
        selectedTaskIds=(task_id,),
        results=(result,),
        startedAt=datetime(2026, 9, 2, tzinfo=UTC),
        completedAt=datetime(2026, 9, 2, 0, 0, 1, tzinfo=UTC),
        policy=BenchmarkRunPolicy(),
    )
    module["_persist_task_results"](  # type: ignore[operator]
        tmp_path / "projection",
        run,
        provider="Qwen",
        model="qwen3.8-max",
    )
    projection_path = next((tmp_path / "projection/task-results").glob("*.json"))
    projection = json.loads(projection_path.read_text(encoding="utf-8"))
    assert projection["evaluationRunId"] == evaluation_run_id
    assert projection["benchmarkTaskId"] == task_id
    assert projection["provider"] == "Qwen"
    assert projection["model"] == "qwen3.8-max"


def test_path_preflight_fails_before_provider_java_or_persistence_side_effects(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module = _module()
    monkeypatch.setattr(module["final_revision"], "verify_frozen_revision", lambda *args: {})
    counters = {"provider": 0, "java": 0}

    async def fake_execute(*args: object, **kwargs: object) -> None:
        del args, kwargs
        counters["provider"] += 1
        counters["java"] += 1

    module["_execute_baseline_once"] = fake_execute
    output_root = tmp_path / ("x" * 200)
    with pytest.raises(RuntimeError, match="artifact path preflight failed"):
        asyncio.run(
            module["_run_once"](  # type: ignore[operator]
                _settings(),
                output_root,
                "qwen",
                acceptance_dir=_ACCEPTANCE,
                runtime_preflight=tmp_path / "runtime.json",
            )
        )

    assert counters == {"provider": 0, "java": 0}
    assert not output_root.exists()
    assert not list(tmp_path.rglob("*.json"))


def test_valid_full_105_preflight_has_no_live_side_effects(tmp_path: Path) -> None:
    module = _module()
    dataset = module["load_dataset"](module["MANIFEST_PATH"])  # type: ignore[operator]
    task_ids = tuple(entry.benchmark_task_id for entry in dataset.manifest.tasks)
    report = module["_formal105_path_preflight"](  # type: ignore[operator]
        tmp_path,
        "evaluation_run:stage21-real-model-full-105-20260902T125355Z",
        task_ids,
    )

    assert report["overBudgetCount"] == 0
    assert report["providerCalls"] == 0
    assert report["javaExecutions"] == 0
    assert not tmp_path.joinpath("full-105").exists()


def test_runtime_preflight_fails_closed_on_known_non_ready_tasks(tmp_path: Path) -> None:
    module = _module()
    run_path = tmp_path / "run.json"
    run_path.write_text(
        json.dumps(
            {
                "status": "STAGE21_ALL_105_INPUT_AUDIT_COMPLETE",
                "pendingClassificationCount": 0,
                "nonReadyTaskIds": ["bench_task_missing_report"],
                "verification": {"unresolvedJavaResourceCount": 1},
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(RuntimeError, match="not ready for execution"):
        module["_runtime_preflight_evidence"](run_path)  # type: ignore[operator]


def test_runtime_preflight_accepts_only_closed_resource_set(tmp_path: Path) -> None:
    module = _module()
    run_path = tmp_path / "run.json"
    run_path.write_text(
        json.dumps(
            {
                "status": "STAGE21_ALL_105_INPUT_AUDIT_COMPLETE",
                "pendingClassificationCount": 0,
                "nonReadyTaskIds": [],
                "classificationCounts": {"READY": 105},
                "verification": {"unresolvedJavaResourceCount": 0},
            }
        ),
        encoding="utf-8",
    )

    evidence = module["_runtime_preflight_evidence"](run_path)  # type: ignore[operator]

    assert evidence["status"] == "PASS"
    assert evidence["nonReadyTaskIds"] == ()
    assert evidence["unresolvedJavaResourceCount"] == 0
