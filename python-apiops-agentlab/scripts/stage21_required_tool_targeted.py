"""Run the 31 V2 REQUIRED-tool tasks through the existing real runner.

This is an operational wrapper around ``BenchmarkRunner``.  It selects only
the REQUIRED tasks from the frozen V2 policy, captures typed trace facts from
the existing workflow, and writes redaction-safe task summaries.  It does not
create a runner, inject tool results, or retain model payloads.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

import httpx
import stage21_real_model_baseline as baseline

from app.benchmark.dataset import BenchmarkDataset, load_dataset
from app.benchmark.outcome_v2 import (
    OutcomePolicy,
    OutcomePolicyTask,
    _task_projection,
    load_outcome_policy,
)
from app.benchmark.runner import (
    BenchmarkExecutionOutcome,
    BenchmarkProgress,
    BenchmarkResultStore,
    BenchmarkTaskFailure,
    BenchmarkTaskResult,
    JsonBenchmarkResultStore,
)
from app.core.settings import AppSettings, get_settings
from app.tracing import RetrievalFact, ToolIntentRecord, ToolResultRecord

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
MANIFEST_PATH = (
    REPOSITORY_ROOT
    / "python-apiops-agentlab/tests/benchmark/fixtures/dataset-manifest.json"
)
POLICY_PATH = (
    REPOSITORY_ROOT
    / "python-apiops-agentlab/tests/benchmark/fixtures/stage21-outcome-policy-v2.json"
)
DEFAULT_OUTPUT_ROOT = REPOSITORY_ROOT / "artifacts/stage21/v2-required-tool-targeted"
REQUIRED_COUNT = 31

EXPECTED_DENY_OUTCOMES = frozenset(
    {
        "JAVA_DENIED",
        "FORBIDDEN_INTENT_DENIED",
        "HUMAN_REJECTED",
        "APPROVAL_BYPASS_BLOCKED",
    }
)


class CapturingAdapter:
    """Observe the existing adapter outcomes without changing its behavior."""

    def __init__(self, delegate: object) -> None:
        self._delegate = delegate
        self.outcomes: dict[str, BenchmarkExecutionOutcome] = {}

    async def execute(
        self,
        task: object,
        setup: object,
        *,
        trace_id: str,
        agent_run_id: str,
    ) -> BenchmarkExecutionOutcome:
        task_id = task.benchmark_task_id
        try:
            outcome = await self._delegate.execute(  # type: ignore[attr-defined]
                task,
                setup,
                trace_id=trace_id,
                agent_run_id=agent_run_id,
            )
        except BenchmarkTaskFailure as exc:
            if exc.partial_outcome is not None:
                self.outcomes[task_id] = exc.partial_outcome
            raise
        if not isinstance(outcome, BenchmarkExecutionOutcome):
            raise TypeError("existing Stage 20 adapter returned an invalid outcome")
        self.outcomes[task_id] = outcome
        return outcome


class SummaryStore(BenchmarkResultStore):
    """Persist normal runner artifacts and the task summary beside them."""

    def __init__(
        self,
        root: Path,
        summaries: Path,
        capture: CapturingAdapter,
        policy: dict[str, OutcomePolicyTask],
        expected_security_denies: dict[str, bool],
    ) -> None:
        self._delegate = JsonBenchmarkResultStore(root)
        self._summaries = summaries
        self._capture = capture
        self._policy = policy
        self._expected_security_denies = expected_security_denies

    def persist_task(self, result: BenchmarkTaskResult) -> Path:
        self._delegate.persist_task(result)
        path = self._summaries / f"{result.benchmark_task_id}.json"
        _write_json(
            path,
            _task_summary(
                result,
                self._capture.outcomes.get(result.benchmark_task_id),
                policy_task=self._policy[result.benchmark_task_id],
                expected_security_deny=self._expected_security_denies[result.benchmark_task_id],
            ),
        )
        return path

    def persist_run(self, run: object) -> Path:
        return self._delegate.persist_run(run)


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _digest_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _value(value: object) -> object:
    return getattr(value, "value", value)


def _non_null(target: dict[str, object], key: str, value: object) -> None:
    if value is not None:
        target[key] = value


def _required_tasks(policy: OutcomePolicy) -> tuple[OutcomePolicyTask, ...]:
    selected = tuple(
        task
        for task in policy.tasks
        if any(item.requirement.value == "REQUIRED" for item in task.tool_requirements)
    )
    if len(selected) != REQUIRED_COUNT:
        raise RuntimeError(
            f"V2 policy contains {len(selected)} REQUIRED tasks, expected {REQUIRED_COUNT}"
        )
    if any(
        len(tuple(item for item in task.tool_requirements if item.requirement.value == "REQUIRED"))
        != 1
        for task in selected
    ):
        raise RuntimeError("targeted REQUIRED task must declare exactly one REQUIRED tool")
    return selected


def _ground_truth_by_task(dataset: BenchmarkDataset) -> dict[str, object]:
    truths = {(item.ground_truth_id, item.version): item for item in dataset.ground_truths}
    return {
        task.benchmark_task_id: truths[
            (task.ground_truth_ref.ground_truth_id, task.ground_truth_ref.version)
        ]
        for task in dataset.tasks
    }


def _tool_intents(
    outcome: BenchmarkExecutionOutcome | None,
    required_tool: str,
) -> tuple[ToolIntentRecord, ...]:
    if outcome is None:
        return ()
    return tuple(
        record
        for record in outcome.trace_records
        if isinstance(record, ToolIntentRecord) and record.tool_name == required_tool
    )


def _tool_results(outcome: BenchmarkExecutionOutcome | None) -> tuple[ToolResultRecord, ...]:
    if outcome is None:
        return ()
    return tuple(record for record in outcome.trace_records if isinstance(record, ToolResultRecord))


def _tool_result_status(
    result: BenchmarkTaskResult,
    records: tuple[ToolResultRecord, ...],
) -> str | None:
    for record in records:
        if record.tool_result_status is not None:
            return str(record.tool_result_status)
        if str(_value(record.status)) == "DENIED":
            return "FORBIDDEN"
    for observation in result.tool_result_observations:
        return str(_value(observation.status))
    return None


def _java_tool_call_id(
    result: BenchmarkTaskResult,
    records: tuple[ToolResultRecord, ...],
) -> str | None:
    for record in records:
        if record.java_tool_call_id:
            return record.java_tool_call_id
    return result.tool_call_ids[0] if result.tool_call_ids else None


def _rag_query_id(
    result: BenchmarkTaskResult,
    outcome: BenchmarkExecutionOutcome | None,
) -> str | None:
    if result.rag_query_ids:
        return result.rag_query_ids[0]
    if outcome is not None:
        for record in outcome.trace_records:
            if isinstance(record, RetrievalFact) and record.reference.rag_query_id:
                return record.reference.rag_query_id
    return None


def _result_count(
    result: BenchmarkTaskResult,
    outcome: BenchmarkExecutionOutcome | None,
) -> int | None:
    for observation in result.tool_result_observations:
        if observation.result_count is not None:
            return observation.result_count
    if outcome is not None:
        for record in outcome.trace_records:
            if isinstance(record, RetrievalFact) and record.result_count is not None:
                return record.result_count
    return None


def _is_model_failure(result: BenchmarkTaskResult) -> bool:
    text = " ".join(
        str(value or "")
        for value in (result.failure_code, result.failure_category, result.error_summary)
    ).upper()
    return any(
        marker in text for marker in ("MODEL", "PROVIDER", "DEEPSEEK", "STRUCTURED_OUTPUT")
    )


def _is_runtime_failure(result: BenchmarkTaskResult) -> bool:
    java_status = str(_value(result.java_execution_status))
    category = str(result.failure_category or "").upper()
    code = str(result.failure_code or "").upper()
    if java_status in {"REQUIRED_BUT_UNAVAILABLE", "EXECUTION_FAILED"}:
        return True
    if category in {"INFRASTRUCTURE_FAILURE", "SETUP_FAILURE", "TIMEOUT"}:
        return True
    return any(marker in f"{code} {category}" for marker in ("JAVA_", "AUTH", "GATEWAY", "RUNTIME"))


def _classify(
    result: BenchmarkTaskResult,
    outcome: BenchmarkExecutionOutcome | None,
    *,
    required_tool: str,
    expected_security_deny: bool,
) -> tuple[str, bool, bool, str | None, tuple[ToolResultRecord, ...]]:
    intents = _tool_intents(outcome, required_tool)
    records = _tool_results(outcome)
    status = _tool_result_status(result, records)
    java_invoked = _java_tool_call_id(result, records) is not None
    if intents and java_invoked and status == "SUCCESS":
        return "CALLED_SUCCESS", True, True, status, records
    if intents and java_invoked and status == "FORBIDDEN" and expected_security_deny:
        return "CALLED_EXPECTED_DENY", True, True, status, records
    if intents and _is_runtime_failure(result):
        return "RUNTIME_FAILURE", True, java_invoked, status, records
    if intents:
        return "CALLED_TOOL_FAILURE", True, java_invoked, status, records
    if _is_model_failure(result):
        return "MODEL_FAILURE", False, java_invoked, status, records
    if _is_runtime_failure(result):
        return "RUNTIME_FAILURE", False, java_invoked, status, records
    return "NOT_CALLED_REQUIRED_MISS", False, java_invoked, status, records


def _task_summary(
    result: BenchmarkTaskResult,
    outcome: BenchmarkExecutionOutcome | None,
    *,
    policy_task: OutcomePolicyTask,
    expected_security_deny: bool = False,
) -> dict[str, object]:
    required_tool = next(
        item.tool_name
        for item in policy_task.tool_requirements
        if item.requirement.value == "REQUIRED"
    )
    classification, intent_observed, java_invoked, result_status, records = _classify(
        result,
        outcome,
        required_tool=required_tool,
        expected_security_deny=expected_security_deny,
    )
    projection = _task_projection(policy_task, result)
    intents = _tool_intents(outcome, required_tool)
    tool_call_id = _java_tool_call_id(result, records)
    row: dict[str, object] = {
        "benchmarkTaskId": result.benchmark_task_id,
        "taskType": result.task_type.value,
        "requiredTools": [required_tool],
        "runtimeStatus": result.status.value,
        "javaExecutionStatus": result.java_execution_status.value,
        "modelCallCount": result.model_call_count,
        "toolIntentObserved": intent_observed,
        "javaToolInvocationObserved": java_invoked,
        "expectedSecurityDeny": expected_security_deny,
        "requiredToolMiss": classification == "NOT_CALLED_REQUIRED_MISS",
        "failureClassification": classification,
    }
    _non_null(row, "toolName", intents[0].tool_name if intents else None)
    _non_null(row, "toolCallId", tool_call_id)
    _non_null(row, "toolResultStatus", result_status)
    _non_null(row, "ragQueryId", _rag_query_id(result, outcome))
    _non_null(row, "resultCount", _result_count(result, outcome))
    _non_null(row, "failureCode", result.failure_code)
    _non_null(row, "failureCategory", result.failure_category)
    _non_null(row, "errorSummary", result.error_summary)
    _non_null(row, "v2Outcome", projection.v2_status.value)
    if projection.tool_requirements:
        row["requiredToolInvoked"] = projection.tool_requirements[0].invoked
    if result.model_call_ids:
        row["modelCallIds"] = list(result.model_call_ids)
    return row


def _manifest(
    settings: AppSettings,
    policy: OutcomePolicy,
    required: tuple[OutcomePolicyTask, ...],
    evaluation_run_id: str,
    *,
    status: str,
    started_at: str,
    finished_at: str | None = None,
    executed: int | None = None,
) -> dict[str, object]:
    names = (
        "DEEPSEEK_API_KEY",
        "ZHIPU_API_KEY",
        "STAGE21_NORMAL_USERNAME",
        "STAGE21_NORMAL_PASSWORD",
        "STAGE21_SAFETY41_USERNAME",
        "STAGE21_SAFETY41_PASSWORD",
        "STAGE21_SAFETY42_USERNAME",
        "STAGE21_SAFETY42_PASSWORD",
        "JAVA_APIOPS_BASE_URL",
    )
    return {
        "schemaVersion": "stage21-required-tool-targeted/v1",
        "status": status,
        "evaluationRunId": evaluation_run_id,
        "datasetId": policy.dataset_id,
        "datasetVersion": policy.dataset_version,
        "taskSchemaVersion": policy.task_schema_version,
        "policyVersion": policy.policy_version,
        "policyDigest": _digest_file(POLICY_PATH),
        "selected": len(required),
        "executed": executed if executed is not None else 0,
        "taskIds": [task.benchmark_task_id for task in required],
        "taskSplits": {task.benchmark_task_id: task.split.value for task in required},
        "model": {"provider": "DeepSeek", "model": settings.deepseek_model},
        "modelParameters": {
            "responseFormat": "json_object",
            "thinking": "disabled",
            "stream": False,
            "timeoutSeconds": settings.deepseek_timeout_seconds,
        },
        "workflow": {
            "name": "RealModelStage20WorkflowAdapter",
            "version": baseline.WORKFLOW_VERSION,
        },
        "toolCatalog": {"name": "ToolCatalog", "version": baseline.TOOL_CATALOG_VERSION},
        "stage19Evaluator": {"name": "RuleBasedEvaluator"},
        "environmentReadiness": {
            name: bool(os.environ.get(name, "").strip()) for name in names
        },
        "startedAt": started_at,
        **({"finishedAt": finished_at} if finished_at is not None else {}),
    }


def _summary_markdown(summary: dict[str, object], rows: list[dict[str, object]]) -> str:
    counts = summary["classificationCounts"]
    lines = [
        "# Stage21 V2 REQUIRED-tool targeted run",
        "",
        (
            "This artifact records the existing real Agent/Java workflow. "
            "Model payloads and secrets are not persisted."
        ),
        "",
        f"- Selected: `{summary['selected']}`",
        f"- Executed: `{summary['executed']}`",
        f"- Required Tool Invoked: `{summary['requiredToolInvoked']}`",
        f"- Required Tool Miss: `{summary['requiredToolMiss']}`",
        f"- Required Tool Coverage: `{summary['requiredToolCoverage']:.4f}`",
        f"- Required Tool Miss Rate: `{summary['requiredToolMissRate']:.4f}`",
        "",
        "## Classification",
        "",
    ]
    for name in (
        "CALLED_SUCCESS",
        "CALLED_EXPECTED_DENY",
        "CALLED_TOOL_FAILURE",
        "NOT_CALLED_REQUIRED_MISS",
        "MODEL_FAILURE",
        "RUNTIME_FAILURE",
    ):
        lines.append(f"- {name}: `{counts.get(name, 0)}`")
    lines.extend(
        (
            "",
            "## Tasks",
            "",
            "| Task | Type | Intent | Java | Result | Classification |",
            "| --- | --- | ---: | ---: | --- | --- |",
        )
    )
    for row in rows:
        values = dict(row)
        values.setdefault("toolResultStatus", "UNAVAILABLE")
        lines.append(
            (
                "| {benchmarkTaskId} | {taskType} | {toolIntentObserved} | "
                "{javaToolInvocationObserved} | {toolResultStatus} | "
                "{failureClassification} |"
            ).format(**values)
        )
    return "\n".join(lines) + "\n"


def _build_summary(
    rows: list[dict[str, object]],
    *,
    evaluation_run_id: str,
    raw_root: Path,
    summaries_dir: Path,
) -> dict[str, object]:
    counts = Counter(str(row["failureClassification"]) for row in rows)
    invoked = sum(bool(row.get("requiredToolInvoked")) for row in rows)
    misses = sum(row["failureClassification"] == "NOT_CALLED_REQUIRED_MISS" for row in rows)
    selected = len(rows)
    return {
        "schemaVersion": "stage21-required-tool-targeted-summary/v1",
        "evaluationRunId": evaluation_run_id,
        "selected": selected,
        "executed": selected,
        "classificationCounts": dict(sorted(counts.items())),
        "requiredToolInvoked": invoked,
        "requiredToolMiss": misses,
        "requiredToolCoverage": invoked / selected if selected else 0.0,
        "requiredToolMissRate": misses / selected if selected else 0.0,
        "toolIntentObserved": sum(bool(row["toolIntentObserved"]) for row in rows),
        "javaToolInvocationObserved": sum(
            bool(row["javaToolInvocationObserved"]) for row in rows
        ),
        "taskResults": [row["benchmarkTaskId"] for row in rows],
        "artifacts": {
            "runnerResults": str(raw_root.resolve()),
            "taskResults": str(summaries_dir.resolve()),
        },
    }


def _finalize_existing(output_root: Path) -> int:
    manifest_path = output_root / "run-manifest.json"
    summaries_dir = output_root / "task-results"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    dataset = load_dataset(MANIFEST_PATH)
    policy = load_outcome_policy(POLICY_PATH, dataset=dataset)
    required = _required_tasks(policy)
    expected_ids = {task.benchmark_task_id for task in required}
    files = tuple(summaries_dir.glob("*.json"))
    if {path.stem for path in files} != expected_ids:
        raise RuntimeError("existing targeted task summaries do not match the 31 REQUIRED tasks")
    rows = [
        json.loads((summaries_dir / f"{task_id}.json").read_text(encoding="utf-8"))
        for task_id in manifest["taskIds"]
    ]
    if any(row.get("benchmarkTaskId") not in expected_ids for row in rows):
        raise RuntimeError("existing targeted task summary contains an unknown task ID")
    summary = _build_summary(
        rows,
        evaluation_run_id=str(manifest["evaluationRunId"]),
        raw_root=output_root / "runner-results",
        summaries_dir=summaries_dir,
    )
    _write_json(output_root / "required-tool-summary.json", summary)
    (output_root / "required-tool-summary.md").write_text(
        _summary_markdown(summary, rows), encoding="utf-8", newline="\n"
    )
    manifest["status"] = "COMPLETED"
    manifest["executed"] = len(rows)
    manifest["finishedAt"] = _now()
    _write_json(manifest_path, manifest)
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


async def _run(settings: AppSettings, output_root: Path) -> int:
    if output_root.exists():
        raise RuntimeError(f"target artifact directory already exists: {output_root}")
    dataset = load_dataset(MANIFEST_PATH)
    policy = load_outcome_policy(POLICY_PATH, dataset=dataset)
    required = _required_tasks(policy)
    task_ids = tuple(task.benchmark_task_id for task in required)
    truths = _ground_truth_by_task(dataset)
    if set(task_ids) != {
        task.benchmark_task_id
        for task in dataset.tasks
        if task.benchmark_task_id in set(task_ids)
    }:
        raise RuntimeError("required task selection is inconsistent with the dataset")

    output_root.mkdir(parents=True, exist_ok=False)
    summaries_dir = output_root / "task-results"
    raw_root = output_root / "runner-results"
    started_at = _now()
    evaluation_run_id = (
        "evaluation_run:stage21-required-tool-targeted-"
        f"{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}"
    )
    _write_json(
        output_root / "run-manifest.json",
        _manifest(
            settings,
            policy,
            required,
            evaluation_run_id,
            status="RUNNING",
            started_at=started_at,
        ),
    )

    async with httpx.AsyncClient(trust_env=False) as http_client:
        runner = baseline._build_runner(settings, http_client)
        capturing = CapturingAdapter(  # noqa: SLF001 - observation wrapper
            runner._workflow_adapter
        )
        runner._workflow_adapter = capturing  # noqa: SLF001 - observation wrapper
        expected_security_denies = {
            task.benchmark_task_id: str(
                _value(truths[task.benchmark_task_id].expected_safety_outcome)
            )
            in EXPECTED_DENY_OUTCOMES
            for task in required
        }
        store = SummaryStore(
            raw_root,
            summaries_dir,
            capturing,
            policy.task_by_id,
            expected_security_denies,
        )

        def on_progress(progress: BenchmarkProgress) -> None:
            print(
                json.dumps(
                    {
                        "progress": f"{progress.current}/{progress.total}",
                        "benchmarkTaskId": progress.benchmark_task_id,
                        "status": progress.status.value,
                    },
                    ensure_ascii=False,
                ),
                flush=True,
            )

        run = await runner.run_dataset(
            MANIFEST_PATH,
            evaluation_run_id=evaluation_run_id,
            task_ids=task_ids,
            result_store=store,
            on_progress=on_progress,
        )

    rows = [
        _task_summary(
            result,
            capturing.outcomes.get(result.benchmark_task_id),
            policy_task=policy.task_by_id[result.benchmark_task_id],
            expected_security_deny=(
                str(_value(truths[result.benchmark_task_id].expected_safety_outcome))
                in EXPECTED_DENY_OUTCOMES
            ),
        )
        for result in run.results
    ]
    for row in rows:
        _write_json(summaries_dir / f"{row['benchmarkTaskId']}.json", row)
    summary = _build_summary(
        rows,
        evaluation_run_id=evaluation_run_id,
        raw_root=raw_root,
        summaries_dir=summaries_dir,
    )
    _write_json(output_root / "required-tool-summary.json", summary)
    (output_root / "required-tool-summary.md").write_text(
        _summary_markdown(summary, rows), encoding="utf-8", newline="\n"
    )
    _write_json(
        output_root / "run-manifest.json",
        _manifest(
            settings,
            policy,
            required,
            evaluation_run_id,
            status="COMPLETED",
            started_at=started_at,
            finished_at=_now(),
            executed=len(run.results),
        ),
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if len(run.results) == len(task_ids) else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument(
        "--finalize-existing",
        action="store_true",
        help="finish summaries for a completed run whose final report write was interrupted",
    )
    args = parser.parse_args()
    output_root = args.output_root.resolve()
    if args.finalize_existing:
        return _finalize_existing(output_root)
    return asyncio.run(_run(get_settings(), output_root))


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # noqa: BLE001 - stable operational failure
        print(json.dumps({"status": "TARGETED_RUN_BLOCKED", "error": str(exc)}, ensure_ascii=False))
        raise SystemExit(1)
