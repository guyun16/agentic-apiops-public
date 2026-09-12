"""Freeze Stage21 v3 and replay only a bounded cohort of v2 residual tasks."""

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

from app.benchmark import AuthProfileResolver, RealModelStage20WorkflowAdapter
from app.benchmark.auth_profiles import load_stage21_prerequisites
from app.benchmark.outcome_v2 import (
    OutcomeV2Projection,
    V2OutcomeStatus,
    load_outcome_policy,
    project_outcome_v2,
)
from app.benchmark.provider_integrity import verify_provider_integrity
from app.benchmark.report_runtime_recipes import (
    is_report_runtime_recipe_task,
    resolve_report_runtime_recipe,
)
from app.benchmark.runner import BenchmarkRun, BenchmarkTaskStatus, JavaExecutionStatus
from app.benchmark.stage21_initial_report_resources import (
    is_stage21_initial_report_task,
    resolve_stage21_initial_report_reference,
)
from app.benchmark.stage21_rag_runtime_recipes import resolve_stage21_rag_runtime_recipe
from app.benchmark.stage21_runner_runtime_recipes import (
    is_stage21_runner_runtime_recipe_task,
    resolve_stage21_runner_runtime_recipe,
)
from app.clients.java_apiops import JavaApiOpsClient
from app.core.settings import AppSettings, get_settings

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
HISTORICAL_OFFICIAL_ROOT = REPOSITORY_ROOT / "f105r/official-accuracy-v2-20260904T072119Z"
HISTORICAL_REVISION = "stage21-formal105-accuracy-repair-v2"
HISTORICAL_RUN_ID = "evaluation_run:stage21-real-model-full-105-20260904T072622Z"
DEFAULT_OUTPUT_PARENT = REPOSITORY_ROOT / "f105r"
COHORT_LABEL = "residual-cohort-13"

RESIDUAL_TASKS = (
    "bench_task_golden_rag_evidence",
    "bench_task_formal_failure_report_constraint_primary",
    "bench_task_formal_failure_business_report_authority",
    "bench_task_testcase_happy_create_order_runner",
    "bench_task_formal_testcase_inventory_conflict_runner",
    "bench_task_formal_testcase_happy_create_order_contract",
    "bench_task_testcase_boundary_quantity_zero",
    "bench_task_formal_testcase_missing_json_path_expected",
    "bench_task_formal_failure_business_acceptable_alt",
    "bench_task_failure_insufficient_missing",
    "bench_task_formal_failure_insufficient_missing_headers",
    "bench_task_formal_tool_deny_no_alternate_path",
    "bench_task_e2e_diagnosis_tool_guarded",
)

COVERAGE = {
    "bench_task_golden_rag_evidence": (
        "required-tool",
        "rag-accepted-source-authority",
    ),
    "bench_task_formal_failure_report_constraint_primary": (
        "report-resolution-pagination",
        "required-tool",
        "diagnosis-ontology",
    ),
    "bench_task_formal_failure_business_report_authority": (
        "report-resolution-pagination",
        "business-outcome-authority",
    ),
    "bench_task_testcase_happy_create_order_runner": (
        "testcase-runner-bridge",
        "java-runner-authority",
    ),
    "bench_task_formal_testcase_inventory_conflict_runner": (
        "testcase-runner-bridge",
        "business-outcome-authority",
    ),
    "bench_task_formal_testcase_happy_create_order_contract": (
        "evaluator-projection",
        "testcase-grounding",
    ),
    "bench_task_testcase_boundary_quantity_zero": ("testcase-grounding",),
    "bench_task_formal_testcase_missing_json_path_expected": ("intentional-invalid-preservation",),
    "bench_task_formal_failure_business_acceptable_alt": (
        "diagnosis-ontology",
        "java-report-authority",
    ),
    "bench_task_failure_insufficient_missing": (
        "diagnosis-insufficient-evidence",
        "report-resolution-pagination",
    ),
    "bench_task_formal_failure_insufficient_missing_headers": (
        "diagnosis-insufficient-evidence",
        "report-resolution-pagination",
    ),
    "bench_task_formal_tool_deny_no_alternate_path": (
        "safety-deny",
        "cross-project",
    ),
    "bench_task_e2e_diagnosis_tool_guarded": (
        "safety-deny",
        "cross-project",
        "java-evidence",
    ),
}


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _historical_inputs() -> tuple[OutcomeV2Projection, BenchmarkRun, Path]:
    freeze_path = HISTORICAL_OFFICIAL_ROOT / "freeze-manifest.json"
    outcome_path = HISTORICAL_OFFICIAL_ROOT / "outcome-v2.json"
    run_paths = tuple((HISTORICAL_OFFICIAL_ROOT / "full-105/results").glob("run-*/run.json"))
    if len(run_paths) != 1:
        raise RuntimeError("v2 official must contain exactly one persisted run")
    freeze = json.loads(freeze_path.read_text(encoding="utf-8"))
    if freeze.get("accuracyRepairContract", {}).get("revision") != HISTORICAL_REVISION:
        raise RuntimeError("v2 official revision identity mismatch")
    run = BenchmarkRun.model_validate_json(run_paths[0].read_text(encoding="utf-8"))
    if run.evaluation_run_id != HISTORICAL_RUN_ID:
        raise RuntimeError("v2 official evaluation run identity mismatch")
    projection = OutcomeV2Projection.model_validate_json(outcome_path.read_text(encoding="utf-8"))
    if projection.v2_status_counts != {"FAIL": 30, "PASS": 42, "UNKNOWN": 33}:
        raise RuntimeError("v2 official status counts do not match the frozen baseline")
    old = {task.benchmark_task_id: task for task in projection.tasks}
    missing = sorted(set(RESIDUAL_TASKS) - set(old))
    non_residual = sorted(
        task_id for task_id in RESIDUAL_TASKS if old[task_id].v2_status is V2OutcomeStatus.PASS
    )
    if missing or non_residual:
        raise RuntimeError(
            f"residual cohort is invalid: missing={missing}, nonResidual={non_residual}"
        )
    return projection, run, run_paths[0]


async def _focused_runtime_preflight(
    settings: AppSettings,
    dataset: Any,
) -> dict[str, object]:
    tasks = {task.benchmark_task_id: task for task in dataset.tasks}
    prerequisites = load_stage21_prerequisites()
    task_checks: list[dict[str, object]] = []
    async with httpx.AsyncClient(trust_env=False) as http_client:
        health = await http_client.get(
            settings.java_apiops_base_url.rstrip("/") + "/actuator/health",
            timeout=settings.java_apiops_timeout_seconds,
        )
        target = await http_client.get(
            "http://127.0.0.1:8080/products?pageNo=1&pageSize=1",
            timeout=settings.java_apiops_timeout_seconds,
        )
        if health.status_code != 200 or target.status_code != 200:
            raise RuntimeError(
                "focused preflight requires healthy Java and Runner target boundaries"
            )
        java = JavaApiOpsClient(
            http_client,
            base_url=settings.java_apiops_base_url,
            timeout_seconds=settings.java_apiops_timeout_seconds,
        )
        resolver = AuthProfileResolver(java)
        for task_id in RESIDUAL_TASKS:
            task = tasks[task_id]
            prerequisite = prerequisites[task_id]
            project_id = RealModelStage20WorkflowAdapter._project_id(task)
            if project_id is None or project_id != prerequisite.current_project_id:
                raise RuntimeError(f"canonical project identity mismatch for {task_id}")
            session = await resolver.resolve_for_task(task_id)
            trace_id = "trace:stage21-v3-preflight:" + task_id
            await java.assert_project_readable(
                project_id=project_id,
                token=session.token,
                trace_id=trace_id,
            )
            requirements = RealModelStage20WorkflowAdapter._java_requirements(task)
            report_evidence: dict[str, object] | None = None
            metadata_evidence: dict[str, object] | None = None
            recipe_evidence: dict[str, object] | None = None

            if is_stage21_initial_report_task(task):
                reference = resolve_stage21_initial_report_reference(task)
                if reference is None:
                    raise RuntimeError(f"initial report reference is unresolved for {task_id}")
                summary = await java.find_latest_test_run(
                    project_id=project_id,
                    case_id=reference.case_id,
                    token=session.token,
                    trace_id=trace_id,
                )
                if summary is None or summary.case_id != reference.case_id:
                    raise RuntimeError(f"initial report is missing for {task_id}")
                report = await java.get_test_report(
                    project_id=project_id,
                    run_id=summary.run_id,
                    token=session.token,
                    trace_id=trace_id,
                )
                if report.project_id != project_id or report.run_id != summary.run_id:
                    raise RuntimeError(f"initial report identity mismatch for {task_id}")
                report_evidence = {
                    "caseId": reference.case_id,
                    "runId": summary.run_id,
                    "reportIdPresent": bool(report.report_id),
                    "stableExactLookup": True,
                }

            if requirements.metadata:
                api_id = RealModelStage20WorkflowAdapter._api_id(task)
                metadata = await java.get_api_metadata(
                    project_id=project_id,
                    api_id=api_id,
                    token=session.token,
                    trace_id=trace_id,
                )
                if metadata.api_id != api_id:
                    raise RuntimeError(f"metadata identity mismatch for {task_id}")
                metadata_evidence = {
                    "apiId": api_id,
                    "projectId": project_id,
                    "canonicalIdentity": True,
                }

            if is_report_runtime_recipe_task(task):
                recipe = resolve_report_runtime_recipe(task)
                recipe_evidence = {
                    "kind": "REPORT_RUNTIME",
                    "resolved": recipe is not None,
                }
            elif is_stage21_runner_runtime_recipe_task(task):
                recipe = resolve_stage21_runner_runtime_recipe(task)
                recipe_evidence = {
                    "kind": "RUNNER_RUNTIME",
                    "resolved": recipe is not None,
                }
            elif requirements.runner:
                recipe_evidence = {
                    "kind": "GENERATED_TESTCASE_RUNNER",
                    "resolved": True,
                }

            if requirements.rag:
                rag_recipe = resolve_stage21_rag_runtime_recipe(task)
                if rag_recipe is None:
                    raise RuntimeError(f"RAG runtime recipe is unresolved for {task_id}")

            task_checks.append(
                {
                    "benchmarkTaskId": task_id,
                    "authProfile": prerequisite.auth_profile.value,
                    "principalId": session.principal_id,
                    "projectId": project_id,
                    "canonicalProjectIdentity": True,
                    "javaRequired": requirements.required,
                    "report": report_evidence,
                    "metadata": metadata_evidence,
                    "runnerRecipe": recipe_evidence,
                    "ragRecipeResolved": not requirements.rag
                    or resolve_stage21_rag_runtime_recipe(task) is not None,
                    "ready": True,
                }
            )
    return {
        "schemaVersion": "stage21-v3-residual-focused-preflight/v1",
        "status": "PASS",
        "taskCount": len(task_checks),
        "modelCallCount": 0,
        "runnerSubmitCount": 0,
        "toolGatewayCallCount": 0,
        "javaHealth": "PASS",
        "runnerTargetHealth": "PASS",
        "nonReadyTaskIds": [],
        "tasks": task_checks,
    }


def _task_failure_classification(
    result: Any,
    projected: Any,
    provider_status: str,
) -> tuple[str, str]:
    if projected.v2_status is V2OutcomeStatus.PASS:
        return "RESOLVED", "all frozen Outcome V2 requirements passed"
    if provider_status in {"PROVIDER_UNPROVEN", "PROVIDER_MISMATCH", "ACTUAL_FALLBACK"}:
        return "WORKFLOW", f"provider integrity was {provider_status}"
    if result.status is not BenchmarkTaskStatus.SUCCESS:
        if result.java_execution_status in {
            JavaExecutionStatus.EXECUTION_FAILED,
            JavaExecutionStatus.REQUIRED_BUT_UNAVAILABLE,
        } or (result.failure_code or "").startswith("JAVA_"):
            return "JAVA_RUNTIME", "the benchmark runtime did not complete its Java boundary"
        if result.failure_category == "CONTRACT_FAILURE":
            return "BENCHMARK_CONTRACT", "the benchmark runtime reported a contract failure"
        if result.failure_code == "MODEL_OUTPUT_FAILURE":
            return "MODEL_REASONING", "the terminal model output failed its required contract"
        return "WORKFLOW", "the benchmark task runtime did not complete successfully"

    normalized = (
        result.formal_evidence.normalized_evaluation_facts
        if result.formal_evidence is not None
        else {}
    )
    structured = normalized.get("structured_facts", [])
    fact_by_name = {
        item["name"]: item.get("value")
        for item in structured
        if isinstance(item, dict) and isinstance(item.get("name"), str)
    }
    evidence_metric = next(
        (
            metric
            for metric in (result.evaluation_result.metrics if result.evaluation_result else ())
            if metric.metric.value == "evidence_hit"
        ),
        None,
    )
    if (
        result.benchmark_task_id == "bench_task_formal_failure_business_acceptable_alt"
        and result.model_call_count == 0
        and fact_by_name.get("business_outcome") == "ORDER_BUSINESS_CONFLICT"
    ):
        return (
            "WORKFLOW",
            "the Java report proved HTTP 409 ORDER_BUSINESS_CONFLICT, but the workflow treated "
            "Runner SUCCESS as failureType NONE and skipped the frozen required RAG call/model",
        )
    if result.benchmark_task_id in {
        "bench_task_testcase_happy_create_order_runner",
        "bench_task_formal_testcase_inventory_conflict_runner",
    } and fact_by_name.get("java_runner_status") == "EXECUTION_FAILED":
        return (
            "WORKFLOW",
            "the accepted generated testcase used the supplied http://localhost metadata target; "
            "Java then authoritatively reported CONNECT_ERROR instead of the expected "
            "business result",
        )
    if evidence_metric is not None and "accepted_source_authority=not-used" in (
        evidence_metric.details or ""
    ):
        return (
            "EVALUATOR_AUTHORITY",
            "Java returned current Stage21 RAG source identities, but the evaluation-owned "
            "accepted-source authority has no entry for this frozen GroundTruth identity",
        )
    if any(
        requirement.requirement.value == "REQUIRED" and not requirement.invoked
        for requirement in projected.tool_requirements
    ):
        return "TOOL", "a frozen required tool was not invoked"
    if projected.outcome_authority_gap:
        return "AUTHORITY", "Outcome V2 still lacks a required authoritative fact"
    if projected.v2_status is V2OutcomeStatus.UNKNOWN:
        return "EVALUATOR", "the evaluator did not resolve all required observations"
    return (
        "MODEL_REASONING",
        "authoritative inputs were available but the semantic result was wrong",
    )


def _comparison(
    old: OutcomeV2Projection,
    new: OutcomeV2Projection,
    run: BenchmarkRun,
    provider: dict[str, Any],
) -> dict[str, object]:
    old_by_id = {task.benchmark_task_id: task for task in old.tasks}
    new_by_id = {task.benchmark_task_id: task for task in new.tasks}
    result_by_id = {result.benchmark_task_id: result for result in run.results}
    provider_by_task: dict[str, str] = {}
    for status, key in (
        ("PROVIDER_PROVEN", "provenTaskIds"),
        ("NO_MODEL_CALL", "noModelCallTaskIds"),
        ("PROVIDER_UNPROVEN", "unprovenTaskIds"),
        ("PROVIDER_MISMATCH", "mismatchTaskIds"),
        ("ACTUAL_FALLBACK", "actualFallbackTaskIds"),
    ):
        for task_id in provider.get(key, []):
            provider_by_task[task_id] = status

    transitions: Counter[str] = Counter()
    classifications: Counter[str] = Counter()
    tasks: list[dict[str, object]] = []
    for task_id in RESIDUAL_TASKS:
        previous = old_by_id[task_id]
        current = new_by_id[task_id]
        result = result_by_id[task_id]
        transition = f"{previous.v2_status.value}->{current.v2_status.value}"
        classification, classification_reason = _task_failure_classification(
            result,
            current,
            provider_by_task.get(task_id, "PROVIDER_UNPROVEN"),
        )
        transitions[transition] += 1
        if classification != "RESOLVED":
            classifications[classification] += 1
        tasks.append(
            {
                "benchmarkTaskId": task_id,
                "taskType": result.task_type.value,
                "coverage": list(COVERAGE[task_id]),
                "oldStatus": previous.v2_status.value,
                "newStatus": current.v2_status.value,
                "runtimeStatus": result.status.value,
                "javaExecutionStatus": result.java_execution_status.value,
                "providerIntegrity": provider_by_task.get(task_id, "UNCLASSIFIED"),
                "failureClassification": classification,
                "failureClassificationReason": classification_reason,
                "failureCategory": result.failure_category,
                "failureCode": result.failure_code,
                "outcomeAuthority": current.outcome_authority.value,
                "outcomeAuthorityGap": current.outcome_authority_gap,
                "outcomeMetrics": [
                    metric.model_dump(mode="json") for metric in current.outcome_metrics
                ],
                "toolRequirements": [
                    requirement.model_dump(mode="json") for requirement in current.tool_requirements
                ],
            }
        )
    return {
        "schemaVersion": "stage21-v3-residual-root-cause-audit/v1",
        "taskCount": len(tasks),
        "transitionCounts": dict(sorted(transitions.items())),
        "failureClassificationCounts": dict(sorted(classifications.items())),
        "tasks": tasks,
    }


def _audit_existing(output_root: Path) -> dict[str, object]:
    """Reclassify a completed cohort without changing any live-run evidence."""

    old_projection, _, _ = _historical_inputs()
    run_paths = tuple((output_root / COHORT_LABEL / "results").glob("run-*/run.json"))
    if len(run_paths) != 1:
        raise RuntimeError("existing residual cohort must contain exactly one persisted run")
    run = BenchmarkRun.model_validate_json(run_paths[0].read_text(encoding="utf-8"))
    projection = OutcomeV2Projection.model_validate_json(
        (output_root / "outcome-v2-live.json").read_text(encoding="utf-8")
    )
    provider = json.loads((output_root / "provider-integrity.json").read_text(encoding="utf-8"))
    audit = _comparison(old_projection, projection, run, provider)
    classifications = audit["failureClassificationCounts"]
    systemic = any(
        classifications.get(name, 0) > 0
        for name in ("WORKFLOW", "EVALUATOR_AUTHORITY", "BENCHMARK_CONTRACT")
    )
    audit = {
        **audit,
        "verdict": "SYSTEMIC_ISSUE" if systemic else "PASS",
        "readyForFull105": not systemic,
        "full105Status": "NOT_RUN",
        "systemicIssues": [
            {
                "category": category,
                "taskCount": classifications.get(category, 0),
            }
            for category in (
                "EVALUATOR_AUTHORITY",
                "WORKFLOW",
                "BENCHMARK_CONTRACT",
            )
            if classifications.get(category, 0) > 0
        ],
    }
    _write_json(output_root / "residual-root-cause-audit.json", audit)
    return audit


async def _run(
    output_root: Path,
    *,
    acceptance_dir: Path,
) -> dict[str, object]:
    if output_root.exists():
        raise RuntimeError(f"residual live output already exists: {output_root}")
    old_projection, _, old_run_path = _historical_inputs()
    historical_digests = {
        "freeze": formal._sha256_file(HISTORICAL_OFFICIAL_ROOT / "freeze-manifest.json"),
        "outcome": formal._sha256_file(HISTORICAL_OFFICIAL_ROOT / "outcome-v2.json"),
        "run": formal._sha256_file(old_run_path),
    }
    settings = get_settings()
    if settings.qwen_model != formal.EXPECTED_QWEN_MODEL:
        raise RuntimeError("residual live run requires the frozen qwen3.8-max identity")
    dataset = formal.load_dataset(formal.MANIFEST_PATH)
    policy = load_outcome_policy(formal.POLICY_PATH, dataset=dataset)
    qwen_gate = formal._qwen_provider_gate(settings, acceptance_dir)
    environment = formal._environment_readiness(settings, "qwen")
    if environment.get("ready") is not True:
        missing = [name for name, ready in environment["required"].items() if not ready]
        raise RuntimeError("residual live environment is incomplete: " + ", ".join(missing))
    preflight = await _focused_runtime_preflight(settings, dataset)
    if preflight.get("status") != "PASS":
        raise RuntimeError("focused residual runtime preflight failed closed")

    output_root.mkdir(parents=True)
    frozen_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    revision = formal._freeze_manifest(
        settings,
        dataset,
        policy,
        provider="qwen",
        qwen_gate=qwen_gate,
        environment_readiness=environment,
        runtime_preflight=preflight,
        frozen_at=frozen_at,
    )
    revision = {
        **revision,
        "freezeStatus": "FROZEN_BEFORE_RESIDUAL_LIVE_COHORT",
        "formal105Status": "NOT_RUN",
        "selectedTaskIds": list(RESIDUAL_TASKS),
        "sourceOfficial": {
            "revision": HISTORICAL_REVISION,
            "evaluationRunId": HISTORICAL_RUN_ID,
            "root": str(HISTORICAL_OFFICIAL_ROOT),
            "digests": historical_digests,
        },
        "historicalOfficialArtifactsPreserved": True,
    }
    _write_json(output_root / "focused-runtime-preflight.json", preflight)
    _write_json(output_root / "benchmark-revision.json", revision)

    baseline.DEFAULT_OUTPUT_ROOT = output_root
    evaluation_run_id = "evaluation_run:stage21-v3-residual-live-" + datetime.now(UTC).strftime(
        "%Y%m%dT%H%M%SZ"
    )
    async with httpx.AsyncClient(trust_env=False) as http_client:
        runner = baseline._build_runner(settings, http_client, provider="qwen")
        result = await baseline._run_baseline(
            runner,
            settings,
            label=COHORT_LABEL,
            task_ids=RESIDUAL_TASKS,
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
    _write_json(output_root / "outcome-v2-live.json", projection.model_dump(mode="json"))
    _write_json(output_root / "residual-transition-audit.json", comparison)

    post_digests = {
        "freeze": formal._sha256_file(HISTORICAL_OFFICIAL_ROOT / "freeze-manifest.json"),
        "outcome": formal._sha256_file(HISTORICAL_OFFICIAL_ROOT / "outcome-v2.json"),
        "run": formal._sha256_file(old_run_path),
    }
    history_preserved = historical_digests == post_digests
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
    system_checks = {
        "revisionFrozenBeforeCohort": revision["freezeStatus"]
        == "FROZEN_BEFORE_RESIDUAL_LIVE_COHORT",
        "residualOnly": len(result.run.results) == len(RESIDUAL_TASKS)
        and set(result.run.selected_task_ids) == set(RESIDUAL_TASKS),
        "providerIntegrity": provider_clean,
        "evaluationFactsPersisted": all(
            item.formal_evidence is not None for item in result.run.results
        ),
        "outcomeV2Projected": projection.projected_task_count == len(RESIDUAL_TASKS),
        "historicalOfficialPreserved": history_preserved,
        "credentialLeakageAbsent": not leakage,
        "full105NotRun": len(result.run.results) != 105,
    }
    status = "PASS" if all(system_checks.values()) else "SYSTEMIC_ISSUE"
    summary = {
        "schemaVersion": "stage21-v3-residual-live-summary/v1",
        "status": status,
        "benchmarkRevision": formal.BENCHMARK_CONTRACT_REVISION,
        "evaluationRunId": result.run.evaluation_run_id,
        "provider": {"provider": "Qwen", "model": settings.qwen_model},
        "qwen38ProviderAcceptance": qwen_gate,
        "selectedTaskCount": len(RESIDUAL_TASKS),
        "selectedTaskIds": list(RESIDUAL_TASKS),
        "transitionCounts": comparison["transitionCounts"],
        "failureClassificationCounts": comparison["failureClassificationCounts"],
        "v2StatusCounts": projection.v2_status_counts,
        "residualPassRate": projection.v2_status_counts.get("PASS", 0) / len(RESIDUAL_TASKS),
        "residualOutcomeAccuracy": projection.outcome_accuracy.model_dump(mode="json"),
        "runtimeStatusCounts": dict(
            sorted(Counter(item.status.value for item in result.run.results).items())
        ),
        "javaExecutionStatusCounts": dict(
            sorted(Counter(item.java_execution_status.value for item in result.run.results).items())
        ),
        "providerIntegrity": provider,
        "systemChecks": system_checks,
        "leakageScan": {
            "status": "PASS" if not leakage else "FAIL",
            "matchingPathCount": len(leakage),
        },
        "historicalOfficialDigestsBefore": historical_digests,
        "historicalOfficialDigestsAfter": post_digests,
        "full105Status": "NOT_RUN",
    }
    _write_json(output_root / "residual-live-summary.json", summary)
    return summary


def main() -> int:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-root",
        type=Path,
        default=DEFAULT_OUTPUT_PARENT / f"v3-residual-live-{stamp}",
    )
    parser.add_argument(
        "--qwen-acceptance-dir",
        type=Path,
        default=formal.QWEN_ACCEPTANCE_DIR,
    )
    parser.add_argument(
        "--audit-existing",
        action="store_true",
        help="classify an already completed cohort without making live calls",
    )
    args = parser.parse_args()
    if args.audit_existing:
        audit = _audit_existing(args.output_root.resolve())
        print(json.dumps(audit, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    summary = asyncio.run(
        _run(
            args.output_root.resolve(),
            acceptance_dir=args.qwen_acceptance_dir.resolve(),
        )
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if summary["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
