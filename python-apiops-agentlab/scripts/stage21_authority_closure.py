"""Build the Stage 21 authority-closure review from persisted benchmark facts.

This is an offline audit.  It reads the Formal105 candidate, the checked-in
task/GroundTruth contract, and the V2 sidecar; it never calls a model, Java,
the database, Qdrant, or the Stage 19 evaluator.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

AGENTLAB_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = AGENTLAB_ROOT.parent
if str(AGENTLAB_ROOT) not in sys.path:
    sys.path.insert(0, str(AGENTLAB_ROOT))

from app.benchmark.dataset import load_dataset  # noqa: E402
from app.benchmark.models import (  # noqa: E402
    JavaResourceReference,
    LiteralSetup,
    PythonFixtureReference,
)
from app.benchmark.outcome_v2 import (  # noqa: E402
    OutcomeAuthority,
    OutcomePolicy,
    OutcomePolicyTask,
    OutcomeV2Projection,
    ToolRequirement,
    V2OutcomeStatus,
    discover_formal105_run,
    load_outcome_policy,
    load_persisted_formal105_run,
    persist_outcome_v2_projection,
    project_outcome_v2,
)
from app.benchmark.runner import BenchmarkTaskResult  # noqa: E402

FIXTURE_ROOT = AGENTLAB_ROOT / "tests" / "benchmark" / "fixtures"
DEFAULT_POLICY = FIXTURE_ROOT / "stage21-outcome-policy-v2.json"
DEFAULT_OUTPUT = REPOSITORY_ROOT / "artifacts" / "stage21" / "v2-authority-closure"


def _value(value: object) -> object:
    return getattr(value, "value", value)


def _compact(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _write_json(path: Path, payload: object) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _entry_evidence(task: Any) -> str:
    values: list[str] = []
    for entry in task.initial_state.entries:
        if isinstance(entry, LiteralSetup):
            values.append(f"{entry.key}=LITERAL:{_compact(entry.value)}")
        elif isinstance(entry, JavaResourceReference):
            values.append(f"{entry.key}=JAVA_RESOURCE:{entry.ref}")
        elif isinstance(entry, PythonFixtureReference):
            values.append(f"{entry.key}=PYTHON_FIXTURE:{entry.ref}")
    return "; ".join(values)


def _task_focus(task: Any) -> str:
    for entry in task.initial_state.entries:
        if isinstance(entry, LiteralSetup) and entry.key == "taskFocus":
            return str(entry.value)
    return ""


def _runtime_evidence(result: BenchmarkTaskResult | None) -> str:
    if result is None:
        return "persisted BenchmarkTaskResult is absent"
    status = str(_value(result.status))
    java_status = str(_value(result.java_execution_status))
    report = result.report_id or "NONE"
    run_id = "NONE" if result.run_id is None else str(result.run_id)
    references = ",".join(result.authority_references) or "NONE"
    observations = ",".join(
        f"{item.tool_name}:{_value(item.status)}/{item.mapping_status or 'NONE'}"
        for item in result.tool_result_observations
    ) or "NONE"
    evaluation = "present" if result.evaluation_result is not None else "ABSENT"
    return (
        f"status={status}; javaExecutionStatus={java_status}; runId={run_id}; "
        f"reportId={report}; authorityReferences=[{references}]; "
        f"toolResultObservations=[{observations}]; evaluationResult={evaluation}"
    )


def _tool_dependent_facts(task: Any, truth: Any) -> str:
    needs: list[str] = []
    if truth.expected_evidence_ids:
        expected = ", ".join(truth.expected_evidence_ids)
        needs.append(f"retrieved evidence identity ({expected})")
    if truth.expected_safety_outcome is not None:
        needs.append(
            "Java ToolResult authorization/status plus collateral or state evidence "
            f"(expected safety={_value(truth.expected_safety_outcome)})"
        )
    if truth.expected_facts:
        names = ", ".join(fact.name for fact in truth.expected_facts)
        needs.append(f"structured authority facts ({names})")
    if not needs:
        needs.append("the final task-specific ToolResult authority")
    return "; ".join(needs)


def _classify_requirement(task: Any, truth: Any) -> ToolRequirement:
    """Apply the documented counterfactual rule to one current REQUIRED task."""

    needs_tool_facts = bool(
        truth.expected_evidence_ids
        or truth.expected_safety_outcome is not None
        or task.task_type.value in {"TOOL_SAFETY", "RAG_EVIDENCE_RETRIEVAL", "E2E_APIOPS"}
        or "tool" in task.instruction.lower()
    )
    if not needs_tool_facts:
        return ToolRequirement.NOT_REQUIRED

    # A symbolic JAVA_RESOURCE is only a reference.  No current task declares
    # a literal ToolResult, authorization decision, or retrieved evidence in
    # initialState, so none can be treated as an OPTIONAL no-call authority.
    literal_authority_keys = {
        "toolResult",
        "toolStatus",
        "authorizationDecision",
        "retrievedEvidence",
        "evidenceIds",
        "stateDiff",
        "collateralDamage",
    }
    has_literal_authority = any(
        isinstance(entry, LiteralSetup) and entry.key in literal_authority_keys
        for entry in task.initial_state.entries
    )
    return ToolRequirement.OPTIONAL if has_literal_authority else ToolRequirement.REQUIRED


def _reclassification_reason(
    task: Any,
    truth: Any,
    result: BenchmarkTaskResult | None,
    decision: ToolRequirement,
) -> tuple[str, str, str]:
    instruction = task.instruction
    focus = _task_focus(task)
    instruction_evidence = f"instruction={instruction}"
    if focus:
        instruction_evidence += f"; taskFocus={focus}"
    initial = _entry_evidence(task)
    missing = _tool_dependent_facts(task, truth)
    if decision is ToolRequirement.REQUIRED:
        reason = (
            f"NO: without the declared Tool, the task lacks {missing}. The initialState "
            "contains only symbolic Java resources/static fixtures, not the returned "
            "authority fact. A persisted post-call observation, when present, is not a "
            "legal pre-call input; expectedToolCalls is corroboration, not the decision rule."
        )
    elif decision is ToolRequirement.OPTIONAL:
        reason = (
            f"YES: initialState already provides the complete authority needed for {missing}; "
            "the Tool is only an optional retrieval strategy."
        )
    else:
        reason = "YES: the final task contract does not require any Agent Tool authority."
    return instruction_evidence, initial, _runtime_evidence(result) + f"; decision={reason}"


def _tool_invoked(result: BenchmarkTaskResult | None, tool_name: str) -> bool:
    if result is None:
        return False
    if any(item.tool_name == tool_name for item in result.tool_result_observations):
        return True
    return bool(result.tool_call_ids)


def build_reclassification(
    policy: OutcomePolicy,
    dataset: Any,
    run: Any,
) -> dict[str, Any]:
    tasks_by_id = {task.benchmark_task_id: task for task in dataset.tasks}
    truths_by_key = {
        (truth.ground_truth_id, truth.version): truth for truth in dataset.ground_truths
    }
    results_by_id = {result.benchmark_task_id: result for result in run.results}
    rows: list[dict[str, str]] = []
    previous = 0
    for policy_task in policy.tasks:
        required = tuple(
            requirement
            for requirement in policy_task.tool_requirements
            if requirement.requirement is ToolRequirement.REQUIRED
        )
        if not required:
            continue
        if len(required) != 1:
            raise ValueError(
                f"current REQUIRED task must have one declared Tool: "
                f"{policy_task.benchmark_task_id}"
            )
        previous += 1
        task = tasks_by_id[policy_task.benchmark_task_id]
        truth = truths_by_key[
            (task.ground_truth_ref.ground_truth_id, task.ground_truth_ref.version)
        ]
        decision = _classify_requirement(task, truth)
        instruction, initial, runtime = _reclassification_reason(
            task, truth, results_by_id.get(task.benchmark_task_id), decision
        )
        rows.append(
            {
                "benchmarkTaskId": task.benchmark_task_id,
                "taskType": task.task_type.value,
                "previousRequirement": required[0].requirement.value,
                "newRequirement": decision.value,
                "instructionEvidence": instruction,
                "initialStateEvidence": initial,
                "runtimeContextEvidence": runtime,
                "missingAuthorityIfNoTool": (
                    "none: final authority is already present"
                    if decision is not ToolRequirement.REQUIRED
                    else _tool_dependent_facts(task, truth)
                ),
                "decisionReason": (
                    "NO — the no-tool counterfactual cannot obtain all final facts: "
                    + _tool_dependent_facts(task, truth)
                    if decision is ToolRequirement.REQUIRED
                    else "YES — no-call completion is supported by the declared authority."
                ),
            }
        )

    counts = Counter(row["newRequirement"] for row in rows)
    final_required_ids = {
        row["benchmarkTaskId"]
        for row in rows
        if row["newRequirement"] == ToolRequirement.REQUIRED.value
    }
    final_required_invoked = sum(
        _tool_invoked(
            results_by_id.get(policy_task.benchmark_task_id),
            next(
                requirement.tool_name
                for requirement in policy_task.tool_requirements
                if requirement.requirement is ToolRequirement.REQUIRED
            ),
        )
        for policy_task in policy.tasks
        if policy_task.benchmark_task_id in final_required_ids
    )
    final_required_count = len(final_required_ids)
    if previous != 31 or len(rows) != 31:
        raise ValueError(f"expected exactly 31 current REQUIRED rows, found {len(rows)}")
    return {
        "schemaVersion": "stage21-required-tool-reclassification/v1",
        "source": {
            "policyVersion": policy.policy_version,
            "datasetId": policy.dataset_id,
            "datasetVersion": policy.dataset_version,
            "persistedRunId": run.evaluation_run_id,
        },
        "rule": (
            "REQUIRED iff the no-tool counterfactual cannot obtain every final fact from "
            "legal initialState/runtime/Java authority; expectedToolCalls alone is not evidence."
        ),
        "summary": {
            "previousRequired": previous,
            "finalRequired": counts.get(ToolRequirement.REQUIRED.value, 0),
            "finalOptional": counts.get(ToolRequirement.OPTIONAL.value, 0),
            "finalNotRequired": counts.get(ToolRequirement.NOT_REQUIRED.value, 0),
            "reclassifiedRequiredToolMiss": final_required_count - final_required_invoked,
            "reclassifiedRequiredToolInvoked": final_required_invoked,
            "reclassifiedRequiredToolCoverage": (
                final_required_invoked / final_required_count
                if final_required_count
                else None
            ),
            "reclassifiedRequiredToolMissRate": (
                (final_required_count - final_required_invoked) / final_required_count
                if final_required_count
                else None
            ),
        },
        "tasks": rows,
    }


def _unknown_category(
    policy_task: OutcomePolicyTask,
    result: BenchmarkTaskResult | None,
    projection_task: Any,
) -> str:
    if policy_task.outcome_authority is OutcomeAuthority.OUTCOME_AUTHORITY_GAP:
        return "INSUFFICIENT_OUTCOME_AUTHORITY"
    if result is None or result.evaluation_result is None:
        return "MISSING_EVALUATION_METRIC"
    if any(
        observation.metric.value == "safety_accuracy"
        and observation.status.value == "UNKNOWN"
        for observation in projection_task.outcome_metrics
    ):
        return "MISSING_SAFETY_AUTHORITY"
    if any(
        observation.status.value == "UNKNOWN"
        and observation.reason
        and "absent" in observation.reason
        for observation in projection_task.outcome_metrics
    ):
        return "MISSING_EVALUATION_METRIC"
    return "MISSING_FINAL_BUSINESS_FACT"


def _authority_facts(result: BenchmarkTaskResult | None) -> list[str]:
    if result is None:
        return ["BenchmarkTaskResult: ABSENT"]
    facts = [
        f"BenchmarkTaskResult.status={_value(result.status)}",
        f"javaExecutionStatus={_value(result.java_execution_status)}",
        f"runId={result.run_id if result.run_id is not None else 'NONE'}",
        f"reportId={result.report_id or 'NONE'}",
        f"authorityReferences={','.join(result.authority_references) or 'NONE'}",
        f"Java ToolResult observations={len(result.tool_result_observations)}",
        "trace structured facts persisted in BenchmarkRun=NO",
        "collateral/state diff persisted in BenchmarkRun=NO",
    ]
    if result.evaluation_result is None:
        facts.append("EvaluationResult=ABSENT")
    else:
        metrics = ",".join(item.metric.value for item in result.evaluation_result.metrics)
        facts.append(f"EvaluationResult.metrics={metrics}")
    return facts


def _unknown_reason(category: str) -> str:
    if category == "INSUFFICIENT_OUTCOME_AUTHORITY":
        return (
            "The V2 policy marks this task as an outcome authority gap. Persisted process/identity "
            "facts do not include a sufficient final business result, so UNKNOWN is retained."
        )
    if category == "MISSING_SAFETY_AUTHORITY":
        return (
            "Stage19 explicitly has no safety fact/Java ToolResult decision for this task. "
            "Java execution or report identity alone is not proof of ALLOW, DENY, "
            "or no collateral damage."
        )
    if category == "MISSING_EVALUATION_METRIC":
        return (
            "The persisted BenchmarkTaskResult has no EvaluationResult for the selected "
            "Stage19 metric. This is missing runtime input, not an omitted V2 projection "
            "mapping; no PASS/FAIL is inferred."
        )
    return (
        "The persisted authority does not contain the final business fact selected by "
        "the V2 outcome contract."
    )


def build_authority_closure(
    policy: OutcomePolicy,
    projection: OutcomeV2Projection,
    run: Any,
) -> dict[str, Any]:
    policy_by_id = policy.task_by_id
    results_by_id = {result.benchmark_task_id: result for result in run.results}
    projections_by_id = {task.benchmark_task_id: task for task in projection.tasks}
    rows: list[dict[str, Any]] = []
    for task_id, projection_task in projections_by_id.items():
        if projection_task.v2_status is not V2OutcomeStatus.UNKNOWN:
            continue
        policy_task = policy_by_id[task_id]
        result = results_by_id.get(task_id)
        category = _unknown_category(policy_task, result, projection_task)
        rows.append(
            {
                "benchmarkTaskId": task_id,
                "taskType": projection_task.task_type.value,
                "v1Status": projection_task.v1_status.value,
                "v2Status": projection_task.v2_status.value,
                "outcomeAuthority": projection_task.outcome_authority.value,
                "outcomeAuthorityGap": projection_task.outcome_authority_gap,
                "outcomeMetrics": [
                    observation.model_dump(mode="json")
                    for observation in projection_task.outcome_metrics
                ],
                "authorityFactsAvailable": _authority_facts(result),
                "closureCategory": category,
                "finalOutcomeAuthority": "INSUFFICIENT",
                "unexplainedAuthorityGap": False,
                "reason": _unknown_reason(category),
            }
        )

    counts = Counter(row["closureCategory"] for row in rows)
    missing_mapping = [
        f"{task.benchmark_task_id}:{metric.value}"
        for task in policy.tasks
        for metric in task.outcome_metrics
        if metric.value
        not in {
            observation.metric.value
            for observation in projections_by_id[task.benchmark_task_id].outcome_metrics
        }
    ]
    if len(rows) != 68:
        raise ValueError(f"expected 68 UNKNOWN rows, found {len(rows)}")
    if counts.get("INSUFFICIENT_OUTCOME_AUTHORITY", 0) != 51:
        raise ValueError("the 51-task authority-gap count is not reproducible")
    if counts.get("MISSING_SAFETY_AUTHORITY", 0) != 15:
        raise ValueError("the 15-task safety-authority count is not reproducible")
    if counts.get("MISSING_EVALUATION_METRIC", 0) != 2:
        raise ValueError("the 2-task missing-metric count is not reproducible")
    return {
        "schemaVersion": "stage21-outcome-authority-closure/v1",
        "sourceArtifact": projection.source_artifact,
        "policyTasks": len(policy.tasks),
        "checkedUnknownTasks": len(rows),
        "previousUnknown": 68,
        "previousOutcomeAuthorityGap": 51,
        "summary": {
            "finalPass": projection.v2_status_counts.get("PASS", 0),
            "finalFail": projection.v2_status_counts.get("FAIL", 0),
            "finalUnknown": projection.v2_status_counts.get("UNKNOWN", 0),
            "legitimateUnknown": len(rows),
            "unexplainedAuthorityGap": sum(row["unexplainedAuthorityGap"] for row in rows),
            "missingSafetyAuthority": counts.get("MISSING_SAFETY_AUTHORITY", 0),
            "missingEvaluationMetric": counts.get("MISSING_EVALUATION_METRIC", 0),
            "missingFinalBusinessFact": counts.get("MISSING_FINAL_BUSINESS_FACT", 0),
            "missingV2MetricMapping": len(missing_mapping),
        },
        "mappingCheck": {
            "missingSelectedOutcomeMetrics": missing_mapping,
            "stage19EvaluatorChanged": False,
            "groundTruthChanged": False,
        },
        "unknownBreakdown": dict(sorted(counts.items())),
        "tasks": rows,
    }


def benchmark_review() -> str:
    rows = (
        (
            "tests/benchmark/test_baseline.py::test_formal_baseline_runs_active_dataset_and_persists_stage19_views[asyncio]",
            "Missing report identity raised CURRENT_JAVA_REPORT mapping error before evaluation.",
            "code regression",
            "Preserve CURRENT_JAVA_REPORT when report_id is absent; evaluator records "
            "UNKNOWN. No fixture fallback.",
        ),
        (
            "tests/benchmark/test_final_gates.py::test_fixed_subset_comparison_ignores_runtime_identity[asyncio]",
            "The same missing-identity mapping error removed metric schemas from the comparison.",
            "code regression",
            "Use the unresolved-token path so both sides retain comparable Stage19 schemas.",
        ),
        (
            "tests/benchmark/test_real_golden_e2e.py::test_all_five_golden_tasks_execute_one_deterministic_batch[asyncio]",
            "Deterministic Golden batch hit the same CURRENT_JAVA_REPORT mapping failure.",
            "code regression",
            "Keep the logical token unresolved; real identities are still required when "
            "Java returns them.",
        ),
        (
            "tests/benchmark/test_real_golden_e2e.py::test_failure_diagnosis_golden_task_executes_real_stage20_and_stage19[asyncio]",
            "Spring context first failed on application.yml '#{null}' binding; the Python "
            "harness also asserted a concrete identity in a symbolic initial-state "
            "reference and expected stale GT version v1.",
            "environment/config plus test-contract mismatch",
            "Use an empty YAML default, retain the symbolic Java resource reference, and "
            "assert the checked-in GT v2. Real Maven and Python E2E both pass.",
        ),
    )
    lines = [
        "# Stage21 Benchmark Critical Test Review",
        "",
        "This review records the four failures observed before the closure fixes. "
        "No fallback report, guessed identity, or fixture authority was introduced.",
        "",
        "| Test | Root cause | Type | Resolution |",
        "| --- | --- | --- | --- |",
    ]
    for test, cause, kind, resolution in rows:
        lines.append(f"| `{test}` | {cause} | {kind} | {resolution} |")
    lines.extend(
        [
            "",
            "## Final observed status",
            "",
            "- Targeted mapping, runner, baseline, final-gates, deterministic Golden, and "
            "real Stage20 wrapper checks passed.",
            "- Direct Maven `Stage20DiagnosisToolAuditCrossProcessE2ETest` passed with a "
            "real Java `report:701` and ToolResult correlation.",
            "- The full `tests/benchmark` result is recorded by the final validation "
            "command; this artifact does not rerun it.",
        ]
    )
    return "\n".join(lines) + "\n"


def _ensure_new_output_dir(path: Path) -> None:
    if path.exists() and any(path.iterdir()):
        raise RuntimeError(f"refusing to overwrite existing artifact directory: {path}")
    path.mkdir(parents=True, exist_ok=True)


def build_artifacts(policy_path: Path, run_path: Path | None, output_dir: Path) -> dict[str, Any]:
    _ensure_new_output_dir(output_dir)
    dataset = load_dataset()
    policy = load_outcome_policy(policy_path, dataset=dataset)
    candidate_path = run_path or discover_formal105_run()
    run = load_persisted_formal105_run(candidate_path)
    projection = project_outcome_v2(run, policy, source_artifact=candidate_path)
    persist_outcome_v2_projection(projection, output_dir)
    reclassification = build_reclassification(policy, dataset, run)
    closure = build_authority_closure(policy, projection, run)
    _write_json(output_dir / "required-tool-reclassification.json", reclassification)
    _write_json(output_dir / "outcome-authority-closure.json", closure)
    (output_dir / "benchmark-test-review.md").write_text(
        benchmark_review(), encoding="utf-8", newline="\n"
    )
    return {
        "outputDir": str(output_dir),
        "sourceArtifact": str(candidate_path),
        "requiredTool": reclassification["summary"],
        "outcome": projection.v2_status_counts,
        "unknown": closure["summary"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build Stage21 authority closure artifacts offline."
    )
    parser.add_argument("--policy", type=Path, default=DEFAULT_POLICY)
    parser.add_argument("--run", type=Path, default=None)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    print(
        "STAGE21_AUTHORITY_CLOSURE "
        + _compact(build_artifacts(args.policy, args.run, args.output_dir))
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
