"""Run the Stage 21 real-model baseline through the existing benchmark runner.

This is an operational entry point, not a second runner.  It selects the
existing manifest, constructs the selected existing provider client, and lets the
existing ``BenchmarkRunner`` call the thin real-workflow adapter.  The
``smoke`` and ``pilot`` outputs are kept separate from the formal ``full``
baseline so deterministic infrastructure evidence cannot be mistaken for a
model baseline.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import httpx

from app.benchmark import (
    FIXED_SUBSET_ID,
    FIXED_SUBSET_TASK_IDS,
    AuthProfileResolver,
    AuthProfileWorkflowAdapter,
    BaselineConfiguration,
    BenchmarkExecutionMode,
    BenchmarkRun,
    BenchmarkRunner,
    BenchmarkRunPolicy,
    ConfigurationValue,
    DatasetSplit,
    RealModelStage20WorkflowAdapter,
    Stage21AuthProfile,
    compare_fixed_subset_runs,
    load_dataset,
    persist_baseline_artifacts,
    persist_fixed_subset_comparison,
    run_formal_baseline,
)
from app.clients.java_apiops import JavaApiOpsClient
from app.clients.llm_provider import build_llm, provider_identity
from app.core.settings import AppSettings, get_settings
from app.evaluator import EVALUATOR_VERSION

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
MANIFEST_PATH = (
    REPOSITORY_ROOT
    / "python-apiops-agentlab"
    / "tests"
    / "benchmark"
    / "fixtures"
    / "dataset-manifest.json"
)
DEFAULT_OUTPUT_ROOT = REPOSITORY_ROOT / "artifacts" / "stage21" / "real-model-baseline"
BASELINE_CONFIG_ID = "stage21-real-model-baseline-v1"
BASELINE_CONFIG_VERSION = "stage21.5-real-model-v1"
WORKFLOW_VERSION = "stage21-real-model-adapter-v1"
TOOL_CATALOG_VERSION = "approved-tool-catalog-v1"
PILOT_TASK_IDS = (
    "bench_task_golden_testcase_happy",
    "bench_task_testcase_missing_required_api_id",
    "bench_task_golden_failure_diagnosis",
    "bench_task_failure_assertion_mismatch",
    "bench_task_golden_tool_safety",
    "bench_task_tool_allowed_rag_read",
    "bench_task_golden_rag_evidence",
    "bench_task_rag_multi_hit",
    "bench_task_golden_e2e_apiops",
    "bench_task_formal_e2e_generation_diagnosis_guarded",
)
REPRESENTATIVE_TASK_IDS = (
    "bench_task_golden_testcase_happy",
    "bench_task_golden_failure_diagnosis",
    "bench_task_golden_tool_safety",
    "bench_task_golden_rag_evidence",
    "bench_task_golden_e2e_apiops",
)


def _git_snapshot() -> dict[str, object]:
    try:
        revision = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=REPOSITORY_ROOT,
            capture_output=True,
            check=False,
            text=True,
            timeout=5,
        ).stdout.strip()
        status = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=REPOSITORY_ROOT,
            capture_output=True,
            check=False,
            text=True,
            timeout=5,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return {"revision": "UNAVAILABLE", "workingTreeDirty": "UNKNOWN"}
    return {
        "revision": revision or "UNAVAILABLE",
        "workingTreeDirty": bool(status.strip()),
    }


def _configuration(
    settings: AppSettings,
    split: str,
    provider: str = "deepseek",
) -> BaselineConfiguration:
    dataset = load_dataset(MANIFEST_PATH)
    git = _git_snapshot()
    identity = provider_identity(settings, provider)
    if provider == "deepseek":
        parameters = {
            "response_format": "json_object",
            "thinking": "disabled",
            "stream": False,
            "timeout_seconds": settings.deepseek_timeout_seconds,
        }
        request_source = "DeepSeekClient.complete request"
        model_source = "AppSettings.deepseek_model"
    else:
        parameters = {
            "response_format": "json_object",
            "enable_thinking": False,
            "stream": False,
            "timeout_seconds": settings.qwen_timeout_seconds,
        }
        request_source = "QwenClient.complete request"
        model_source = "AppSettings.qwen_model"
    model = {
        "provider": identity.provider,
        "model": identity.model,
    }
    prompts = (
        {"name": "testcase_generate", "version": "v1"},
        {"name": "testcase_repair", "version": "v1"},
        {"name": "diagnosis", "version": "1"},
    )
    return BaselineConfiguration(
        baselineConfigId=BASELINE_CONFIG_ID,
        datasetId=dataset.manifest.dataset_id,
        datasetVersion=dataset.manifest.dataset_version,
        datasetSplit=split,
        taskSchemaVersion=dataset.manifest.task_schema_version,
        modelIdentity=ConfigurationValue.available(model, source=model_source),
        modelParameters=ConfigurationValue.available(
            parameters,
            source=request_source,
        ),
        promptIdentities=tuple(
            ConfigurationValue.available(prompt, source="existing workflow prompt file")
            for prompt in prompts
        ),
        workflowIdentity=ConfigurationValue.available(
            {"name": "RealModelStage20WorkflowAdapter", "version": WORKFLOW_VERSION},
            source="app.benchmark.real_model",
        ),
        toolCatalogIdentity=ConfigurationValue.available(
            {"name": "ToolCatalog", "version": TOOL_CATALOG_VERSION},
            source="app.tools.ToolCatalog",
        ),
        evaluatorIdentity=ConfigurationValue.available(
            {"name": "RuleBasedEvaluator", "version": EVALUATOR_VERSION},
            source="app.evaluator.EVALUATOR_VERSION",
        ),
        benchmarkConfigVersion=BASELINE_CONFIG_VERSION,
        applicationIdentity=ConfigurationValue.available(
            git,
            source="git revision and working-tree snapshot",
        ),
        javaRuntimeVersion=ConfigurationValue.unavailable(
            source="Stage20 runtime context",
            reason="Java runtime version is not emitted by this Python process",
        ),
        pythonRuntimeVersion=ConfigurationValue.available(
            f"python {__import__('platform').python_version()}",
            source="platform.python_version",
        ),
        executionTimestamp=datetime.now(UTC),
    )


def _new_evaluation_run_id(label: str) -> str:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return f"evaluation_run:stage21-real-model-{label}-{stamp}"


def _task_status_summary(run: BenchmarkRun) -> dict[str, object]:
    return {
        "selected": len(run.selected_task_ids),
        "executed": len(run.results),
        "evaluated": sum(result.evaluation_result is not None for result in run.results),
        "status": dict(Counter(result.status.value for result in run.results)),
        "executionMode": dict(Counter(result.execution_mode.value for result in run.results)),
        "tasksWithModelCalls": sum(bool(result.model_call_ids) for result in run.results),
        "totalModelCalls": sum(result.model_call_count for result in run.results),
        "evaluationIds": sum(bool(result.evaluation_id) for result in run.results),
    }


def _representative_task_summary(run: BenchmarkRun) -> dict[str, object]:
    """Expose bounded task evidence for the test-owned representative harness."""

    summary = _task_status_summary(run)
    summary["taskResults"] = [
        {
            "benchmarkTaskId": result.benchmark_task_id,
            "taskType": result.task_type.value,
            "status": result.status.value,
            "executionMode": result.execution_mode.value,
            "javaExecutionStatus": result.java_execution_status.value,
            "agentRunId": result.agent_run_id,
            "traceId": result.trace_id,
            "runId": result.run_id,
            "reportId": result.report_id,
            "toolCallIds": list(result.tool_call_ids),
            "ragQueryIds": list(result.rag_query_ids),
            "modelCallIds": list(result.model_call_ids),
            "modelCallCount": result.model_call_count,
            "modelLatencyMs": result.model_latency_ms,
            "promptTokens": result.prompt_tokens,
            "completionTokens": result.completion_tokens,
            "totalTokens": result.total_tokens,
            "evaluationId": result.evaluation_id,
            "taskSuccess": (
                result.task_success.model_dump(mode="json")
                if result.task_success is not None
                else None
            ),
            "evaluationMetrics": (
                [metric.model_dump(mode="json") for metric in result.evaluation_result.metrics]
                if result.evaluation_result is not None
                else None
            ),
            "errorSummary": result.error_summary,
        }
        for result in run.results
    ]
    return summary


def _assert_real_model_observed(run: BenchmarkRun, label: str) -> None:
    missing = [
        result.benchmark_task_id
        for result in run.results
        if result.execution_mode is not BenchmarkExecutionMode.REAL_MODEL
        or not result.model_call_ids
    ]
    if missing:
        raise RuntimeError(
            f"{label} did not observe a real model call for {len(missing)} task(s): "
            + ", ".join(missing[:10])
        )


def _build_runner(
    settings: AppSettings,
    http_client: httpx.AsyncClient,
    provider: str = "deepseek",
) -> BenchmarkRunner:
    llm = build_llm(
        http_client,
        settings,
        provider=provider,
    )
    java_client = JavaApiOpsClient(
        http_client,
        base_url=settings.java_apiops_base_url,
        timeout_seconds=settings.java_apiops_timeout_seconds,
    )
    auth_profiles = AuthProfileResolver(java_client)
    profile_adapters = {
        profile: RealModelStage20WorkflowAdapter(
            llm,
            java_client=java_client,
            token_provider=auth_profiles.token_provider(profile),
            repository_root=REPOSITORY_ROOT,
        )
        for profile in Stage21AuthProfile
    }
    adapter = AuthProfileWorkflowAdapter(profile_adapters, auth_profiles)
    return BenchmarkRunner(
        adapter,
        policy=BenchmarkRunPolicy(
            taskTimeoutSeconds=max(
                180.0,
                (
                    settings.deepseek_timeout_seconds
                    if provider == "deepseek"
                    else settings.qwen_timeout_seconds
                )
                * 3,
            ),
            cleanupTimeoutSeconds=10.0,
            maxInfrastructureAttempts=1,
        ),
    )


async def _run_baseline(
    runner: BenchmarkRunner,
    settings: AppSettings,
    *,
    label: str,
    split: DatasetSplit | None = None,
    task_ids: tuple[str, ...] = (),
    golden_only: bool = False,
    provider: str = "deepseek",
    evaluation_run_id: str | None = None,
) -> object:
    effective_split = "all" if split is None else split.value.lower()
    configuration = _configuration(settings, effective_split, provider)
    return await run_formal_baseline(
        runner,
        configuration,
        evaluation_run_id=evaluation_run_id or _new_evaluation_run_id(label),
        output_dir=DEFAULT_OUTPUT_ROOT / label,
        manifest_path=MANIFEST_PATH,
        split=split,
        task_ids=task_ids,
        golden_only=golden_only,
    )


def _held_out_projection(
    full_result: object,
    settings: AppSettings,
    provider: str = "deepseek",
) -> object:
    full = full_result
    assert hasattr(full, "run")
    dataset = load_dataset(MANIFEST_PATH)
    held_out_ids = {
        entry.benchmark_task_id
        for entry in dataset.manifest.tasks
        if entry.split is DatasetSplit.HELD_OUT
    }
    held_out_run = full.run.model_copy(
        update={
            "split": DatasetSplit.HELD_OUT,
            "selected_task_ids": tuple(
                task_id for task_id in full.run.selected_task_ids if task_id in held_out_ids
            ),
            "results": tuple(
                result for result in full.run.results if result.benchmark_task_id in held_out_ids
            ),
        }
    )
    configuration = _configuration(settings, "held_out", provider).model_copy(
        update={"baseline_config_id": f"{BASELINE_CONFIG_ID}-held-out"}
    )
    return persist_baseline_artifacts(
        held_out_run,
        dataset,
        configuration,
        output_dir=DEFAULT_OUTPUT_ROOT / "held-out",
    )


def _load_latest_full_result(output_root: Path) -> object:
    results_root = output_root / "full-105" / "results"
    run_dirs = sorted(
        (path for path in results_root.iterdir() if path.is_dir()),
        key=lambda path: path.name,
        reverse=True,
    )
    if not run_dirs:
        raise RuntimeError(f"full baseline artifact not found under {results_root}")
    run_path = run_dirs[0] / "run.json"
    return SimpleNamespace(run=BenchmarkRun.model_validate_json(run_path.read_text()))


async def _run_post_full(
    settings: AppSettings,
    output_root: Path,
    provider: str = "deepseek",
) -> dict[str, object]:
    global DEFAULT_OUTPUT_ROOT
    DEFAULT_OUTPUT_ROOT = output_root.resolve()
    dataset = load_dataset(MANIFEST_PATH)
    full = _load_latest_full_result(DEFAULT_OUTPUT_ROOT)
    held_out = _held_out_projection(full, settings, provider)
    async with httpx.AsyncClient(trust_env=False) as http_client:
        runner = _build_runner(settings, http_client, provider)
        rerun_a = await _run_baseline(
            runner,
            settings,
            label="fixed-subset-rerun-a",
            split=DatasetSplit.DEV,
            task_ids=FIXED_SUBSET_TASK_IDS,
            provider=provider,
        )
        _assert_real_model_observed(rerun_a.run, "fixed-subset-rerun-a")
        rerun_b = await _run_baseline(
            runner,
            settings,
            label="fixed-subset-rerun-b",
            split=DatasetSplit.DEV,
            task_ids=FIXED_SUBSET_TASK_IDS,
            provider=provider,
        )
        _assert_real_model_observed(rerun_b.run, "fixed-subset-rerun-b")
        comparison = compare_fixed_subset_runs(
            rerun_a.run,
            rerun_b.run,
            subset_id=FIXED_SUBSET_ID,
            config_digest_a=rerun_a.configuration.configuration_digest,
            config_digest_b=rerun_b.configuration.configuration_digest,
        )
        comparison_path = persist_fixed_subset_comparison(
            comparison,
            DEFAULT_OUTPUT_ROOT / "fixed-subset-rerun.json",
        )
    return {
        "dataset": {
            "datasetId": dataset.manifest.dataset_id,
            "datasetVersion": dataset.manifest.dataset_version,
            "taskCount": len(dataset.tasks),
        },
        "heldOut": _task_status_summary(held_out.run),
        "rerunA": _task_status_summary(rerun_a.run),
        "rerunB": _task_status_summary(rerun_b.run),
        "fixedSubset": {
            "subsetId": FIXED_SUBSET_ID,
            "taskCount": len(FIXED_SUBSET_TASK_IDS),
            "configDigestEqual": comparison.config_digest_equal,
            "taskIdsEqual": comparison.task_ids_equal,
            "metricSchemaEqual": comparison.metric_schema_equal,
            "perTaskComparable": comparison.per_task_comparable,
            "aggregateComparable": comparison.aggregate_comparable,
            "observedDifferences": comparison.observed_differences,
            "artifact": str(comparison_path),
        },
        "artifacts": str(DEFAULT_OUTPUT_ROOT),
    }


async def _run_all(
    settings: AppSettings,
    output_root: Path,
    provider: str = "deepseek",
) -> dict[str, object]:
    global DEFAULT_OUTPUT_ROOT
    DEFAULT_OUTPUT_ROOT = output_root.resolve()
    dataset = load_dataset(MANIFEST_PATH)
    async with httpx.AsyncClient(trust_env=False) as http_client:
        runner = _build_runner(settings, http_client, provider)
        smoke = await _run_baseline(
            runner,
            settings,
            label="smoke",
            golden_only=True,
            provider=provider,
        )
        _assert_real_model_observed(smoke.run, "smoke")
        pilot = await _run_baseline(
            runner,
            settings,
            label="pilot-dev-10",
            split=DatasetSplit.DEV,
            task_ids=PILOT_TASK_IDS,
            provider=provider,
        )
        _assert_real_model_observed(pilot.run, "pilot")
        full = await _run_baseline(runner, settings, label="full-105", provider=provider)
        _assert_real_model_observed(full.run, "full")
        held_out = _held_out_projection(full, settings, provider)
        rerun_a = await _run_baseline(
            runner,
            settings,
            label="fixed-subset-rerun-a",
            split=DatasetSplit.DEV,
            task_ids=FIXED_SUBSET_TASK_IDS,
            provider=provider,
        )
        _assert_real_model_observed(rerun_a.run, "fixed-subset-rerun-a")
        rerun_b = await _run_baseline(
            runner,
            settings,
            label="fixed-subset-rerun-b",
            split=DatasetSplit.DEV,
            task_ids=FIXED_SUBSET_TASK_IDS,
            provider=provider,
        )
        _assert_real_model_observed(rerun_b.run, "fixed-subset-rerun-b")
        comparison = compare_fixed_subset_runs(
            rerun_a.run,
            rerun_b.run,
            subset_id=FIXED_SUBSET_ID,
            config_digest_a=rerun_a.configuration.configuration_digest,
            config_digest_b=rerun_b.configuration.configuration_digest,
        )
        comparison_path = persist_fixed_subset_comparison(
            comparison,
            DEFAULT_OUTPUT_ROOT / "fixed-subset-rerun.json",
        )
    return {
        "dataset": {
            "datasetId": dataset.manifest.dataset_id,
            "datasetVersion": dataset.manifest.dataset_version,
            "taskCount": len(dataset.tasks),
        },
        "smoke": _task_status_summary(smoke.run),
        "pilot": _task_status_summary(pilot.run),
        "full": _task_status_summary(full.run),
        "heldOut": _task_status_summary(held_out.run),
        "rerunA": _task_status_summary(rerun_a.run),
        "rerunB": _task_status_summary(rerun_b.run),
        "fixedSubset": {
            "subsetId": FIXED_SUBSET_ID,
            "taskCount": len(FIXED_SUBSET_TASK_IDS),
            "configDigestEqual": comparison.config_digest_equal,
            "taskIdsEqual": comparison.task_ids_equal,
            "metricSchemaEqual": comparison.metric_schema_equal,
            "perTaskComparable": comparison.per_task_comparable,
            "aggregateComparable": comparison.aggregate_comparable,
            "observedDifferences": comparison.observed_differences,
            "artifact": str(comparison_path),
        },
        "artifacts": str(DEFAULT_OUTPUT_ROOT),
    }


async def _run_one(
    settings: AppSettings,
    output_root: Path,
    phase: str,
    provider: str = "deepseek",
) -> dict[str, object]:
    if phase == "all":
        return await _run_all(settings, output_root, provider)
    if phase == "post-full":
        return await _run_post_full(settings, output_root, provider)
    global DEFAULT_OUTPUT_ROOT
    DEFAULT_OUTPUT_ROOT = output_root.resolve()
    async with httpx.AsyncClient(trust_env=False) as http_client:
        runner = _build_runner(settings, http_client, provider)
        if phase == "representative-smoke":
            result = await _run_baseline(
                runner,
                settings,
                label="representative-smoke",
                task_ids=REPRESENTATIVE_TASK_IDS,
                provider=provider,
            )
            _assert_real_model_observed(result.run, phase)
            return {
                phase: _representative_task_summary(result.run),
                "artifacts": str(DEFAULT_OUTPUT_ROOT / phase),
            }
        if phase == "smoke":
            result = await _run_baseline(
                runner,
                settings,
                label="smoke",
                golden_only=True,
                provider=provider,
            )
        elif phase == "pilot":
            result = await _run_baseline(
                runner,
                settings,
                label="pilot-dev-10",
                split=DatasetSplit.DEV,
                task_ids=PILOT_TASK_IDS,
                provider=provider,
            )
        else:
            result = await _run_baseline(runner, settings, label="full-105", provider=provider)
        _assert_real_model_observed(result.run, phase)
    return {phase: _task_status_summary(result.run), "artifacts": str(DEFAULT_OUTPUT_ROOT)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "phase",
        choices=("representative-smoke", "smoke", "pilot", "full", "post-full", "all"),
        nargs="?",
        default="all",
    )
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--provider", choices=("deepseek", "qwen"), default="deepseek")
    args = parser.parse_args()
    settings = get_settings()
    summary = asyncio.run(_run_one(settings, args.output_root, args.phase, args.provider))
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
