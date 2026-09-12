"""Audit v4 residuals and replay only proven prompt/model failures."""

# ruff: noqa: E501 - evidence sentences remain intact in the persisted audit.

from __future__ import annotations

import argparse
import asyncio
import hashlib
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
OFFICIAL_ROOT = REPOSITORY_ROOT / "f105r/v4o-20260904T145500Z"
OFFICIAL_REVISION = "stage21-formal105-accuracy-repair-v4"
OFFICIAL_RUN_ID = "evaluation_run:stage21-real-model-full-105-20260904T145654Z"
COHORT_LABEL = "prompt-model-residual"

TARGETED_TASKS = (
    "bench_task_e2e_diagnosis_tool_guarded",
    "bench_task_formal_e2e_generation_diagnosis_guarded",
)

_CLASSIFICATIONS: dict[str, tuple[str, str, tuple[str, ...]]] = {
    "bench_task_golden_e2e_apiops": (
        "RUNTIME",
        "Java authoritatively returned a successful create-order run while the frozen task expects a database-constraint failure.",
        ("BENCHMARK CONTRACT",),
    ),
    "bench_task_golden_failure_diagnosis": (
        "TOOL / RAG",
        "The required query ran, but Project 42 returned inventory evidence instead of the frozen orders unique-index identity; the model followed the returned evidence.",
        ("BENCHMARK CONTRACT",),
    ),
    "bench_task_testcase_boundary_inventory_limit": (
        "WORKFLOW",
        "GenerationContext selected quantity.maximum with HTTP 200 instead of the requested inventory-availability business boundary and HTTP 409.",
        (),
    ),
    "bench_task_testcase_business_inventory_python": (
        "EVALUATOR / AUTHORITY",
        "The accepted candidate asserts the documented HTTP 409, but the required business_error fact is not projected by current authority.",
        (),
    ),
    "bench_task_testcase_business_inventory_runner": (
        "RUNTIME",
        "The generated business-error testcase reached Java, but the target produced CONNECT_ERROR instead of the expected business response.",
        (),
    ),
    "bench_task_testcase_boundary_list_products_page_size": (
        "WORKFLOW",
        "Java metadata resolution supplied createOrder to GenerationContext for a listProducts task.",
        (),
    ),
    "bench_task_failure_http_500": (
        "BENCHMARK CONTRACT",
        "GroundTruth expects a RAG call, but the frozen execution prerequisite declares only READ_REPORT; planning therefore completed without a model call.",
        ("WORKFLOW",),
    ),
    "bench_task_failure_business_inventory": (
        "BENCHMARK CONTRACT",
        "GroundTruth expects a RAG call, but the frozen execution prerequisite declares only READ_REPORT; planning therefore completed without a model call.",
        ("WORKFLOW",),
    ),
    "bench_task_failure_evidence_root_report": (
        "BENCHMARK CONTRACT",
        "GroundTruth expects a RAG call, but the frozen execution prerequisite declares only READ_REPORT; planning therefore completed without a model call.",
        ("WORKFLOW",),
    ),
    "bench_task_rag_multi_hit": (
        "TOOL / RAG",
        "The exact query returned inventory runbooks, so only the current report matched the two required evidence identities.",
        (),
    ),
    "bench_task_rag_zero_hit": (
        "TOOL / RAG",
        "The exact zero-hit query returned two above-threshold corpus documents; this is retrieval behavior, not a model decision.",
        (),
    ),
    "bench_task_rag_irrelevant_distractor": (
        "TOOL / RAG",
        "The exact query returned current corpus identities that the frozen evaluator did not accept as the required evidence identity.",
        ("EVALUATOR / AUTHORITY",),
    ),
    "bench_task_e2e_generation_runner_success": (
        "EVALUATOR / AUTHORITY",
        "Java Runner success and contract acceptance are present, but business_outcome remains outside the authoritative projection.",
        (),
    ),
    "bench_task_e2e_generation_business_failure": (
        "EVALUATOR / AUTHORITY",
        "Java observed the expected HTTP 409, but the required business_outcome is not authoritatively projected.",
        (),
    ),
    "bench_task_e2e_diagnosis_tool_guarded": (
        "STRUCTURED OUTPUT",
        "After Java denied the cross-project lookup, Qwen returned sufficientEvidence=false with empty limitations and recommendedChecks, violating the cross-field contract.",
        ("PROMPT / MODEL REASONING",),
    ),
    "bench_task_formal_e2e_generation_diagnosis_guarded": (
        "STRUCTURED OUTPUT",
        "After Java denied the cross-project lookup, Qwen returned empty limitations and recommendedChecks; the observed HTTP 409 is also inconsistent with the frozen expected successful run.",
        ("PROMPT / MODEL REASONING", "RUNTIME"),
    ),
    "bench_task_formal_failure_http500_diagnosis_boundary": (
        "BENCHMARK CONTRACT",
        "GroundTruth expects a RAG call, but the execution prerequisite declares only READ_REPORT and no model call occurred.",
        ("WORKFLOW",),
    ),
    "bench_task_formal_failure_http500_payload": (
        "BENCHMARK CONTRACT",
        "GroundTruth expects a RAG call, but the execution prerequisite declares only READ_REPORT and no model call occurred.",
        ("WORKFLOW",),
    ),
    "bench_task_formal_failure_http500_transport_distinction": (
        "BENCHMARK CONTRACT",
        "GroundTruth expects a RAG call, but the execution prerequisite declares only READ_REPORT and no model call occurred.",
        ("WORKFLOW",),
    ),
    "bench_task_formal_failure_inventory_business": (
        "BENCHMARK CONTRACT",
        "GroundTruth expects a RAG call, but the execution prerequisite declares only READ_REPORT and no model call occurred.",
        ("WORKFLOW",),
    ),
    "bench_task_formal_failure_inventory_duplicate_key": (
        "BENCHMARK CONTRACT",
        "GroundTruth expects report plus RAG evidence, but the execution prerequisite declares only READ_REPORT and no model call occurred.",
        ("WORKFLOW",),
    ),
    "bench_task_formal_failure_multi_evidence_report": (
        "EVALUATOR / AUTHORITY",
        "Qwen produced the expected database-constraint diagnosis from report and retrieved evidence, but accepted-source evidence identity resolved only one of two frozen IDs.",
        (),
    ),
    "bench_task_formal_failure_report_constraint_alternative": (
        "BENCHMARK CONTRACT",
        "GroundTruth expects report plus RAG evidence, but the execution prerequisite declares only READ_REPORT and no model call occurred.",
        ("WORKFLOW",),
    ),
    "bench_task_formal_failure_transport_dns": (
        "WORKFLOW",
        "Tool planning resolved an authoritative no-response transport report to an insufficient deterministic projection and skipped model inference.",
        (),
    ),
    "bench_task_formal_rag_near_match_exact": (
        "TOOL / RAG",
        "The exact query returned one accepted constraint identity plus a payment near-match, leaving evidence coverage incomplete.",
        (),
    ),
    "bench_task_formal_rag_zero_hit_authorized": (
        "TOOL / RAG",
        "The exact zero-hit query returned two above-threshold corpus documents; this is retrieval behavior, not a model decision.",
        (),
    ),
    "bench_task_formal_testcase_auth_missing_token_post": (
        "EVALUATOR / AUTHORITY",
        "The accepted candidate preserves the operation, missing credential, and 401, but expected_error_code is not projected.",
        (),
    ),
    "bench_task_formal_testcase_boundary_inventory_zero": (
        "WORKFLOW",
        "GenerationContext exposed quantity.minimum and HTTP 200 instead of the requested insufficient-stock business boundary and HTTP 409.",
        (),
    ),
    "bench_task_formal_testcase_business_inventory_expected": (
        "EVALUATOR / AUTHORITY",
        "The accepted candidate asserts HTTP 409, but business_error and success_expected are not projected by current authority.",
        (),
    ),
    "bench_task_formal_testcase_create_order_quantity_one": (
        "BENCHMARK CONTRACT",
        "The task input selects HAPPY_PATH and Qwen produced quantity=1, while GroundTruth requires task_strategy=BOUNDARY.",
        (),
    ),
    "bench_task_formal_testcase_get_orders_limit": (
        "WORKFLOW",
        "Java metadata resolution supplied createOrder to GenerationContext for the requested GET /orders operation.",
        (),
    ),
    "bench_task_formal_testcase_happy_get_orders_metadata": (
        "WORKFLOW",
        "Java metadata resolution supplied createOrder to GenerationContext for the requested GET /orders operation.",
        (),
    ),
    "bench_task_formal_testcase_inventory_conflict_metadata": (
        "EVALUATOR / AUTHORITY",
        "The accepted candidate asserts the documented HTTP 409, but business_error and failure_boundary are not projected.",
        (),
    ),
    "bench_task_formal_testcase_list_products_page_size_one": (
        "WORKFLOW",
        "Java metadata resolution supplied createOrder to GenerationContext for a listProducts task.",
        (),
    ),
    "bench_task_formal_testcase_unknown_assertion_type": (
        "EVALUATOR / AUTHORITY",
        "Qwen correctly preserved BODY_CONTAINS as the declared intentional invalidity, but Outcome authority remains unresolved for the rejected candidate.",
        ("BENCHMARK CONTRACT",),
    ),
}


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _tree_digest(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        digest.update(path.relative_to(root).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


def _official_inputs() -> tuple[OutcomeV2Projection, BenchmarkRun, Path]:
    freeze = json.loads((OFFICIAL_ROOT / "freeze-manifest.json").read_text(encoding="utf-8"))
    if freeze.get("accuracyRepairContract", {}).get("revision") != OFFICIAL_REVISION:
        raise RuntimeError("v4 official revision identity mismatch")
    run_paths = tuple((OFFICIAL_ROOT / "full-105/results").glob("run-*/run.json"))
    if len(run_paths) != 1:
        raise RuntimeError("v4 official must contain exactly one persisted run")
    run = BenchmarkRun.model_validate_json(run_paths[0].read_text(encoding="utf-8"))
    if run.evaluation_run_id != OFFICIAL_RUN_ID:
        raise RuntimeError("v4 official evaluation run identity mismatch")
    projection = OutcomeV2Projection.model_validate_json(
        (OFFICIAL_ROOT / "outcome-v2.json").read_text(encoding="utf-8")
    )
    if projection.v2_status_counts != {"FAIL": 25, "PASS": 70, "UNKNOWN": 10}:
        raise RuntimeError("v4 official status counts do not match the declared baseline")
    return projection, run, run_paths[0]


def _audit_residuals(
    old_projection: OutcomeV2Projection,
    old_run: BenchmarkRun,
) -> dict[str, object]:
    old_by_id = {item.benchmark_task_id: item for item in old_projection.tasks}
    result_by_id = {item.benchmark_task_id: item for item in old_run.results}
    residual_ids = {
        task_id
        for task_id, item in old_by_id.items()
        if item.v2_status is not V2OutcomeStatus.PASS
    }
    if residual_ids != set(_CLASSIFICATIONS):
        raise RuntimeError(
            "residual classification coverage mismatch: "
            f"missing={sorted(residual_ids - set(_CLASSIFICATIONS))}, "
            f"extra={sorted(set(_CLASSIFICATIONS) - residual_ids)}"
        )
    tasks = []
    counts: Counter[str] = Counter()
    for task_id in sorted(residual_ids):
        primary, reason, secondary = _CLASSIFICATIONS[task_id]
        projected = old_by_id[task_id]
        result = result_by_id[task_id]
        counts[primary] += 1
        tasks.append(
            {
                "benchmarkTaskId": task_id,
                "taskType": result.task_type.value,
                "oldStatus": projected.v2_status.value,
                "runtimeStatus": result.status.value,
                "modelCallCount": result.model_call_count,
                "failureCode": result.failure_code,
                "modelOutputFailure": result.failure_code == "MODEL_OUTPUT_FAILURE",
                "primaryRootCause": primary,
                "secondaryRootCauses": list(secondary),
                "reason": reason,
                "promptRepairEligible": task_id in TARGETED_TASKS,
            }
        )
    return {
        "schemaVersion": "stage21-v4-final-residual-root-cause-audit/v1",
        "benchmarkRevision": OFFICIAL_REVISION,
        "sourceEvaluationRunId": OFFICIAL_RUN_ID,
        "sourceOfficialRoot": str(OFFICIAL_ROOT),
        "failCount": 25,
        "unknownCount": 10,
        "modelOutputFailureCount": sum(
            bool(item["modelOutputFailure"]) for item in tasks
        ),
        "uniqueResidualTaskCount": len(tasks),
        "promptModelFailureTaskIds": list(TARGETED_TASKS),
        "nonPromptFailureTaskIds": sorted(residual_ids - set(TARGETED_TASKS)),
        "primaryRootCauseCounts": dict(sorted(counts.items())),
        "tasks": tasks,
    }


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
    tasks = []
    for task_id in TARGETED_TASKS:
        previous = old_by_id[task_id]
        current = new_by_id[task_id]
        result = result_by_id[task_id]
        transition = f"{previous.v2_status.value}->{current.v2_status.value}"
        transitions[transition] += 1
        repair_calls = sum(
            record.get("record_type") == "model_call"
            and record.get("event") == "TERMINAL"
            and record.get("prompt", {}).get("name") == "diagnosis_semantic_repair"
            for record in (
                result.formal_evidence.trace_evidence if result.formal_evidence else ()
            )
            if isinstance(record, dict)
        )
        tasks.append(
            {
                "benchmarkTaskId": task_id,
                "oldStatus": previous.v2_status.value,
                "newStatus": current.v2_status.value,
                "transition": transition,
                "runtimeStatus": result.status.value,
                "failureCategory": result.failure_category,
                "failureCode": result.failure_code,
                "modelCallCount": result.model_call_count,
                "semanticRepairCallCount": repair_calls,
                "outcomeAuthority": current.outcome_authority.value,
                "outcomeAuthorityGap": current.outcome_authority_gap,
                "outcomeMetrics": [
                    metric.model_dump(mode="json") for metric in current.outcome_metrics
                ],
            }
        )
    status_counts = new.v2_status_counts
    passed = status_counts.get("PASS", 0)
    failed = status_counts.get("FAIL", 0)
    unknown = status_counts.get("UNKNOWN", 0)
    denominator = passed + failed
    return {
        "schemaVersion": "stage21-v4-prompt-repair-targeted-comparison/v1",
        "targetedTaskCount": len(TARGETED_TASKS),
        "transitionCounts": dict(sorted(transitions.items())),
        "oldFailToPass": transitions.get("FAIL->PASS", 0),
        "oldUnknownToPass": transitions.get("UNKNOWN->PASS", 0),
        "stillFail": failed,
        "stillUnknown": unknown,
        "targetedPassRate": passed / len(TARGETED_TASKS),
        "targetedOutcomeAccuracy": passed / denominator if denominator else None,
        "estimatedNewPassGain": transitions.get("FAIL->PASS", 0)
        + transitions.get("UNKNOWN->PASS", 0),
        "providerIntegrity": provider,
        "tasks": tasks,
    }


async def _run(output_root: Path, acceptance_dir: Path) -> dict[str, object]:
    if output_root.exists():
        raise RuntimeError(f"targeted output already exists: {output_root}")
    old_projection, old_run, old_run_path = _official_inputs()
    historical_before = {
        "tree": _tree_digest(OFFICIAL_ROOT),
        "freeze": formal._sha256_file(OFFICIAL_ROOT / "freeze-manifest.json"),
        "outcome": formal._sha256_file(OFFICIAL_ROOT / "outcome-v2.json"),
        "run": formal._sha256_file(old_run_path),
    }
    audit = _audit_residuals(old_projection, old_run)

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
    _write_json(output_root / "residual-root-cause-audit.json", audit)
    _write_json(output_root / "focused-runtime-preflight.json", preflight)
    _write_json(
        output_root / "repair-manifest.json",
        {
            "schemaVersion": "stage21-v4-final-residual-prompt-repair/v1",
            "benchmarkRevision": OFFICIAL_REVISION,
            "formal105Status": "NOT_RUN",
            "sourceOfficial": {
                "root": str(OFFICIAL_ROOT),
                "evaluationRunId": OFFICIAL_RUN_ID,
                "digests": historical_before,
            },
            "provider": {"provider": "Qwen", "model": settings.qwen_model},
            "providerAcceptance": qwen_gate,
            "targetedTaskIds": list(TARGETED_TASKS),
            "promptRepair": {
                "diagnosisPrompt": formal._sha256_file(
                    REPOSITORY_ROOT
                    / "python-apiops-agentlab/app/agents/prompts/diagnosis_v1.txt"
                ),
                "diagnosisSemanticRepairPrompt": formal._sha256_file(
                    REPOSITORY_ROOT
                    / "python-apiops-agentlab/app/agents/prompts/diagnosis_semantic_repair_v1.txt"
                ),
                "diagnosisAdapter": formal._sha256_file(
                    REPOSITORY_ROOT / "python-apiops-agentlab/app/agents/diagnosis.py"
                ),
                "diagnosisWorkflow": formal._sha256_file(
                    REPOSITORY_ROOT
                    / "python-apiops-agentlab/app/workflows/diagnosis_workflow.py"
                ),
                "testcasePromptChangedForThisRepair": False,
            },
            "createdAt": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        },
    )

    baseline.DEFAULT_OUTPUT_ROOT = output_root
    evaluation_run_id = (
        "evaluation_run:stage21-v4-prompt-repair-targeted-"
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
    _write_json(output_root / "provider-integrity.json", provider)
    _write_json(output_root / "outcome-v2-targeted.json", projection.model_dump(mode="json"))
    _write_json(output_root / "targeted-comparison.json", comparison)

    historical_after = {
        "tree": _tree_digest(OFFICIAL_ROOT),
        "freeze": formal._sha256_file(OFFICIAL_ROOT / "freeze-manifest.json"),
        "outcome": formal._sha256_file(OFFICIAL_ROOT / "outcome-v2.json"),
        "run": formal._sha256_file(old_run_path),
    }
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
    prompt_failures_remaining = [
        task["benchmarkTaskId"]
        for task in comparison["tasks"]
        if task["failureCode"] == "MODEL_OUTPUT_FAILURE"
    ]
    checks = {
        "targetedOnly": len(result.run.results) == len(TARGETED_TASKS)
        and set(result.run.selected_task_ids) == set(TARGETED_TASKS),
        "full105NotRun": len(result.run.results) != 105,
        "providerIntegrity": provider_clean,
        "historicalOfficialPreserved": historical_before == historical_after,
        "credentialLeakageAbsent": not leakage,
        "promptModelFailuresClosed": not prompt_failures_remaining,
    }
    summary = {
        "schemaVersion": "stage21-v4-final-residual-prompt-repair-summary/v1",
        "status": "PASS" if all(checks.values()) else "FAIL",
        "benchmarkRevision": OFFICIAL_REVISION,
        "evaluationRunId": result.run.evaluation_run_id,
        "officialRoot": str(OFFICIAL_ROOT),
        "outputRoot": str(output_root),
        "provider": {"provider": "Qwen", "model": settings.qwen_model},
        "targetedTaskIds": list(TARGETED_TASKS),
        "runtimeStatusCounts": dict(
            sorted(Counter(item.status.value for item in result.run.results).items())
        ),
        "comparison": comparison,
        "promptModelFailuresRemaining": prompt_failures_remaining,
        "remainingGenuineModelFailures": len(prompt_failures_remaining),
        "historicalOfficialDigestsBefore": historical_before,
        "historicalOfficialDigestsAfter": historical_after,
        "systemChecks": checks,
        "leakageScan": {
            "status": "PASS" if not leakage else "FAIL",
            "matchingPathCount": len(leakage),
        },
        "formal105Status": "NOT_RUN",
    }
    _write_json(output_root / "final-summary.json", summary)
    return summary


def main() -> int:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-root",
        type=Path,
        default=REPOSITORY_ROOT / f"f105r/v4-final-residual-prompt-repair-{stamp}",
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
