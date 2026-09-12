"""Compare the frozen Stage21 baseline, offline V2 projection, and one new run.

This report is intentionally read-only with respect to benchmark execution.  It
loads the three already-persisted artifacts, uses the V2 projector's delta
builder for task/category transitions, and writes only comparison artifacts
under the new experiment directory.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

from app.benchmark.outcome_v2 import (
    OutcomeV2Projection,
    build_outcome_v2_delta,
    load_persisted_outcome_v2_projection,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
STAGE21_ROOT = REPOSITORY_ROOT / "artifacts" / "stage21"
BASELINE_ROOT = STAGE21_ROOT / "final-v2-formal105"
OFFLINE_ROOT = STAGE21_ROOT / "v2-outcome-relaxed-offline"
NEW_ROOT = STAGE21_ROOT / "outcome-first-rag-enhanced-105"
FORMAL_TASK_COUNT = 105
OUTCOME_TARGET = 0.80


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise RuntimeError(f"comparison input is missing: {path}")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"comparison input must be a JSON object: {path}")
    return value


def _write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _metric_value(metric: object) -> float | None:
    if isinstance(metric, (int, float)):
        return float(metric)
    if not isinstance(metric, dict):
        return None
    value = metric.get("value")
    if value is None:
        value = metric.get("mean")
    return float(value) if isinstance(value, (int, float)) else None


def _rate(value: float | None, numerator: int, denominator: int, unknown: int) -> dict[str, Any]:
    return {
        "status": "VALUE" if value is not None else "NOT_APPLICABLE",
        "value": value,
        "numerator": numerator,
        "denominator": denominator,
        "unknownCount": unknown,
    }


def _projection_view(projection: OutcomeV2Projection) -> dict[str, Any]:
    return {
        "policyVersion": projection.policy_version,
        "datasetId": projection.dataset_id,
        "datasetVersion": projection.dataset_version,
        "sourceArtifact": projection.source_artifact,
        "taskCount": projection.task_count,
        "projectedTaskCount": projection.projected_task_count,
        "splitCounts": projection.split_counts,
        "statusCounts": projection.v2_status_counts,
        "v1StatusCounts": projection.v1_status_counts,
        "outcomeAccuracy": projection.outcome_accuracy.model_dump(mode="json"),
        "outcomeAuthorityGapCount": projection.outcome_authority_gap_count,
        "requiredTool": {
            "count": projection.required_tool_count,
            "invoked": projection.required_tool_invocation_count,
            "miss": projection.required_tool_miss_count,
            "missRate": projection.required_tool_miss_rate.model_dump(mode="json"),
        },
        "categories": [
            category.model_dump(mode="json") for category in projection.categories
        ],
    }


def _tool_view(summary: dict[str, Any]) -> dict[str, Any]:
    tool = summary.get("toolUse", {})
    required = tool.get("Required Tool Coverage", {})
    required_miss_rate = tool.get("Required Tool Miss Rate", {})
    optional = tool.get("Optional Tool Invocation Rate", {})
    overall = tool.get("overall Tool Invocation Rate", {})
    return {
        "required": {
            "count": tool.get("TOOL_REQUIRED", 0),
            "invoked": tool.get("Required Tool Invoked", 0),
            "miss": tool.get("Required Tool Miss", 0),
            "coverage": required,
            "missRate": required_miss_rate,
        },
        "optional": {
            "count": tool.get("OPTIONAL tasks", 0),
            "invoked": optional.get("numerator", 0),
            "invocationRate": optional,
        },
        "overall": overall,
        "classificationCounts": tool.get("classificationCounts", {}),
    }


def _stage19_view(summary: dict[str, Any]) -> dict[str, Any]:
    metric_names = (
        "tool_precision",
        "tool_recall",
        "parameter_accuracy",
        "evidence_hit",
        "diagnosis_accuracy",
        "safety_accuracy",
    )
    metrics = summary.get("evaluationMetrics", {})
    return {
        "evaluationMetrics": {
            name: metrics.get(name, {}) for name in metric_names
        },
        "formal105EvidenceHit": summary.get("evidenceHit", {}).get("formal105", {}),
        "deterministicRag": summary.get("evidenceHit", {}).get("deterministicRag", {}),
    }


def _safety_view(summary: dict[str, Any]) -> dict[str, Any]:
    metrics = summary.get("evaluationMetrics", {})
    safety_metric = metrics.get("safety_accuracy", {})
    expected_deny = summary.get("expectedDeny", {})
    deny_count = int(expected_deny.get("taskCount", 0))
    deny_observed = int(expected_deny.get("observedExpectedDeny", 0))
    deny_rate = deny_observed / deny_count if deny_count else None
    applicable = int(safety_metric.get("applicable_count", 0))
    judgeable = int(safety_metric.get("value_count", 0))
    judgeability = judgeable / applicable if applicable else None
    collateral = summary.get("collateralDamage", {})
    return {
        "safetyOutcomeAccuracy": safety_metric,
        "safetyJudgeability": {
            "judgeableCount": judgeable,
            "applicableCount": applicable,
            "unknownCount": int(safety_metric.get("unknown_count", 0)),
            "rate": judgeability,
        },
        "safetyProcessCoverage": {
            "expectedDeny": expected_deny,
            "expectedDenyCoverage": _rate(
                deny_rate, deny_observed, deny_count, 0
            ),
            "unexpectedUnsafeBehavior": summary.get(
                "unexpectedUnsafeBehavior", {}
            ),
            "collateralDamage": collateral.get("summary", collateral),
        },
    }


def _runtime_view(summary: dict[str, Any], mode: str) -> dict[str, Any]:
    return {
        "mode": mode,
        "selected": summary.get("selected"),
        "executed": summary.get("executed"),
        "persistedTaskArtifacts": summary.get("persistedTaskArtifacts"),
        "evaluationRunId": summary.get("evaluationRunId"),
        "status": summary.get("runtimeStatus", {}),
        "boundaryChecks": summary.get("boundaryChecks", {}),
        "baselineFrozen": summary.get("baselineFrozen"),
    }


def _model_view(summary: dict[str, Any]) -> dict[str, Any]:
    return summary.get("model", {})


def _split_view(projection: OutcomeV2Projection) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for split in ("DEV", "HELD_OUT"):
        tasks = [
            task for task in projection.tasks if task.split.value.upper() == split
        ]
        counts = Counter(task.v2_status.value for task in tasks)
        passes = counts["PASS"]
        fails = counts["FAIL"]
        unknown = counts["UNKNOWN"]
        required_miss = sum(
            any(
                requirement.requirement.value == "REQUIRED"
                and not requirement.invoked
                for requirement in task.tool_requirements
            )
            for task in tasks
        )
        result[split] = {
            "taskCount": len(tasks),
            "statusCounts": {
                "PASS": passes,
                "FAIL": fails,
                "UNKNOWN": unknown,
            },
            "outcomeAccuracy": _rate(
                passes / (passes + fails) if passes + fails else None,
                passes,
                passes + fails,
                unknown,
            ),
            "outcomeAuthorityGapCount": sum(
                task.outcome_authority_gap for task in tasks
            ),
            "requiredToolMiss": required_miss,
        }
    return result


def _record(
    label: str,
    projection: OutcomeV2Projection,
    summary: dict[str, Any],
    *,
    mode: str,
    freeze_path: Path | None,
) -> dict[str, Any]:
    freeze = _read_json(freeze_path) if freeze_path is not None else {}
    return {
        "label": label,
        "mode": mode,
        "projection": _projection_view(projection),
        "runtime": _runtime_view(summary, mode),
        "v1": {"statusCounts": projection.v1_status_counts},
        "tool": _tool_view(summary),
        "stage19Diagnostics": _stage19_view(summary),
        "safety": _safety_view(summary),
        "model": _model_view(summary),
        "splits": _split_view(projection),
        "freeze": {
            "path": str(freeze_path) if freeze_path is not None else None,
            "gitHead": freeze.get("gitHead"),
            "dirtyDiffDigest": freeze.get("dirtyDiffDigest"),
            "workingTreeDirty": freeze.get("workingTreeDirty"),
            "freezeStatus": freeze.get("freezeStatus"),
            "baselineFrozen": summary.get("baselineFrozen"),
        },
    }


def _assert_projection_set(
    projections: dict[str, OutcomeV2Projection],
) -> None:
    task_sets = {
        label: {task.benchmark_task_id for task in projection.tasks}
        for label, projection in projections.items()
    }
    for label, projection in projections.items():
        if projection.task_count != FORMAL_TASK_COUNT:
            raise RuntimeError(
                f"{label} taskCount must be {FORMAL_TASK_COUNT}: "
                f"{projection.task_count}"
            )
        if projection.projected_task_count != FORMAL_TASK_COUNT:
            raise RuntimeError(
                f"{label} projectedTaskCount must be {FORMAL_TASK_COUNT}: "
                f"{projection.projected_task_count}"
            )
    if len({frozenset(value) for value in task_sets.values()}) != 1:
        raise RuntimeError("A/B/C projections do not contain the same task IDs")
    dataset_identity = {
        (projection.dataset_id, projection.dataset_version, projection.task_schema_version)
        for projection in projections.values()
    }
    if len(dataset_identity) != 1:
        raise RuntimeError("A/B/C projections do not share dataset identity")


def _number_delta(old: float | None, new: float | None) -> float | None:
    if old is None or new is None:
        return None
    return new - old


def _triplet(values: dict[str, float | None]) -> dict[str, Any]:
    return {
        **values,
        "A_to_B": _number_delta(values["A"], values["B"]),
        "B_to_C": _number_delta(values["B"], values["C"]),
        "A_to_C": _number_delta(values["A"], values["C"]),
    }


def _count_triplet(
    projections: dict[str, OutcomeV2Projection],
) -> dict[str, Any]:
    statuses = ("PASS", "FAIL", "UNKNOWN")
    values = {
        label: {status: projection.v2_status_counts.get(status, 0) for status in statuses}
        for label, projection in projections.items()
    }
    return {
        **values,
        "A_to_B": {
            status: values["B"][status] - values["A"][status]
            for status in statuses
        },
        "B_to_C": {
            status: values["C"][status] - values["B"][status]
            for status in statuses
        },
        "A_to_C": {
            status: values["C"][status] - values["A"][status]
            for status in statuses
        },
    }


def _split_deltas(
    records: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for split in ("DEV", "HELD_OUT"):
        values = {
            label: records[label]["splits"][split] for label in records
        }
        output[split] = {
            "A": values["A"],
            "B": values["B"],
            "C": values["C"],
            "A_to_B": {
                "statusCounts": {
                    status: values["B"]["statusCounts"][status]
                    - values["A"]["statusCounts"][status]
                    for status in ("PASS", "FAIL", "UNKNOWN")
                },
                "outcomeAccuracy": _number_delta(
                    values["A"]["outcomeAccuracy"]["value"],
                    values["B"]["outcomeAccuracy"]["value"],
                ),
            },
            "B_to_C": {
                "statusCounts": {
                    status: values["C"]["statusCounts"][status]
                    - values["B"]["statusCounts"][status]
                    for status in ("PASS", "FAIL", "UNKNOWN")
                },
                "outcomeAccuracy": _number_delta(
                    values["B"]["outcomeAccuracy"]["value"],
                    values["C"]["outcomeAccuracy"]["value"],
                ),
            },
        }
    return output


def _metric_triplet(
    records: dict[str, dict[str, Any]],
    path: tuple[str, ...],
) -> dict[str, Any]:
    values: dict[str, float | None] = {}
    for label, record in records.items():
        value: object = record
        for key in path:
            if not isinstance(value, dict):
                value = None
                break
            value = value.get(key)
        values[label] = _metric_value(value)
    return _triplet(values)


def _load_inputs(output_root: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    paths = {
        "A": {
            "projection": BASELINE_ROOT / "outcome-v2.json",
            "summary": BASELINE_ROOT / "formal105-summary.json",
            "freeze": BASELINE_ROOT / "freeze-manifest.json",
        },
        "B": {
            "projection": OFFLINE_ROOT / "outcome-v2.json",
            "summary": OFFLINE_ROOT / "outcome-v2-summary.json",
            "freeze": None,
        },
        "C": {
            "projection": output_root / "outcome-v2.json",
            "summary": output_root / "formal105-summary.json",
            "freeze": output_root / "freeze-manifest.json",
        },
    }
    projections = {
        label: load_persisted_outcome_v2_projection(values["projection"])
        for label, values in paths.items()
    }
    summaries = {
        "A": _read_json(paths["A"]["summary"]),
        "B": _read_json(paths["B"]["summary"]),
        "C": _read_json(paths["C"]["summary"]),
    }
    _assert_projection_set(projections)
    if projections["B"].source_artifact != projections["A"].source_artifact:
        raise RuntimeError("offline B does not reproject the frozen A run")
    if projections["C"].source_artifact == projections["A"].source_artifact:
        raise RuntimeError("new C run must have a distinct persisted run artifact")
    return projections, summaries


def _build_report(output_root: Path) -> dict[str, Any]:
    projections, summaries = _load_inputs(output_root)
    records = {
        "A": _record(
            "A_PREVIOUS_FROZEN_BASELINE",
            projections["A"],
            summaries["A"],
            mode="FROZEN_BASELINE",
            freeze_path=BASELINE_ROOT / "freeze-manifest.json",
        ),
        "B": _record(
            "B_OFFLINE_V2_REPROJECTION",
            projections["B"],
            summaries["A"],
            mode="OFFLINE_REPROJECTION",
            freeze_path=None,
        ),
        "C": _record(
            "C_NEW105_OUTCOME_FIRST_RAG_ENHANCED",
            projections["C"],
            summaries["C"],
            mode="NEW_REAL_MODEL_105",
            freeze_path=output_root / "freeze-manifest.json",
        ),
    }
    task_delta_ab, category_delta_ab = build_outcome_v2_delta(
        projections["A"], projections["B"]
    )
    task_delta_bc, category_delta_bc = build_outcome_v2_delta(
        projections["B"], projections["C"]
    )
    outcome_values = {
        label: _metric_value(record["projection"]["outcomeAccuracy"])
        for label, record in records.items()
    }
    target_status = (
        "OPTIMIZATION_TARGET_MET"
        if outcome_values["C"] is not None and outcome_values["C"] >= OUTCOME_TARGET
        else "OPTIMIZATION_TARGET_NOT_MET"
    )
    deterministic_rag = {
        label: record["stage19Diagnostics"]["deterministicRag"]
        for label, record in records.items()
    }
    report: dict[str, Any] = {
        "schemaVersion": "stage21-outcome-first-comparison/v1",
        "sourceOfTruth": {
            "A": str(BASELINE_ROOT),
            "B": str(OFFLINE_ROOT),
            "C": str(output_root),
            "datasetTaskCount": FORMAL_TASK_COUNT,
            "offlineUsesModel": False,
            "newRunCount": 1,
        },
        "records": records,
        "comparison": {
            "outcomeAccuracy": _triplet(outcome_values),
            "v2StatusCounts": _count_triplet(projections),
            "requiredToolCoverage": _metric_triplet(
                records, ("tool", "required", "coverage")
            ),
            "requiredToolMissRate": _metric_triplet(
                records, ("tool", "required", "missRate")
            ),
            "evidenceHit": {
                "formal105": _metric_triplet(
                    records, ("stage19Diagnostics", "formal105EvidenceHit")
                ),
                "deterministic": {
                    "Hit@1": {
                        label: deterministic_rag[label].get("Hit@1")
                        for label in records
                    },
                    "Hit@K": {
                        label: deterministic_rag[label].get("Hit@K")
                        for label in records
                    },
                    "Recall@K": {
                        label: deterministic_rag[label].get("Recall@K")
                        for label in records
                    },
                    "MRR": {
                        label: deterministic_rag[label].get("MRR")
                        for label in records
                    },
                },
            },
            "diagnosisAccuracy": _metric_triplet(
                records,
                ("stage19Diagnostics", "evaluationMetrics", "diagnosis_accuracy"),
            ),
            "safetyJudgeability": _metric_triplet(
                records, ("safety", "safetyJudgeability", "rate")
            ),
            "taskDelta": {
                "A_to_B": task_delta_ab,
                "B_to_C": task_delta_bc,
            },
            "categoryDelta": {
                "A_to_B": category_delta_ab,
                "B_to_C": category_delta_bc,
            },
            "devHeldOut": _split_deltas(records),
        },
        "target": {
            "threshold": OUTCOME_TARGET,
            "new105OutcomeAccuracy": outcome_values["C"],
            "status": target_status,
            "nextAction": (
                "NO_FURTHER_TUNING; STOP_FOR_MANAGER_REVIEW"
                if target_status == "OPTIMIZATION_TARGET_NOT_MET"
                else "STOP_FOR_MANAGER_REVIEW"
            ),
        },
        "boundaryCheck": {
            "A": records["A"]["freeze"],
            "B": {
                "mode": "OFFLINE_REPROJECTION",
                "inheritedRunArtifact": projections["B"].source_artifact,
                "modelCalled": False,
                "fixtureFallback": False,
                "pythonBypass": False,
            },
            "C": records["C"]["freeze"],
            "new105OneBenchmarkRun": True,
            "new105Selected": summaries["C"].get("selected"),
            "new105Executed": summaries["C"].get("executed"),
            "new105Persisted": summaries["C"].get("persistedTaskArtifacts"),
            "systemicRuntimeBlocker": summaries["C"]
            .get("boundaryChecks", {})
            .get("systemicInfrastructureBlocker"),
            "noBatchUnknownToPass": all(
                delta["delta"]["unknownToPass"] == 0
                for delta in (task_delta_ab, task_delta_bc)
            ),
        },
    }
    return report


def _fmt(value: object) -> str:
    if value is None:
        return "N/A"
    if isinstance(value, float):
        return f"{value:.6f}"
    return str(value)


def _status_text(record: dict[str, Any]) -> str:
    counts = record["projection"]["statusCounts"]
    return "/".join(str(counts.get(status, 0)) for status in ("PASS", "FAIL", "UNKNOWN"))


def _render_markdown(report: dict[str, Any]) -> str:
    records = report["records"]
    comparison = report["comparison"]
    target = report["target"]
    lines = [
        "# Stage21 Outcome-First A/B/C Comparison",
        "",
        "A is the planning-document-specified frozen `final-v2-formal105` run; "
        "B is a model-free V2 re-projection of that same run; C is the one new "
        "105-task real-model run after the V2 and RAG gates.",
        "",
        "## Core outcome",
        "",
        "| Metric | A frozen baseline | B offline V2 | C new105 |",
        "| --- | ---: | ---: | ---: |",
        (
            "| Outcome Accuracy | "
            f"{_fmt(comparison['outcomeAccuracy']['A'])} | "
            f"{_fmt(comparison['outcomeAccuracy']['B'])} | "
            f"{_fmt(comparison['outcomeAccuracy']['C'])} |"
        ),
        (
            "| V2 PASS/FAIL/UNKNOWN | "
            f"{_status_text(records['A'])} | {_status_text(records['B'])} | "
            f"{_status_text(records['C'])} |"
        ),
        (
            "| Required Tool Coverage | "
            f"{_fmt(comparison['requiredToolCoverage']['A'])} | "
            f"{_fmt(comparison['requiredToolCoverage']['B'])} | "
            f"{_fmt(comparison['requiredToolCoverage']['C'])} |"
        ),
        (
            "| Formal105 Evidence Hit | "
            f"{_fmt(comparison['evidenceHit']['formal105']['A'])} | "
            f"{_fmt(comparison['evidenceHit']['formal105']['B'])} | "
            f"{_fmt(comparison['evidenceHit']['formal105']['C'])} |"
        ),
        (
            "| Diagnosis Accuracy | "
            f"{_fmt(comparison['diagnosisAccuracy']['A'])} | "
            f"{_fmt(comparison['diagnosisAccuracy']['B'])} | "
            f"{_fmt(comparison['diagnosisAccuracy']['C'])} |"
        ),
        (
            "| Safety judgeability | "
            f"{_fmt(comparison['safetyJudgeability']['A'])} | "
            f"{_fmt(comparison['safetyJudgeability']['B'])} | "
            f"{_fmt(comparison['safetyJudgeability']['C'])} |"
        ),
        "",
        "`PASS/FAIL/UNKNOWN` counts are shown in that order. B does not call a model.",
        "",
        "## Deltas",
        "",
        (
            "- A→B outcome delta: "
            f"`{comparison['outcomeAccuracy']['A_to_B']}`; "
            f"status delta `{comparison['v2StatusCounts']['A_to_B']}`."
        ),
        (
            "- B→C outcome delta: "
            f"`{comparison['outcomeAccuracy']['B_to_C']}`; "
            f"status delta `{comparison['v2StatusCounts']['B_to_C']}`."
        ),
        (
            "- Required Tool Coverage A→B/B→C: "
            f"`{comparison['requiredToolCoverage']['A_to_B']}` / "
            f"`{comparison['requiredToolCoverage']['B_to_C']}`."
        ),
        (
            "- Diagnosis Accuracy A→B/B→C: "
            f"`{comparison['diagnosisAccuracy']['A_to_B']}` / "
            f"`{comparison['diagnosisAccuracy']['B_to_C']}`."
        ),
        "",
        "### Task-level changed rows",
        "",
        "| Comparison | Task | Transition | Reason |",
        "| --- | --- | --- | --- |",
    ]
    changed_rows = []
    deltas = (
        ("A→B", comparison["taskDelta"]["A_to_B"]),
        ("B→C", comparison["taskDelta"]["B_to_C"]),
    )
    for name, delta in deltas:
        for row in delta["changedTasks"]:
            changed_rows.append(
                f"| {name} | `{row['benchmarkTaskId']}` | "
                f"`{row['transition']}` | {row['reason']} |"
            )
    lines.extend(changed_rows or ["| — | — | — | no status changes |"])
    lines.extend(
        [
            "",
            "### Deterministic RAG",
            "",
            "| Metric | A | B | C |",
            "| --- | ---: | ---: | ---: |",
        ]
    )
    for metric in ("Hit@1", "Hit@K", "Recall@K", "MRR"):
        values = comparison["evidenceHit"]["deterministic"][metric]
        lines.append(
            f"| {metric} | {_fmt(values['A'])} | {_fmt(values['B'])} | {_fmt(values['C'])} |"
        )
    lines.extend(
        [
            "",
            "## DEV / HELD_OUT",
            "",
            "| Split | A PASS/FAIL/UNKNOWN | B PASS/FAIL/UNKNOWN | C PASS/FAIL/UNKNOWN |",
            "| --- | --- | --- | --- |",
        ]
    )
    for split in ("DEV", "HELD_OUT"):
        values = comparison["devHeldOut"][split]
        lines.append(
            f"| {split} | {_fmt(values['A']['statusCounts']['PASS'])}/"
            f"{_fmt(values['A']['statusCounts']['FAIL'])}/"
            f"{_fmt(values['A']['statusCounts']['UNKNOWN'])} | "
            f"{_fmt(values['B']['statusCounts']['PASS'])}/"
            f"{_fmt(values['B']['statusCounts']['FAIL'])}/"
            f"{_fmt(values['B']['statusCounts']['UNKNOWN'])} | "
            f"{_fmt(values['C']['statusCounts']['PASS'])}/"
            f"{_fmt(values['C']['statusCounts']['FAIL'])}/"
            f"{_fmt(values['C']['statusCounts']['UNKNOWN'])} |"
        )
    lines.extend(
        [
            "",
            "## Gate result",
            "",
            f"- New105 target (threshold `{OUTCOME_TARGET}`): `{target['status']}`.",
            f"- New105 runtime: `{records['C']['runtime']['status']}`; "
            f"selected/executed/persisted=`{records['C']['runtime']['selected']}/"
            f"{records['C']['runtime']['executed']}/"
            f"{records['C']['runtime']['persistedTaskArtifacts']}`.",
            f"- Offline model calls: `{report['boundaryCheck']['B']['modelCalled']}`.",
            f"- Batch UNKNOWN→PASS: `{report['boundaryCheck']['noBatchUnknownToPass']}`.",
            "- No further tuning is authorized by the planning document after a "
            "below-target new105 result.",
            "",
            "The complete machine-readable task/category deltas, process diagnostics, "
            "model/token/latency records, safety process coverage, and boundary checks "
            "are in `comparison.json` beside this file.",
            "",
            "STOP_FOR_MANAGER_REVIEW",
            "",
        ]
    )
    return "\n".join(lines)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-root",
        type=Path,
        default=NEW_ROOT,
        help=(
            "new105 artifact directory (default: "
            "artifacts/stage21/outcome-first-rag-enhanced-105)"
        ),
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    output_root = args.output_root.resolve()
    report = _build_report(output_root)
    _write_json(output_root / "comparison.json", report)
    (output_root / "comparison.md").write_text(
        _render_markdown(report), encoding="utf-8", newline="\n"
    )
    print(
        json.dumps(
            {
                "comparison": str(output_root / "comparison.json"),
                "markdown": str(output_root / "comparison.md"),
                "target": report["target"],
                "outcomeAccuracy": report["comparison"]["outcomeAccuracy"],
                "v2StatusCounts": report["comparison"]["v2StatusCounts"],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
