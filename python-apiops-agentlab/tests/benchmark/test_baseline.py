from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

import app.benchmark.baseline as baseline_module
from app.benchmark import (
    BaselineConfiguration,
    BaselineRunRecord,
    BenchmarkExecutionOutcome,
    BenchmarkFailureCategory,
    BenchmarkRunner,
    BenchmarkTaskFailure,
    BenchmarkTaskStatus,
    ConfigurationValue,
    DatasetSplit,
    FailureInventory,
    JsonBenchmarkResultStore,
    MetadataAvailability,
    ReproducibilityRecord,
    capture_git_revision,
    capture_python_runtime,
    load_dataset,
    persist_baseline_artifacts,
    run_formal_baseline,
    unavailable_java_runtime,
)
from app.evaluator import (
    EvaluationFacts,
    EvaluationResult,
    MetricName,
    MetricsCalculator,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
FIXED_TIMESTAMP = datetime(2026, 8, 26, 12, 0, tzinfo=UTC)


def _configuration(
    dataset,
    *,
    baseline_id: str = "stage21-baseline-test",
    dataset_split: str = "all",
) -> BaselineConfiguration:
    return BaselineConfiguration(
        baselineConfigId=baseline_id,
        datasetId=dataset.manifest.dataset_id,
        datasetVersion=dataset.manifest.dataset_version,
        datasetSplit=dataset_split,
        taskSchemaVersion=dataset.manifest.task_schema_version,
        modelIdentity=ConfigurationValue.unavailable(
            source="test baseline",
            reason="no external Agent model is invoked by this deterministic adapter",
        ),
        modelParameters=ConfigurationValue.unavailable(
            source="test baseline",
            reason="no model call parameters are available",
        ),
        promptIdentities=(
            ConfigurationValue.unavailable(
                source="test baseline",
                reason="no prompt is invoked by this deterministic adapter",
            ),
        ),
        workflowIdentity=ConfigurationValue.available(
            "BenchmarkRunner/test-stage20-adapter",
            source="test baseline",
        ),
        toolCatalogIdentity=ConfigurationValue.available(
            "existing-stage20-tool-catalog",
            source="test baseline",
        ),
        evaluatorIdentity=ConfigurationValue.available(
            "rule-evaluator-v1",
            source="app.evaluator.EVALUATOR_VERSION",
        ),
        benchmarkConfigVersion="stage21.5-baseline-v1",
        applicationIdentity=capture_git_revision(REPOSITORY_ROOT),
        javaRuntimeVersion=unavailable_java_runtime(),
        pythonRuntimeVersion=capture_python_runtime(),
        executionTimestamp=FIXED_TIMESTAMP,
    )


class EmptyFactsStage20Adapter:
    def __init__(self, failing_task_id: str | None = None) -> None:
        self.failing_task_id = failing_task_id
        self.calls: list[str] = []

    async def execute(
        self,
        task,
        setup,
        *,
        trace_id: str,
        agent_run_id: str,
    ) -> BenchmarkExecutionOutcome:
        self.calls.append(task.benchmark_task_id)
        if task.benchmark_task_id == self.failing_task_id:
            raise BenchmarkTaskFailure(
                "controlled baseline adapter failure",
                category=BenchmarkFailureCategory.AGENT_FAILURE,
                code="CONTROLLED_BASELINE_FAILURE",
            )
        return BenchmarkExecutionOutcome(
            trace_id=trace_id,
            agent_run_id=agent_run_id,
            facts=EvaluationFacts(),
        )


def _metric(aggregate, name: MetricName):
    return next(metric for metric in aggregate.metrics if metric.metric is name)


@pytest.mark.anyio
async def test_formal_baseline_runs_active_dataset_and_persists_stage19_views(
    tmp_path: Path,
) -> None:
    dataset = load_dataset()
    adapter = EmptyFactsStage20Adapter()
    configuration = _configuration(dataset)
    result = await run_formal_baseline(
        BenchmarkRunner(adapter),
        configuration,
        evaluation_run_id="evaluation_run:stage21-baseline-test",
        output_dir=tmp_path / "baseline",
    )

    assert len(result.run.selected_task_ids) == 105
    assert len(result.run.results) == 105
    assert all(item.status is BenchmarkTaskStatus.SUCCESS for item in result.run.results)
    assert all(isinstance(item.evaluation_result, EvaluationResult) for item in result.run.results)
    assert result.overall_metrics.case_count == 105
    assert {item.category.value: item.task_count for item in result.category_metrics} == {
        "TESTCASE_GENERATION": 30,
        "FAILURE_DIAGNOSIS": 34,
        "TOOL_SAFETY": 21,
        "RAG_EVIDENCE_RETRIEVAL": 15,
        "E2E_APIOPS": 5,
    }
    assert result.reproducibility.configuration == configuration
    assert result.reproducibility.configuration_digest == configuration.configuration_digest

    artifacts = result.artifacts
    assert artifacts.baseline_config.is_file()
    assert artifacts.baseline_run.is_file()
    assert artifacts.failure_inventory.is_file()
    assert artifacts.reproducibility.is_file()
    assert artifacts.evaluation_csv.is_file()
    assert artifacts.baseline_report.is_file()
    assert artifacts.run.is_file()
    assert len(artifacts.task_results) == 105
    assert all(path.is_file() for path in artifacts.task_results)

    persisted_config = json.loads(artifacts.baseline_config.read_text(encoding="utf-8"))
    assert persisted_config["datasetId"] == dataset.manifest.dataset_id
    assert persisted_config["javaRuntimeVersion"]["availability"] == "UNAVAILABLE"
    assert persisted_config["modelIdentity"]["availability"] == "UNAVAILABLE"
    assert (
        BaselineRunRecord.model_validate_json(
            artifacts.baseline_run.read_text(encoding="utf-8")
        ).benchmark_run_id
        == result.run.evaluation_run_id
    )
    assert (
        FailureInventory.model_validate_json(
            artifacts.failure_inventory.read_text(encoding="utf-8")
        ).failure_count
        == 0
    )
    assert (
        ReproducibilityRecord.model_validate_json(
            artifacts.reproducibility.read_text(encoding="utf-8")
        ).configuration_digest
        == configuration.configuration_digest
    )

    for metric_name in (MetricName.TOTAL_TOKENS, MetricName.COST):
        metric = _metric(result.overall_metrics, metric_name)
        assert metric.value_count == 0
        assert metric.mean is None
        assert metric.rate is None
        assert metric.not_applicable_count + metric.unknown_count + metric.error_count == 105
    assert "Collateral Damage is not a baseline metric here" in artifacts.baseline_report.read_text(
        encoding="utf-8"
    )

    print(
        "STAGE21_FORMAL_BASELINE "
        + json.dumps(
            {
                "baselineConfigId": configuration.baseline_config_id,
                "evaluationRunId": result.run.evaluation_run_id,
                "selected": len(result.run.selected_task_ids),
                "executed": len(result.run.results),
                "evaluated": result.overall_metrics.case_count,
                "failureTasks": result.failure_inventory.failure_count,
                "categoryTasks": {
                    item.category.value: item.task_count for item in result.category_metrics
                },
                "artifacts": str(artifacts.root),
            },
            sort_keys=True,
        )
    )

    report_before = artifacts.baseline_report.read_bytes()
    persisted_again = persist_baseline_artifacts(
        result.run,
        dataset,
        configuration,
        output_dir=tmp_path / "baseline",
        result_store=JsonBenchmarkResultStore(tmp_path / "baseline" / "results"),
    )
    assert persisted_again.artifacts.baseline_report.read_bytes() == report_before


@pytest.mark.anyio
async def test_failure_inventory_links_existing_task_failure_and_keeps_evaluation_refs(
    tmp_path: Path,
) -> None:
    dataset = load_dataset()
    failing_id = "bench_task_golden_testcase_happy"
    selected = (
        failing_id,
        "bench_task_golden_rag_evidence",
    )
    adapter = EmptyFactsStage20Adapter(failing_task_id=failing_id)
    result = await run_formal_baseline(
        BenchmarkRunner(adapter),
        _configuration(dataset, baseline_id="stage21-failure-inventory-test"),
        evaluation_run_id="evaluation_run:stage21-failure-inventory-test",
        output_dir=tmp_path / "baseline",
        task_ids=selected,
    )

    assert len(result.run.results) == 2
    failed_result = next(
        item for item in result.run.results if item.benchmark_task_id == failing_id
    )
    assert failed_result.status is BenchmarkTaskStatus.FAILED
    assert failed_result.evaluation_result is None
    assert result.failure_inventory.failure_count >= 1
    failure = next(
        item for item in result.failure_inventory.items if item.benchmark_task_id == failing_id
    )
    assert failure.failure_category == BenchmarkFailureCategory.AGENT_FAILURE.value
    assert failure.failure_code == "CONTROLLED_BASELINE_FAILURE"
    assert failure.evaluation_id is None
    assert Path(failure.artifact_ref).name.startswith("task-")
    assert not failure.artifact_ref.endswith(f"{failing_id}.json")
    assert Path(result.artifacts.root / failure.artifact_ref).is_file()


@pytest.mark.anyio
async def test_existing_metrics_calculator_is_the_baseline_aggregation_authority(
    tmp_path: Path,
) -> None:
    dataset = load_dataset()
    result = await run_formal_baseline(
        BenchmarkRunner(EmptyFactsStage20Adapter()),
        _configuration(dataset, baseline_id="stage21-aggregation-test", dataset_split="dev"),
        evaluation_run_id="evaluation_run:stage21-aggregation-test",
        output_dir=tmp_path / "baseline",
        split=DatasetSplit.DEV,
    )

    evaluation_results = tuple(
        item.evaluation_result for item in result.run.results if item.evaluation_result is not None
    )
    expected = MetricsCalculator().calculate(evaluation_results)
    assert result.overall_metrics == expected
    assert all(
        category.metrics
        == MetricsCalculator().calculate(
            tuple(
                item.evaluation_result
                for item in result.run.results
                if item.evaluation_result is not None and item.task_type is category.category
            )
        )
        for category in result.category_metrics
    )


@pytest.mark.anyio
async def test_existing_baseline_identity_rejects_different_configuration(tmp_path: Path) -> None:
    dataset = load_dataset()
    adapter = EmptyFactsStage20Adapter()
    runner = BenchmarkRunner(adapter)
    output_dir = tmp_path / "baseline"
    evaluation_run_id = "evaluation_run:stage21-immutable-test"
    configuration = _configuration(dataset, baseline_id="stage21-immutable-test")
    await run_formal_baseline(
        runner,
        configuration,
        evaluation_run_id=evaluation_run_id,
        output_dir=output_dir,
        task_ids=("bench_task_golden_testcase_happy",),
    )
    changed = configuration.model_copy(update={"benchmark_config_version": "stage21.5-other"})

    with pytest.raises(FileExistsError, match="different configuration"):
        await run_formal_baseline(
            runner,
            changed,
            evaluation_run_id=evaluation_run_id,
            output_dir=output_dir,
            task_ids=("bench_task_golden_testcase_happy",),
        )
    assert adapter.calls == ["bench_task_golden_testcase_happy"]


@pytest.mark.anyio
async def test_report_failure_does_not_mutate_existing_execution_run(
    tmp_path: Path, monkeypatch
) -> None:
    dataset = load_dataset()
    store = JsonBenchmarkResultStore(tmp_path / "results")
    run = await BenchmarkRunner(EmptyFactsStage20Adapter(), result_store=store).run_batch(
        dataset,
        evaluation_run_id="evaluation_run:stage21-report-failure-test",
        task_ids=("bench_task_golden_testcase_happy",),
    )
    before = run.model_dump(mode="json")

    def fail_report(*args, **kwargs):
        raise RuntimeError("controlled report failure")

    monkeypatch.setattr(baseline_module, "render_evaluation_report", fail_report)
    with pytest.raises(RuntimeError, match="controlled report failure"):
        persist_baseline_artifacts(
            run,
            dataset,
            _configuration(dataset, baseline_id="stage21-report-failure-test"),
            output_dir=tmp_path,
            result_store=store,
        )
    assert run.model_dump(mode="json") == before


def test_configuration_value_requires_explicit_missing_metadata_state() -> None:
    with pytest.raises(ValueError):
        ConfigurationValue(availability=MetadataAvailability.UNKNOWN, source="invalid")


def test_runtime_capture_is_read_only_and_typed() -> None:
    python_runtime = capture_python_runtime()
    git_revision = capture_git_revision(REPOSITORY_ROOT)
    assert python_runtime.availability.value == "AVAILABLE"
    assert python_runtime.value
    assert git_revision.availability.value in {"AVAILABLE", "UNAVAILABLE", "UNKNOWN"}
