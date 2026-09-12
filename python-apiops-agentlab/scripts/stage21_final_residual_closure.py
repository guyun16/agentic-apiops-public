"""One fail-closed targeted replay of the remaining Stage21 correctness defects."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from collections import Counter
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import httpx
import stage21_final_v2_formal105 as formal
import stage21_real_model_baseline as baseline
import stage21_v3_residual_live as residual_pipeline
import stage21_v4_final_residual_prompt_repair as prompt_audit
import stage21_v4_nonprompt_residual_repair as nonprompt

from app.benchmark import load_dataset
from app.benchmark.baseline import persist_baseline_artifacts, plan_baseline_artifact_paths
from app.benchmark.outcome_v2 import (
    OutcomeV2Projection,
    load_outcome_policy,
    project_outcome_v2,
)
from app.benchmark.provider_integrity import verify_provider_integrity
from app.benchmark.runner import (
    BenchmarkRun,
    BenchmarkTaskResult,
    JsonBenchmarkResultStore,
    preflight_artifact_paths,
)
from app.core.settings import get_settings

REPOSITORY_ROOT = nonprompt.REPOSITORY_ROOT
NONPROMPT_ROOT = REPOSITORY_ROOT / "f105r/v4-nonprompt-residual-repair-20260904T172855Z"
PROMPT_ROOT = REPOSITORY_ROOT / "f105r/v4-final-residual-prompt-repair-20260904T161316Z"
CANDIDATE_REVISION = "stage21-final-residual-closure-v1"
CONFIRMATION_REVISION = "stage21-final-residual-closure-v2"
COHORT_LABEL = "final-residual"
EXPECTED_RESIDUAL_COUNT = 15
EXPECTED_COHORT_COUNT = 18
REGRESSION_CONTROLS = (
    "bench_task_testcase_happy_create_order_runner",
    "bench_task_testcase_business_inventory_runner",
    "bench_task_formal_testcase_inventory_conflict_runner",
)
ZERO_HIT_TASKS = (
    "bench_task_formal_rag_zero_hit_authorized",
    "bench_task_rag_zero_hit",
)


class ClosureFailure(RuntimeError):
    """A bounded failure code safe to persist without exception payloads."""


def _load_projection(path: Path) -> OutcomeV2Projection:
    return OutcomeV2Projection.model_validate_json(path.read_text(encoding="utf-8"))


def _statuses(projection: OutcomeV2Projection) -> dict[str, str]:
    statuses = {row.benchmark_task_id: row.v2_status.value for row in projection.tasks}
    if len(statuses) != len(projection.tasks):
        raise ClosureFailure("DUPLICATE_PROJECTION_TASK")
    return statuses


def _residual_cohort(previous: OutcomeV2Projection) -> tuple[str, ...]:
    statuses = _statuses(previous)
    if len(statuses) != 33 or Counter(statuses.values()) != Counter(
        {"PASS": 18, "FAIL": 7, "UNKNOWN": 8}
    ):
        raise ClosureFailure("PREVIOUS_NONPROMPT_BASELINE_DRIFT")
    selected = tuple(sorted(task_id for task_id, status in statuses.items() if status != "PASS"))
    if len(selected) != EXPECTED_RESIDUAL_COUNT:
        raise ClosureFailure("RESIDUAL_COHORT_DRIFT")
    return selected


def _overlay_statuses(projections: Sequence[OutcomeV2Projection]) -> dict[str, str]:
    merged = _statuses(projections[0])
    if len(merged) != 105:
        raise ClosureFailure("OFFICIAL_BASELINE_NOT_105")
    for projection in projections[1:]:
        updates = _statuses(projection)
        if not set(updates) <= set(merged):
            raise ClosureFailure("ESTIMATE_UNRECOGNIZED_TASK")
        merged.update(updates)
    return merged


def _selected_cohort(
    previous: OutcomeV2Projection, last_known: dict[str, str]
) -> tuple[str, ...]:
    residual = _residual_cohort(previous)
    if any(last_known.get(task_id) != "PASS" for task_id in REGRESSION_CONTROLS):
        raise ClosureFailure("REGRESSION_CONTROL_BASELINE_DRIFT")
    selected = tuple(sorted((*residual, *REGRESSION_CONTROLS)))
    if len(selected) != EXPECTED_COHORT_COUNT or len(set(selected)) != len(selected):
        raise ClosureFailure("RESIDUAL_AND_CONTROL_COHORT_DRIFT")
    return selected


def _estimate(projections: Sequence[OutcomeV2Projection]) -> dict[str, object]:
    """Overlay by identity chronologically; never add aggregate gains twice."""
    merged = _overlay_statuses(projections)
    counts = Counter(merged.values())
    denominator = counts["PASS"] + counts["FAIL"]
    return {
        "isOfficialResult": False,
        "notice": "ESTIMATE != NEW OFFICIAL RESULT",
        "basis": "task identity overlay: official v4 -> prompt replay -> nonprompt -> closure",
        "pass": counts["PASS"],
        "fail": counts["FAIL"],
        "unknown": counts["UNKNOWN"],
        "passRate": counts["PASS"] / 105,
        "outcomeAccuracy": counts["PASS"] / denominator if denominator else None,
        "assumption": "Unreplayed task outcomes remain unchanged; full105 regression unverified.",
    }


def _history_snapshot(roots: Sequence[Path]) -> dict[str, str]:
    return {
        str(path): prompt_audit._tree_digest(path) if path.is_dir() else formal._sha256_file(path)
        for path in roots
    }


def _history_roots(output_root: Path) -> tuple[Path, ...]:
    roots = tuple(sorted((REPOSITORY_ROOT / "f105r").iterdir())) + tuple(
        sorted((REPOSITORY_ROOT / "artifacts/stage21").glob("v4-final-freeze-*"))
    )
    if any(output_root == path or path in output_root.parents for path in roots):
        raise ClosureFailure("OUTPUT_OVERLAPS_HISTORY")
    return roots


def _source_snapshot() -> dict[str, str]:
    base = REPOSITORY_ROOT / "python-apiops-agentlab"
    java = REPOSITORY_ROOT / "java-apiops-platform"
    paths = [
        *sorted((base / "app").rglob("*.py")),
        *sorted((base / "app/agents/prompts").glob("*.txt")),
        *sorted((base / "tests/benchmark/fixtures").rglob("*.json")),
        *sorted((base / "scripts").glob("*.py")),
        *sorted(java.glob("*/src/**/*.java")),
        *sorted(java.glob("*/src/**/*.yml")),
        *sorted(java.glob("*/target/*.jar")),
    ]
    return {str(path.relative_to(REPOSITORY_ROOT)): formal._sha256_file(path) for path in paths}


def _provider_clean(report: dict[str, object], *, require_call: bool = False) -> bool:
    allowed = {"PROVIDER_PROVEN"} if require_call else {"PROVIDER_PROVEN", "NO_MODEL_CALL"}
    return report.get("status") in allowed and not any(
        report.get(key)
        for key in ("unprovenTaskIds", "mismatchTaskIds", "actualFallbackTaskIds")
    )


def _confirmation_has_no_model_calls(
    results: Sequence[BenchmarkTaskResult], report: dict[str, object]
) -> bool:
    return (
        report.get("status") == "NO_MODEL_CALL"
        and report.get("terminalModelCallCount") == 0
        and all(not row.model_call_count and not row.model_call_ids for row in results)
    )


def _validate_zero_hit_confirmation(
    first: OutcomeV2Projection, results: Sequence[BenchmarkTaskResult]
) -> None:
    rows = {row.benchmark_task_id: row for row in first.tasks}
    result_rows = {row.benchmark_task_id: row for row in results}
    for task_id in ZERO_HIT_TASKS:
        row = rows.get(task_id)
        result = result_rows.get(task_id)
        if row is None or result is None or row.v2_status.value != "UNKNOWN":
            raise ClosureFailure("ZERO_HIT_CONFIRMATION_BASELINE_MISMATCH")
        unavailable = [metric for metric in row.outcome_metrics if metric.status.value != "VALUE"]
        if len(unavailable) != 1 or (
            unavailable[0].status.value != "UNKNOWN"
            or unavailable[0].reason != "structured facts unavailable: evidence_leakage"
        ):
            raise ClosureFailure("ZERO_HIT_CONFIRMATION_REASON_MISMATCH")
        provider = verify_provider_integrity(
            (result,), expected_provider="Qwen", expected_model="qwen3.8-max"
        )
        if not _confirmation_has_no_model_calls((result,), provider):
            raise ClosureFailure("ZERO_HIT_CONFIRMATION_PRIOR_MODEL_CALL")


def _runtime_clean(result: BenchmarkTaskResult) -> bool:
    return (
        result.failure_category
        not in {
            "INFRASTRUCTURE_FAILURE", "TIMEOUT", "SETUP_FAILURE", "EVALUATION_FAILURE",
            "CLEANUP_FAILURE", "PROVIDER_FAILURE",
        }
        and result.status.value not in {"TIMEOUT", "ABORTED"}
        and result.setup_status.value == "SUCCESS"
        and result.cleanup_status.value == "SUCCESS"
        and result.java_execution_status.value not in {
            "REQUIRED_BUT_UNAVAILABLE", "EXECUTION_FAILED",
        }
    )


class VerifiedStore(JsonBenchmarkResultStore):
    """Persist evidence first, then stop before another task on guard failure."""

    def __init__(
        self, root: Path, verify_source: Callable[[], None], *, zero_hit_confirmation: bool = False
    ) -> None:
        super().__init__(root)
        self.verify_source = verify_source
        self.executed = 0
        self.zero_hit_confirmation = zero_hit_confirmation

    def persist_task(self, result: BenchmarkTaskResult) -> Path:
        self.executed += 1
        destination = self.task_path(result.evaluation_run_id, result.benchmark_task_id)
        if destination.exists():
            raise ClosureFailure("DUPLICATE_TASK_PERSISTENCE")
        path = super().persist_task(result)
        persisted = BenchmarkTaskResult.model_validate_json(path.read_text(encoding="utf-8"))
        if persisted != result:
            raise ClosureFailure("TASK_PERSISTENCE_MISMATCH")
        provider = verify_provider_integrity(
            (persisted,), expected_provider="Qwen", expected_model="qwen3.8-max"
        )
        if not _provider_clean(provider):
            raise ClosureFailure("PROVIDER_IDENTITY_FAILED")
        if self.zero_hit_confirmation and (
            persisted.benchmark_task_id not in ZERO_HIT_TASKS
            or not _confirmation_has_no_model_calls((persisted,), provider)
        ):
            raise ClosureFailure("ZERO_HIT_CONFIRMATION_UNEXPECTED_TASK_OR_MODEL_CALL")
        if not _runtime_clean(persisted):
            raise ClosureFailure("RUNTIME_FAILED")
        self.verify_source()
        print(f"persisted={self.executed} task={result.benchmark_task_id}", flush=True)
        return path


def _read_persisted_run(
    root: Path, run_id: str, expected_ids: tuple[str, ...]
) -> tuple[BenchmarkRun, dict[str, object]]:
    paths = tuple(root.glob("run-*/run.json"))
    if len(paths) != 1:
        raise ClosureFailure("PERSISTED_RUN_ENVELOPE_MISSING_OR_DUPLICATE")
    run = BenchmarkRun.model_validate_json(paths[0].read_text(encoding="utf-8"))
    task_paths = tuple(root.glob("run-*/task-*.json"))
    results = tuple(
        BenchmarkTaskResult.model_validate_json(path.read_text(encoding="utf-8"))
        for path in task_paths
    )
    persisted_ids = tuple(result.benchmark_task_id for result in results)
    expected = set(expected_ids)
    if (
        run.evaluation_run_id != run_id
        or len(run.selected_task_ids) != len(expected_ids)
        or set(run.selected_task_ids) != expected
        or len(persisted_ids) != len(expected_ids)
        or set(persisted_ids) != expected
        or len(set(persisted_ids)) != len(persisted_ids)
        or any(result.evaluation_run_id != run_id for result in results)
        or len(run.results) != len(results)
        or {row.benchmark_task_id: row for row in run.results}
        != {row.benchmark_task_id: row for row in results}
        or run.aborted
    ):
        raise ClosureFailure("ARTIFACT_INTEGRITY_FAILED")
    # All later metrics and provenance derive from the reread task artifacts.
    run = run.model_copy(update={"results": results})
    return run, {
        "selected": len(expected_ids), "executed": len(run.results),
        "persisted": len(results), "missing": 0, "duplicates": 0,
        "artifactIntegrity": "PASS",
        "taskArtifactDigests": {str(path): formal._sha256_file(path) for path in task_paths},
    }


def _comparison(
    old: dict[str, str], current: OutcomeV2Projection,
    *, controls: tuple[str, ...] = REGRESSION_CONTROLS,
) -> dict[str, object]:
    new = _statuses(current)
    transitions = Counter(f"{old[key]}->{value}" for key, value in new.items())
    counts = Counter(new.values())
    denominator = counts["PASS"] + counts["FAIL"]
    return {
        "oldFailToPass": transitions["FAIL->PASS"],
        "oldUnknownToPass": transitions["UNKNOWN->PASS"],
        "stillFail": counts["FAIL"], "stillUnknown": counts["UNKNOWN"],
        "targetedPass": counts["PASS"], "targetedFail": counts["FAIL"],
        "targetedUnknown": counts["UNKNOWN"],
        "targetedOutcomeAccuracy": counts["PASS"] / denominator if denominator else None,
        "regressionControls": list(controls),
        "regressionControlFailures": [
            key for key in controls if new.get(key) != "PASS"
        ],
        "transitionCounts": dict(transitions),
        "tasks": [
            {
                "benchmarkTaskId": key, "oldStatus": old[key], "newStatus": value,
                "role": "REGRESSION_CONTROL" if key in controls else "RESIDUAL",
            }
            for key, value in sorted(new.items())
        ],
    }


async def _run(
    output_root: Path, acceptance_dir: Path, zero_hit_confirmation_root: Path | None = None,
    *, replay_task_ids: tuple[str, ...] | None = None,
    replay_control_ids: tuple[str, ...] = (),
    prior_projection_paths: tuple[Path, ...] = (),
    candidate_revision: str | None = None,
) -> dict[str, object]:
    if replay_task_ids is not None and (
        zero_hit_confirmation_root is not None
        or not replay_task_ids or len(set(replay_task_ids)) != len(replay_task_ids)
        or len(replay_task_ids) >= 105 or not candidate_revision
        or not set(replay_control_ids) <= set(replay_task_ids)
        or len(set(replay_control_ids)) != len(replay_control_ids)
    ):
        raise ClosureFailure("EXPLICIT_TARGETED_SCOPE_INVALID")
    if output_root.exists():
        raise ClosureFailure("OUTPUT_ALREADY_EXISTS")
    history_roots = _history_roots(output_root)
    if zero_hit_confirmation_root is not None:
        if not zero_hit_confirmation_root.is_dir() or (
            zero_hit_confirmation_root == output_root
            or zero_hit_confirmation_root in output_root.parents
        ):
            raise ClosureFailure("CONFIRMATION_ROOT_INVALID_OR_OVERLAPPED")
        if zero_hit_confirmation_root not in history_roots:
            history_roots += (zero_hit_confirmation_root,)
    revision = candidate_revision or (
        CONFIRMATION_REVISION if zero_hit_confirmation_root else CANDIDATE_REVISION
    )
    controls = replay_control_ids if replay_task_ids else (
        () if zero_hit_confirmation_root else REGRESSION_CONTROLS
    )
    history_before = _history_snapshot(history_roots)
    source_before = _source_snapshot()
    prompts_before = nonprompt._prompt_digests()
    output_root.mkdir(parents=True)
    run_id = "evaluation_run:stage21-final-residual-" + uuid4().hex
    store = None
    selected: tuple[str, ...] = ()
    write = prompt_audit._write_json
    write(output_root / "run-intent.json", {
        "benchmarkRevision": revision, "evaluationRunId": run_id,
        "zeroHitConfirmationRoot": (
            str(zero_hit_confirmation_root) if zero_hit_confirmation_root else None
        ),
        "formal105Status": "NOT_RUN", "historicalDigestsBefore": history_before,
        "sourceDigestsBefore": source_before, "promptDigestsBefore": prompts_before,
        "provider": {"provider": "Qwen", "model": "qwen3.8-max"},
        "explicitTaskIds": replay_task_ids,
        "priorProjectionPaths": [str(path) for path in prior_projection_paths],
    })

    def verify_source() -> None:
        if _source_snapshot() != source_before:
            raise ClosureFailure("SOURCE_REVISION_DRIFT")

    try:
        official, _, _ = prompt_audit._official_inputs()
        prompt = _load_projection(PROMPT_ROOT / "outcome-v2-targeted.json")
        previous = _load_projection(NONPROMPT_ROOT / "outcome-v2-targeted.json")
        last_known = _overlay_statuses((official, prompt, previous))
        selected = _selected_cohort(previous, last_known)
        estimate_layers = (official, prompt, previous)
        if replay_task_ids is not None:
            estimate_layers += tuple(_load_projection(path) for path in prior_projection_paths)
            last_known = _overlay_statuses(estimate_layers)
            if not set(replay_task_ids) <= set(last_known):
                raise ClosureFailure("TARGETED_SCOPE_UNRECOGNIZED_TASK")
            if any(last_known[key] != "PASS" for key in controls):
                raise ClosureFailure("REGRESSION_CONTROL_BASELINE_DRIFT")
            selected = replay_task_ids
        if zero_hit_confirmation_root is not None:
            first_summary = json.loads(
                (zero_hit_confirmation_root / "final-summary.json").read_text(encoding="utf-8")
            )
            if first_summary.get("status") != "PASS" or (
                first_summary.get("benchmarkRevision") != CANDIDATE_REVISION
            ):
                raise ClosureFailure("CONFIRMATION_FIRST_RUN_INVALID")
            first_run, _ = _read_persisted_run(
                zero_hit_confirmation_root / COHORT_LABEL / "results",
                first_summary["evaluationRunId"], selected,
            )
            first_projection = _load_projection(
                zero_hit_confirmation_root / "outcome-v2-targeted.json"
            )
            if set(_statuses(first_projection)) != set(selected):
                raise ClosureFailure("CONFIRMATION_FIRST_PROJECTION_COHORT_MISMATCH")
            _validate_zero_hit_confirmation(first_projection, first_run.results)
            estimate_layers += (first_projection,)
            last_known = _overlay_statuses(estimate_layers)
            selected = ZERO_HIT_TASKS
        settings = get_settings()
        if settings.qwen_model != "qwen3.8-max" or settings.diagnosis_llm_provider != "qwen":
            raise ClosureFailure("CONFIGURED_PROVIDER_IDENTITY_FAILED")
        dataset = load_dataset(formal.MANIFEST_PATH)
        rag_only = bool(selected) and all(
            task.task_type.value == "RAG_EVIDENCE_RETRIEVAL"
            for task in dataset.tasks if task.benchmark_task_id in selected
        )
        policy = load_outcome_policy(formal.POLICY_PATH, dataset=dataset)
        gate = formal._qwen_provider_gate(settings, acceptance_dir)
        if formal._environment_readiness(settings, "qwen").get("ready") is not True:
            raise ClosureFailure("ENVIRONMENT_NOT_READY")
        original_cohort = residual_pipeline.RESIDUAL_TASKS
        residual_pipeline.RESIDUAL_TASKS = selected
        try:
            preflight = await residual_pipeline._focused_runtime_preflight(settings, dataset)
        finally:
            residual_pipeline.RESIDUAL_TASKS = original_cohort
        write(output_root / "focused-runtime-preflight.json", preflight)
        if preflight.get("status") != "PASS":
            raise ClosureFailure("RUNTIME_PREFLIGHT_FAILED")
        write(output_root / "repair-manifest.json", {
            "benchmarkRevision": revision, "evaluationRunId": run_id,
            "targetedTaskIds": selected, "providerAcceptance": gate,
            "residualTaskIds": (
                tuple(key for key in selected if key not in controls)
                if zero_hit_confirmation_root or replay_task_ids
                else _residual_cohort(previous)
            ),
            "regressionControlIds": controls,
            "zeroHitConfirmationRoot": (
                str(zero_hit_confirmation_root) if zero_hit_confirmation_root else None
            ),
            "sourceOfficialRoot": str(prompt_audit.OFFICIAL_ROOT),
            "previousTargetedRoot": str(NONPROMPT_ROOT), "formal105Status": "NOT_RUN",
        })
        destination = output_root / COHORT_LABEL
        store = VerifiedStore(
            destination / "results", verify_source,
            zero_hit_confirmation=zero_hit_confirmation_root is not None,
        )
        preflight_artifact_paths(plan_baseline_artifact_paths(
            destination, run_id, selected, result_store=store
        ))
        verify_source()
        async with httpx.AsyncClient(trust_env=False) as client:
            runner = baseline._build_runner(settings, client, provider="qwen")
            await runner.run_dataset(
                formal.MANIFEST_PATH, evaluation_run_id=run_id,
                task_ids=selected, result_store=store,
            )
        run, integrity = _read_persisted_run(store.root, run_id, selected)
        persist_baseline_artifacts(
            run, dataset, baseline._configuration(settings, "all", "qwen"),
            output_dir=destination, result_store=store,
        )
        provider = verify_provider_integrity(
            run.results, expected_provider="Qwen", expected_model="qwen3.8-max"
        )
        write(output_root / "provider-integrity.json", provider)
        if not (
            _confirmation_has_no_model_calls(run.results, provider)
            if zero_hit_confirmation_root or rag_only
            else _provider_clean(provider, require_call=True)
        ):
            raise ClosureFailure("PROVIDER_IDENTITY_FAILED")
        projection = project_outcome_v2(
            run, policy, source_artifact=destination, require_full_dataset=False
        )
        comparison = _comparison(
            last_known, projection, controls=controls,
        )
        estimate = _estimate((*estimate_layers, projection))
        if zero_hit_confirmation_root:
            estimate["basis"] += " -> first18 -> zero-hit confirmation2"
        elif replay_task_ids:
            estimate["basis"] = (
                "task identity chronological overlay: official v4 -> prompt -> nonprompt "
                "-> declared prior projections -> explicit targeted replay"
            )
        write(output_root / "outcome-v2-targeted.json", projection.model_dump(mode="json"))
        write(output_root / "targeted-comparison.json", comparison)
        verify_source()
        history_after = _history_snapshot(history_roots)
        if history_after != history_before:
            raise ClosureFailure("HISTORICAL_ARTIFACT_DRIFT")
        if nonprompt._prompt_digests() != prompts_before:
            raise ClosureFailure("PROMPT_DRIFT_DURING_RUN")
        secrets = tuple({
            *formal._known_secret_values(settings),
            *(value for name, value in os.environ.items()
              if (name.endswith("_PASSWORD") or name.endswith("_API_KEY")) and value),
        })
        leakage = formal._scan_artifact_secrets(output_root, secrets)
        if leakage:
            raise ClosureFailure("ARTIFACT_CREDENTIAL_LEAKAGE")
        summary = {
            "schemaVersion": "stage21-final-residual-closure/v1", "status": "PASS",
            "benchmarkRevision": revision, "evaluationRunId": run_id,
            "outputRoot": str(output_root), "formal105Status": "NOT_RUN",
            "targetedTaskIds": selected, "integrity": integrity,
            "residualTaskCount": (
                len(selected) - len(controls) if zero_hit_confirmation_root or replay_task_ids
                else EXPECTED_RESIDUAL_COUNT
            ),
            "regressionControlCount": len(controls),
            "providerProvenance": (
                "NO_MODEL_CALL" if zero_hit_confirmation_root or rag_only else "PASS"
            ),
            "modelCallCount": sum(row.model_call_count for row in run.results),
            "comparison": comparison,
            "estimatedFormal105": estimate, "historicalArtifactsPreserved": True,
            "sourceFrozenDuringRun": True, "promptsFrozenDuringRun": True,
            "leakageScan": {"status": "PASS", "matchingPathCount": 0},
        }
    except Exception as exc:  # noqa: BLE001 - preserve partial run without leaking payloads
        summary = {
            "schemaVersion": "stage21-final-residual-closure/v1", "status": "FAIL_CLOSED",
            "benchmarkRevision": revision, "evaluationRunId": run_id,
            "outputRoot": str(output_root), "formal105Status": "NOT_RUN",
            "failureCode": str(exc) if isinstance(exc, ClosureFailure) else type(exc).__name__,
            "selected": len(selected), "executed": store.executed if store else 0,
            "persistedTaskFileCount": len(tuple(output_root.glob("**/task-*.json"))),
            "historicalArtifactsPreserved": _history_snapshot(history_roots) == history_before,
            "sourceFrozenDuringRun": _source_snapshot() == source_before,
            "promptsFrozenDuringRun": nonprompt._prompt_digests() == prompts_before,
            "estimateAvailable": False, "automaticSecondRun": False,
        }
    write(output_root / "final-summary.json", summary)
    return summary


def main() -> int:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, default=REPOSITORY_ROOT / (
        f"f105r/final-residual-closure-{stamp}"
    ))
    parser.add_argument("--qwen-acceptance-dir", type=Path, default=formal.QWEN_ACCEPTANCE_DIR)
    parser.add_argument("--zero-hit-confirmation-root", type=Path)
    args = parser.parse_args()
    summary = asyncio.run(_run(
        args.output_root.resolve(), args.qwen_acceptance_dir.resolve(),
        args.zero_hit_confirmation_root.resolve() if args.zero_hit_confirmation_root else None,
    ))
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True, indent=2))
    return 0 if summary["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
