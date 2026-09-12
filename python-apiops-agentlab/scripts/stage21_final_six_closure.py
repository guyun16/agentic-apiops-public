"""Replay exactly the six declared residuals through the existing Java-authoritative pipeline."""

from __future__ import annotations

import argparse
import asyncio
import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

import stage21_final_residual_closure as closure

REVISION = "stage21-final-six-closure-v1"
PRIOR_ROOT = closure.REPOSITORY_ROOT / "f105r/final-residual-reprojection-20260905T014540Z"
PRIOR_PROJECTIONS = (
    PRIOR_ROOT / "outcome-first18-reprojected.json",
    PRIOR_ROOT / "outcome-confirmation2-reprojected.json",
)
TARGETS = (
    "bench_task_rag_irrelevant_distractor",
    "bench_task_formal_testcase_business_inventory_expected",
    "bench_task_formal_testcase_auth_missing_token_post",
    "bench_task_formal_testcase_inventory_conflict_metadata",
    "bench_task_testcase_business_inventory_python",
    "bench_task_formal_e2e_generation_diagnosis_guarded",
)
CONTROLS = (
    "bench_task_formal_rag_near_match_exact",
    "bench_task_formal_rag_zero_hit_authorized",
    "bench_task_e2e_diagnosis_tool_guarded",
    "bench_task_testcase_business_inventory_runner",
)
RAG_CONFIRMATION_TASKS = (TARGETS[0], CONTROLS[0])


def validate_baseline() -> None:
    official, _, _ = closure.prompt_audit._official_inputs()
    layers = (
        official,
        closure._load_projection(closure.PROMPT_ROOT / "outcome-v2-targeted.json"),
        closure._load_projection(closure.NONPROMPT_ROOT / "outcome-v2-targeted.json"),
        *(closure._load_projection(path) for path in PRIOR_PROJECTIONS),
    )
    statuses = closure._overlay_statuses(layers)
    if Counter(statuses.values()) != Counter({"PASS": 99, "FAIL": 2, "UNKNOWN": 4}):
        raise closure.ClosureFailure("FINAL_SIX_BASELINE_DRIFT")
    if {key for key, value in statuses.items() if value != "PASS"} != set(TARGETS):
        raise closure.ClosureFailure("FINAL_SIX_RESIDUAL_IDENTITY_DRIFT")
    if any(statuses.get(key) != "PASS" for key in CONTROLS):
        raise closure.ClosureFailure("FINAL_SIX_CONTROL_BASELINE_DRIFT")


def main() -> int:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path)
    parser.add_argument("--rag-confirmation-root", type=Path)
    args = parser.parse_args()
    validate_baseline()
    prior_paths = PRIOR_PROJECTIONS
    selected = (*TARGETS, *CONTROLS)
    controls = CONTROLS
    revision = REVISION
    label = "final-six-closure"
    if args.rag_confirmation_root:
        previous_root = args.rag_confirmation_root.resolve()
        previous = json.loads((previous_root / "final-summary.json").read_text(encoding="utf-8"))
        if previous.get("status") != "PASS" or previous.get("benchmarkRevision") != REVISION:
            raise closure.ClosureFailure("RAG_CONFIRMATION_PREVIOUS_RUN_INVALID")
        closure._read_persisted_run(
            previous_root / closure.COHORT_LABEL / "results",
            previous["evaluationRunId"], selected,
        )
        previous_projection = previous_root / "outcome-v2-targeted.json"
        if set(closure._statuses(closure._load_projection(previous_projection))) != set(selected):
            raise closure.ClosureFailure("RAG_CONFIRMATION_PREVIOUS_COHORT_INVALID")
        prior_paths += (previous_projection,)
        selected = RAG_CONFIRMATION_TASKS
        controls = (CONTROLS[0],)
        revision = "stage21-final-six-closure-v2"
        label = "final-six-rag-confirmation"
    output_root = (args.output_root or closure.REPOSITORY_ROOT / f"f105r/{label}-{stamp}").resolve()
    summary = asyncio.run(closure._run(
        output_root, closure.formal.QWEN_ACCEPTANCE_DIR.resolve(),
        replay_task_ids=selected, replay_control_ids=controls,
        prior_projection_paths=prior_paths, candidate_revision=revision,
    ))
    if summary["status"] == "PASS":
        projection = closure._load_projection(output_root / "outcome-v2-targeted.json")
        old = {
            row["benchmarkTaskId"]: row["oldStatus"]
            for row in summary["comparison"]["tasks"]
        }
        final_six = projection.model_copy(update={
            "tasks": tuple(row for row in projection.tasks if row.benchmark_task_id in TARGETS),
        })
        key = (
            "confirmationResidualComparison" if args.rag_confirmation_root else "finalSixComparison"
        )
        summary[key] = closure._comparison(old, final_six, controls=())
        if args.rag_confirmation_root:
            summary["confirmationReason"] = (
                "Live negative control retained a comparison-only foreign-service reference "
                "despite metric PASS; confirm primary-topic selection repair, not score retry."
            )
            summary["previousRunRoot"] = str(previous_root)
        closure.prompt_audit._write_json(output_root / "final-summary.json", summary)
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True, indent=2))
    return 0 if summary["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
