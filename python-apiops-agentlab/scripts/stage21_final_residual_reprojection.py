"""Offline Outcome V2 reprojection; never execute a task, model, or Java tool."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

import stage21_final_residual_closure as closure

from app.benchmark import load_dataset
from app.benchmark.outcome_v2 import load_outcome_policy, project_outcome_v2


def _composite_comparison(
    old: dict[str, str], latest: dict[str, str], source_run_ids: dict[str, str]
) -> dict[str, object]:
    transitions = Counter(f"{old[key]}->{value}" for key, value in latest.items())
    counts = Counter(latest.values())
    denominator = counts["PASS"] + counts["FAIL"]
    return {
        "selectedUnique": len(latest),
        "oldFailToPass": transitions["FAIL->PASS"],
        "oldUnknownToPass": transitions["UNKNOWN->PASS"],
        "stillFail": counts["FAIL"], "stillUnknown": counts["UNKNOWN"],
        "targetedPass": counts["PASS"], "targetedFail": counts["FAIL"],
        "targetedUnknown": counts["UNKNOWN"],
        "targetedOutcomeAccuracy": counts["PASS"] / denominator if denominator else None,
        "transitionCounts": dict(transitions),
        "tasks": [
            {
                "benchmarkTaskId": key, "oldStatus": old[key], "newStatus": value,
                "sourceEvaluationRunId": source_run_ids[key],
                "role": "REGRESSION_CONTROL" if key in closure.REGRESSION_CONTROLS else "RESIDUAL",
            }
            for key, value in sorted(latest.items())
        ],
    }


def _validate_changes(
    old_first: dict[str, str], new_first: dict[str, str],
    old_confirmation: dict[str, str], new_confirmation: dict[str, str],
) -> dict[str, object]:
    allowed = set(closure.ZERO_HIT_TASKS)
    if (
        len(old_first) != 18 or set(new_first) != set(old_first)
        or set(old_confirmation) != allowed or set(new_confirmation) != allowed
    ):
        raise closure.ClosureFailure("REPROJECTION_COHORT_MISMATCH")
    changed_first = {key for key in old_first if old_first[key] != new_first[key]}
    changed_confirmation = {
        key for key in old_confirmation if old_confirmation[key] != new_confirmation[key]
    }
    if changed_first - allowed:
        raise closure.ClosureFailure("REPROJECTION_CHANGED_NON_ZERO_HIT_TASK")
    return {
        "onlyZeroHitPolicyChanges": True,
        "other16StatusesUnchanged": True,
        "firstRunChangedTaskIds": sorted(changed_first),
        "confirmationChangedTaskIds": sorted(changed_confirmation),
        "zeroHitProjectionClosed": all(new_confirmation[key] == "PASS" for key in allowed),
    }


def _run(first_root: Path, confirmation_root: Path, output_root: Path) -> dict[str, object]:
    if output_root.exists():
        raise closure.ClosureFailure("REPROJECTION_OUTPUT_ALREADY_EXISTS")
    history_roots = closure._history_roots(output_root)
    for root in (first_root, confirmation_root):
        if not root.is_dir() or root == output_root or root in output_root.parents:
            raise closure.ClosureFailure("REPROJECTION_INPUT_INVALID_OR_OVERLAPPED")
        if root not in history_roots:
            history_roots += (root,)
    history_before = closure._history_snapshot(history_roots)
    sources_before = closure._source_snapshot()
    output_root.mkdir(parents=True)
    write = closure.prompt_audit._write_json
    write(output_root / "reprojection-intent.json", {
        "mode": "REPROJECTION_ONLY", "newTaskExecutions": 0,
        "newModelCalls": 0, "newToolCalls": 0,
        "historicalDigestsBefore": history_before, "sourceDigestsBefore": sources_before,
        "firstRunRoot": str(first_root), "confirmationRunRoot": str(confirmation_root),
    })
    try:
        official, _, _ = closure.prompt_audit._official_inputs()
        prompt = closure._load_projection(closure.PROMPT_ROOT / "outcome-v2-targeted.json")
        previous = closure._load_projection(closure.NONPROMPT_ROOT / "outcome-v2-targeted.json")
        baseline_statuses = closure._overlay_statuses((official, prompt, previous))
        first_ids = closure._selected_cohort(previous, baseline_statuses)
        runs = []
        original_projections = []
        integrity_reports = []
        for root, ids, revision in (
            (first_root, first_ids, closure.CANDIDATE_REVISION),
            (confirmation_root, closure.ZERO_HIT_TASKS, closure.CONFIRMATION_REVISION),
        ):
            saved = json.loads((root / "final-summary.json").read_text(encoding="utf-8"))
            if saved.get("status") != "PASS" or saved.get("benchmarkRevision") != revision:
                raise closure.ClosureFailure("REPROJECTION_SOURCE_RUN_INVALID")
            run, integrity = closure._read_persisted_run(
                root / closure.COHORT_LABEL / "results", saved["evaluationRunId"], ids
            )
            runs.append(run)
            integrity_reports.append(integrity)
            original_projections.append(closure._load_projection(root / "outcome-v2-targeted.json"))
        closure._validate_zero_hit_confirmation(original_projections[0], runs[0].results)
        if runs[0].evaluation_run_id == runs[1].evaluation_run_id:
            raise closure.ClosureFailure("REPROJECTION_SOURCE_RUN_ID_COLLISION")
        dataset = load_dataset(closure.formal.MANIFEST_PATH)
        policy = load_outcome_policy(closure.formal.POLICY_PATH, dataset=dataset)
        projected = tuple(
            project_outcome_v2(run, policy, source_artifact=root, require_full_dataset=False)
            for run, root in zip(runs, (first_root, confirmation_root), strict=True)
        )
        proof = _validate_changes(
            closure._statuses(original_projections[0]), closure._statuses(projected[0]),
            closure._statuses(original_projections[1]), closure._statuses(projected[1]),
        )
        latest = {**closure._statuses(projected[0]), **closure._statuses(projected[1])}
        task_sources = {
            **{key: runs[0].evaluation_run_id for key in first_ids},
            **{key: runs[1].evaluation_run_id for key in closure.ZERO_HIT_TASKS},
        }
        comparison = _composite_comparison(baseline_statuses, latest, task_sources)
        estimate = closure._estimate((official, prompt, previous, *projected))
        estimate["basis"] = (
            "task identity overlay: official v4 -> prompt replay -> nonprompt "
            "-> first18 reprojection -> confirmation2 reprojection"
        )
        for name, projection in zip(
            ("outcome-first18-reprojected.json", "outcome-confirmation2-reprojected.json"),
            projected, strict=True,
        ):
            write(output_root / name, projection.model_dump(mode="json"))
        write(output_root / "composite-task-results.json", comparison)
        history_after = closure._history_snapshot(history_roots)
        sources_after = closure._source_snapshot()
        if history_after != history_before or sources_after != sources_before:
            raise closure.ClosureFailure("REPROJECTION_INPUT_OR_SOURCE_DRIFT")
        summary = {
            "schemaVersion": "stage21-final-residual-reprojection/v1",
            "status": "PASS", "mode": "REPROJECTION_ONLY",
            "sourceEvaluationRunIds": [run.evaluation_run_id for run in runs],
            "newTaskExecutions": 0, "newModelCalls": 0, "newToolCalls": 0,
            "formal105Status": "NOT_RUN", "outputRoot": str(output_root),
            "inputArtifactIntegrity": integrity_reports,
            "historicalArtifactsPreserved": True, "sourceFrozenDuringReprojection": True,
            "policyChangeProof": proof, "comparison": comparison,
            "estimatedFormal105": estimate,
        }
    except Exception as exc:  # noqa: BLE001 - preserve bounded diagnostic evidence
        summary = {
            "status": "FAIL_CLOSED", "mode": "REPROJECTION_ONLY",
            "failureCode": (
                str(exc) if isinstance(exc, closure.ClosureFailure) else type(exc).__name__
            ),
            "newTaskExecutions": 0, "newModelCalls": 0, "newToolCalls": 0,
            "historicalArtifactsPreserved": (
                closure._history_snapshot(history_roots) == history_before
            ),
        }
    write(output_root / "final-summary.json", summary)
    return summary


def main() -> int:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--first-run-root", type=Path, required=True)
    parser.add_argument("--confirmation-run-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, default=closure.REPOSITORY_ROOT / (
        f"f105r/final-residual-reprojection-{stamp}"
    ))
    args = parser.parse_args()
    summary = _run(
        args.first_run_root.resolve(), args.confirmation_run_root.resolve(),
        args.output_root.resolve(),
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if summary["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
