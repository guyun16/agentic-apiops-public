"""Replay the Stage 21 v4 non-prompt residual cohort after targeted repairs."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import stage21_final_v2_formal105 as formal
import stage21_real_model_baseline as baseline
import stage21_v3_residual_live as residual_pipeline
import stage21_v4_final_residual_prompt_repair as prompt_audit

from app.benchmark import load_dataset
from app.benchmark.outcome_v2 import (
    OutcomeV2Projection,
    V2OutcomeStatus,
    load_outcome_policy,
    project_outcome_v2,
)
from app.benchmark.provider_integrity import verify_provider_integrity
from app.benchmark.runner import BenchmarkRun
from app.core.settings import get_settings

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
OFFICIAL_ROOT = prompt_audit.OFFICIAL_ROOT
OFFICIAL_REVISION = prompt_audit.OFFICIAL_REVISION
OFFICIAL_RUN_ID = prompt_audit.OFFICIAL_RUN_ID
CANDIDATE_REVISION = "stage21-formal105-nonprompt-residual-repair-v1"
COHORT_LABEL = "nonprompt-residual"

PROMPT_TASKS = frozenset(prompt_audit.TARGETED_TASKS)
TARGETED_TASKS = tuple(
    sorted(set(prompt_audit._CLASSIFICATIONS) - PROMPT_TASKS)
)
CATEGORY_BY_TASK = {
    task_id: prompt_audit._CLASSIFICATIONS[task_id][0] for task_id in TARGETED_TASKS
}
# The task-level authority audit proved that these two original TOOL / RAG
# classifications are downstream symptoms of a project/corpus contract mismatch.
# Preserve the original classification for auditability and use the repaired
# category only when attributing gains.
REPAIR_CATEGORY_BY_TASK = {
    **CATEGORY_BY_TASK,
    "bench_task_golden_failure_diagnosis": "BENCHMARK CONTRACT",
    "bench_task_rag_multi_hit": "BENCHMARK CONTRACT",
}

PROMPT_PATHS = {
    "diagnosis": REPOSITORY_ROOT
    / "python-apiops-agentlab/app/agents/prompts/diagnosis_v1.txt",
    "diagnosisSemanticRepair": REPOSITORY_ROOT
    / "python-apiops-agentlab/app/agents/prompts/diagnosis_semantic_repair_v1.txt",
    "diagnosisMemoryRefinement": REPOSITORY_ROOT
    / "python-apiops-agentlab/app/agents/prompts/diagnosis_memory_refinement_v1.txt",
    "testcaseGenerate": REPOSITORY_ROOT
    / "python-apiops-agentlab/app/agents/prompts/testcase_generate_v1.txt",
    "testcaseRepair": REPOSITORY_ROOT
    / "python-apiops-agentlab/app/agents/prompts/testcase_repair_v1.txt",
}


def _prompt_digests() -> dict[str, str]:
    return {name: formal._sha256_file(path) for name, path in PROMPT_PATHS.items()}


def _status_counts(projection: OutcomeV2Projection) -> Counter[str]:
    return Counter(task.v2_status.value for task in projection.tasks)


def _comparison(
    old: OutcomeV2Projection,
    new: OutcomeV2Projection,
    run: BenchmarkRun,
    provider: dict[str, Any],
) -> dict[str, object]:
    old_by_id = {item.benchmark_task_id: item for item in old.tasks}
    new_by_id = {item.benchmark_task_id: item for item in new.tasks}
    result_by_id = {item.benchmark_task_id: item for item in run.results}
    transitions: Counter[str] = Counter()
    category_gains: Counter[str] = Counter()
    tasks: list[dict[str, object]] = []
    for task_id in TARGETED_TASKS:
        previous = old_by_id[task_id]
        current = new_by_id[task_id]
        result = result_by_id[task_id]
        transition = f"{previous.v2_status.value}->{current.v2_status.value}"
        transitions[transition] += 1
        if current.v2_status is V2OutcomeStatus.PASS:
            category_gains[REPAIR_CATEGORY_BY_TASK[task_id]] += 1
        tasks.append(
            {
                "benchmarkTaskId": task_id,
                "rootCauseCategory": CATEGORY_BY_TASK[task_id],
                "repairCategory": REPAIR_CATEGORY_BY_TASK[task_id],
                "oldStatus": previous.v2_status.value,
                "newStatus": current.v2_status.value,
                "transition": transition,
                "runtimeStatus": result.status.value,
                "failureCategory": result.failure_category,
                "failureCode": result.failure_code,
                "modelCallCount": result.model_call_count,
                "outcomeAuthority": current.outcome_authority.value,
                "outcomeAuthorityGap": current.outcome_authority_gap,
                "outcomeMetrics": [
                    metric.model_dump(mode="json") for metric in current.outcome_metrics
                ],
            }
        )

    counts = _status_counts(new)
    passed = counts["PASS"]
    failed = counts["FAIL"]
    unknown = counts["UNKNOWN"]
    denominator = passed + failed
    direct_gain = category_gains["BENCHMARK CONTRACT"] + category_gains[
        "EVALUATOR / AUTHORITY"
    ]
    real_gain = (
        category_gains["WORKFLOW"]
        + category_gains["TOOL / RAG"]
        + category_gains["RUNTIME"]
    )
    return {
        "schemaVersion": "stage21-v4-nonprompt-residual-comparison/v1",
        "targetedTaskCount": len(TARGETED_TASKS),
        "transitionCounts": dict(sorted(transitions.items())),
        "categoryPassGains": dict(sorted(category_gains.items())),
        "oldFailToPass": transitions["FAIL->PASS"],
        "oldUnknownToPass": transitions["UNKNOWN->PASS"],
        "stillFail": failed,
        "stillUnknown": unknown,
        "targetedPass": passed,
        "targetedFail": failed,
        "targetedUnknown": unknown,
        "targetedPassRate": passed / len(TARGETED_TASKS),
        "targetedOutcomeAccuracy": passed / denominator if denominator else None,
        "directEvaluatorContractGain": direct_gain,
        "realWorkflowRuntimeGain": real_gain,
        "providerIntegrity": provider,
        "tasks": tasks,
    }


def _estimated_formal105(
    old: OutcomeV2Projection, comparison: dict[str, object]
) -> dict[str, object]:
    counts = Counter(old.v2_status_counts)
    # The immediately preceding prompt-repair replay proved one UNKNOWN->PASS gain.
    counts["UNKNOWN"] -= 1
    counts["PASS"] += 1
    for task in comparison["tasks"]:
        assert isinstance(task, dict)
        old_status = str(task["oldStatus"])
        new_status = str(task["newStatus"])
        counts[old_status] -= 1
        counts[new_status] += 1
    denominator = counts["PASS"] + counts["FAIL"]
    return {
        "basis": "official-v4 plus proven prompt replay plus this non-prompt replay",
        "priorPromptGain": 1,
        "pass": counts["PASS"],
        "fail": counts["FAIL"],
        "unknown": counts["UNKNOWN"],
        "passRate": counts["PASS"] / 105,
        "outcomeAccuracy": counts["PASS"] / denominator if denominator else None,
    }


async def _run(output_root: Path, acceptance_dir: Path) -> dict[str, object]:
    if output_root.exists():
        raise RuntimeError(f"targeted output already exists: {output_root}")
    if len(TARGETED_TASKS) != 33:
        raise RuntimeError("non-prompt residual cohort must contain exactly 33 tasks")
    old_projection, _old_run, old_run_path = prompt_audit._official_inputs()
    historical_before = {
        "tree": prompt_audit._tree_digest(OFFICIAL_ROOT),
        "freeze": formal._sha256_file(OFFICIAL_ROOT / "freeze-manifest.json"),
        "outcome": formal._sha256_file(OFFICIAL_ROOT / "outcome-v2.json"),
        "run": formal._sha256_file(old_run_path),
    }
    prompt_before = _prompt_digests()

    settings = get_settings()
    if settings.qwen_model != formal.EXPECTED_QWEN_MODEL:
        raise RuntimeError("targeted replay requires qwen3.8-max")
    dataset = load_dataset(formal.MANIFEST_PATH)
    policy = load_outcome_policy(formal.POLICY_PATH, dataset=dataset)
    qwen_gate = formal._qwen_provider_gate(settings, acceptance_dir)
    environment = formal._environment_readiness(settings, "qwen")
    if environment.get("ready") is not True:
        missing = [name for name, ready in environment["required"].items() if not ready]
        raise RuntimeError("targeted replay environment is incomplete: " + ", ".join(missing))

    original_cohort = residual_pipeline.RESIDUAL_TASKS
    residual_pipeline.RESIDUAL_TASKS = TARGETED_TASKS
    try:
        preflight = await residual_pipeline._focused_runtime_preflight(settings, dataset)
    finally:
        residual_pipeline.RESIDUAL_TASKS = original_cohort
    if preflight.get("status") != "PASS":
        raise RuntimeError("targeted runtime preflight failed closed")

    output_root.mkdir(parents=True)
    prompt_audit._write_json(output_root / "focused-runtime-preflight.json", preflight)
    prompt_audit._write_json(
        output_root / "repair-manifest.json",
        {
            "schemaVersion": "stage21-v4-nonprompt-residual-repair/v1",
            "benchmarkRevision": CANDIDATE_REVISION,
            "sourceBenchmarkRevision": OFFICIAL_REVISION,
            "formal105Status": "NOT_RUN",
            "sourceOfficial": {
                "root": str(OFFICIAL_ROOT),
                "evaluationRunId": OFFICIAL_RUN_ID,
                "digests": historical_before,
            },
            "provider": {"provider": "Qwen", "model": settings.qwen_model},
            "providerAcceptance": qwen_gate,
            "targetedTaskIds": list(TARGETED_TASKS),
            "rootCauseCategories": CATEGORY_BY_TASK,
            "repairCategories": REPAIR_CATEGORY_BY_TASK,
            "promptFrozenDigests": prompt_before,
            "createdAt": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        },
    )

    baseline.DEFAULT_OUTPUT_ROOT = output_root
    evaluation_run_id = (
        "evaluation_run:stage21-v4-nonprompt-targeted-"
        + datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    )
    async with httpx.AsyncClient(trust_env=False) as http_client:
        runner = baseline._build_runner(settings, http_client, provider="qwen")
        result = await baseline._run_baseline(
            runner,
            settings,
            label=COHORT_LABEL,
            task_ids=TARGETED_TASKS,
            provider="qwen",
            evaluation_run_id=evaluation_run_id,
        )

    provider = verify_provider_integrity(
        result.run.results,
        expected_provider="Qwen",
        expected_model=formal.EXPECTED_QWEN_MODEL,
    )
    projection = project_outcome_v2(
        result.run,
        policy,
        source_artifact=output_root / COHORT_LABEL,
        require_full_dataset=False,
    )
    comparison = _comparison(old_projection, projection, result.run, provider)
    estimate = _estimated_formal105(old_projection, comparison)
    prompt_audit._write_json(output_root / "provider-integrity.json", provider)
    prompt_audit._write_json(
        output_root / "outcome-v2-targeted.json", projection.model_dump(mode="json")
    )
    prompt_audit._write_json(output_root / "targeted-comparison.json", comparison)

    historical_after = {
        "tree": prompt_audit._tree_digest(OFFICIAL_ROOT),
        "freeze": formal._sha256_file(OFFICIAL_ROOT / "freeze-manifest.json"),
        "outcome": formal._sha256_file(OFFICIAL_ROOT / "outcome-v2.json"),
        "run": formal._sha256_file(old_run_path),
    }
    prompt_after = _prompt_digests()
    secret_values = tuple(
        {
            *formal._known_secret_values(settings),
            *(
                value
                for name in (
                    "STAGE21_NORMAL_PASSWORD",
                    "STAGE21_SAFETY41_PASSWORD",
                    "STAGE21_SAFETY42_PASSWORD",
                    "APIOPS_STAGE21_DB_PASSWORD",
                    "ZHIPU_API_KEY",
                )
                if (value := os.environ.get(name, "").strip())
            ),
        }
    )
    leakage = formal._scan_artifact_secrets(output_root, secret_values)
    provider_clean = (
        provider.get("status") == "PROVIDER_PROVEN"
        and not provider.get("unprovenTaskIds")
        and not provider.get("mismatchTaskIds")
        and not provider.get("actualFallbackTaskIds")
    )
    selected = tuple(result.run.selected_task_ids)
    persisted = tuple(item.benchmark_task_id for item in result.run.results)
    checks = {
        "selectedExactly33": len(selected) == 33 and set(selected) == set(TARGETED_TASKS),
        "executedExactly33": len(persisted) == 33 and set(persisted) == set(TARGETED_TASKS),
        "noDuplicates": len(set(persisted)) == 33,
        "full105NotRun": len(result.run.results) != 105,
        "providerIntegrity": provider_clean,
        "historicalOfficialPreserved": historical_before == historical_after,
        "promptFrozen": prompt_before == prompt_after,
        "credentialLeakageAbsent": not leakage,
    }
    remaining_model_failures = [
        task["benchmarkTaskId"]
        for task in comparison["tasks"]
        if task["failureCode"] == "MODEL_OUTPUT_FAILURE"
    ]
    summary = {
        "schemaVersion": "stage21-v4-nonprompt-residual-repair-summary/v1",
        "status": "PASS" if all(checks.values()) else "FAIL",
        "benchmarkRevision": CANDIDATE_REVISION,
        "sourceBenchmarkRevision": OFFICIAL_REVISION,
        "evaluationRunId": result.run.evaluation_run_id,
        "officialRoot": str(OFFICIAL_ROOT),
        "outputRoot": str(output_root),
        "provider": {"provider": "Qwen", "model": settings.qwen_model},
        "targetedTaskIds": list(TARGETED_TASKS),
        "runtimeStatusCounts": dict(
            sorted(Counter(item.status.value for item in result.run.results).items())
        ),
        "comparison": comparison,
        "estimatedFormal105": estimate,
        "remainingGenuineAgentFailureIds": remaining_model_failures,
        "historicalOfficialDigestsBefore": historical_before,
        "historicalOfficialDigestsAfter": historical_after,
        "promptDigestsBefore": prompt_before,
        "promptDigestsAfter": prompt_after,
        "systemChecks": checks,
        "leakageScan": {
            "status": "PASS" if not leakage else "FAIL",
            "matchingPathCount": len(leakage),
        },
        "formal105Status": "NOT_RUN",
    }
    prompt_audit._write_json(output_root / "final-summary.json", summary)
    return summary


def main() -> int:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-root",
        type=Path,
        default=REPOSITORY_ROOT / f"f105r/v4-nonprompt-residual-repair-{stamp}",
    )
    parser.add_argument(
        "--qwen-acceptance-dir",
        type=Path,
        default=formal.QWEN_ACCEPTANCE_DIR,
    )
    args = parser.parse_args()
    summary = asyncio.run(
        _run(args.output_root.resolve(), args.qwen_acceptance_dir.resolve())
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
