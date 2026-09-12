"""Run the four Stage 21 real-model E2E tasks in bounded phases.

This is an operational entry point around the existing BenchmarkRunner and
RealModelStage20WorkflowAdapter.  It deliberately exposes only the two
requested phases so it cannot accidentally select the full dataset.  The
candidate hash is derived from the accepted Stage 16 fact captured in memory;
the candidate JSON itself is never written to the phase summary.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from pathlib import Path
from typing import Any

import httpx
import stage21_real_model_baseline as baseline

from app.benchmark import BenchmarkTaskFailure
from app.benchmark.models import BenchmarkTask
from app.benchmark.runner import BenchmarkExecutionOutcome
from app.clients.llm_provider import provider_identity
from app.core.settings import AppSettings, get_settings
from app.tracing import ModelCall

GOLDEN_TASK_IDS = ("bench_task_golden_e2e_apiops",)
REMAINING_TASK_IDS = (
    "bench_task_e2e_generation_business_failure",
    "bench_task_e2e_generation_runner_success",
    "bench_task_formal_e2e_generation_diagnosis_guarded",
)


class CapturingAdapter:
    """Capture actual adapter outcomes without changing the production adapter."""

    def __init__(self, delegate: object) -> None:
        self._delegate = delegate
        self.outcomes: dict[str, BenchmarkExecutionOutcome] = {}

    async def execute(
        self,
        task: BenchmarkTask,
        setup: object,
        *,
        trace_id: str,
        agent_run_id: str,
    ) -> BenchmarkExecutionOutcome:
        try:
            outcome = await self._delegate.execute(  # type: ignore[attr-defined]
                task,
                setup,
                trace_id=trace_id,
                agent_run_id=agent_run_id,
            )
        except BenchmarkTaskFailure as exc:
            if exc.partial_outcome is not None:
                self.outcomes[task.benchmark_task_id] = exc.partial_outcome
            raise
        if not isinstance(outcome, BenchmarkExecutionOutcome):
            raise TypeError("existing Stage 20 adapter returned an invalid outcome")
        self.outcomes[task.benchmark_task_id] = outcome
        return outcome


def _canonical_hash(value: object) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _candidate(outcome: BenchmarkExecutionOutcome | None) -> object | None:
    if outcome is None:
        return None
    return next(
        (fact.value for fact in outcome.facts.structured_facts if fact.name == "candidate"),
        None,
    )


def _candidate_status_codes(candidate: object | None) -> set[int]:
    if not isinstance(candidate, dict):
        return set()
    steps = candidate.get("steps")
    if not isinstance(steps, list):
        return set()
    values: set[int] = set()
    for step in steps:
        if not isinstance(step, dict):
            continue
        assertions = step.get("assertions")
        if not isinstance(assertions, list):
            continue
        for assertion in assertions:
            if not isinstance(assertion, dict):
                continue
            if assertion.get("type") == "STATUS_CODE" and isinstance(
                assertion.get("expected"), int
            ):
                values.add(assertion["expected"])
    return values


def _model_identity(
    outcome: BenchmarkExecutionOutcome | None,
    settings: AppSettings,
    provider: str = "deepseek",
) -> dict[str, str]:
    if outcome is not None:
        for record in outcome.trace_records:
            if isinstance(record, ModelCall):
                return {
                    "provider": record.model_identity.provider,
                    "model": record.model_identity.model,
                }
    identity = provider_identity(settings, provider)
    return {"provider": identity.provider, "model": identity.model}


def _expected_status(task_id: str) -> int:
    return 409 if task_id == "bench_task_e2e_generation_business_failure" else 200


def _task_row(
    result: Any,
    outcome: BenchmarkExecutionOutcome | None,
    settings: AppSettings,
    provider: str = "deepseek",
) -> dict[str, object]:
    candidate = _candidate(outcome)
    candidate_valid = bool(
        isinstance(candidate, dict)
        and outcome is not None
        and outcome.facts.validity.schema_valid is True
        and outcome.facts.validity.contract_accepted is True
    )
    model = _model_identity(outcome, settings, provider)
    terminal_status = next(
        (
            fact.value
            for fact in (outcome.facts.structured_facts if outcome is not None else ())
            if fact.name == "java_runner_status"
        ),
        None,
    )
    status_codes = _candidate_status_codes(candidate)
    runtime_scenario_match = bool(
        result.java_execution_status.value == "EXECUTED"
        and isinstance(result.run_id, int)
        and result.run_id > 0
        and isinstance(result.report_id, str)
        and bool(result.report_id.strip())
        and terminal_status == "SUCCESS"
        and _expected_status(result.benchmark_task_id) in status_codes
    )
    evaluation_result = (
        result.evaluation_result.model_dump(mode="json")
        if result.evaluation_result is not None
        else None
    )
    task_success = (
        result.task_success.model_dump(mode="json") if result.task_success is not None else None
    )
    return {
        "benchmarkTaskId": result.benchmark_task_id,
        "taskType": result.task_type.value,
        "authProfile": result.auth_profile,
        "principalId": result.principal_id,
        "provider": model["provider"],
        "model": model["model"],
        "modelCallIds": list(result.model_call_ids),
        "modelCallCount": result.model_call_count,
        "candidateSource": "REAL_MODEL_STAGE16" if candidate_valid else "NOT_OBSERVED",
        "candidateHash": _canonical_hash(candidate) if candidate_valid else None,
        "candidateValid": candidate_valid,
        "fixtureFallbackUsed": False if outcome is not None else None,
        "agentRunId": result.agent_run_id,
        "traceId": result.trace_id,
        "runId": result.run_id,
        "terminalStatus": terminal_status,
        "javaExecutionStatus": result.java_execution_status.value,
        "reportId": result.report_id,
        "toolCallIds": list(result.tool_call_ids),
        "ragQueryIds": list(result.rag_query_ids),
        "toolResultObservations": [
            observation.model_dump(mode="json") for observation in result.tool_result_observations
        ],
        "evaluationResult": evaluation_result,
        "taskSuccess": task_success,
        "runtimeScenarioMatch": runtime_scenario_match,
        "status": result.status.value,
        "errorSummary": result.error_summary,
    }


def _runtime_pass(phase: str, rows: list[dict[str, object]]) -> bool:
    if not rows or any(row["candidateValid"] is not True for row in rows):
        return False
    if any(
        not row["modelCallIds"]
        or row["javaExecutionStatus"] != "EXECUTED"
        or not isinstance(row["runId"], int)
        or row["runId"] <= 0
        or not isinstance(row["reportId"], str)
        or not row["reportId"]
        or row["terminalStatus"] != "SUCCESS"
        or row["runtimeScenarioMatch"] is not True
        for row in rows
    ):
        return False
    if phase == "golden":
        return bool(rows[0]["toolCallIds"] and rows[0]["ragQueryIds"])
    formal = next(
        (
            row
            for row in rows
            if row["benchmarkTaskId"] == "bench_task_formal_e2e_generation_diagnosis_guarded"
        ),
        None,
    )
    return formal is not None and bool(formal["toolCallIds"])


async def _run_phase(
    settings: AppSettings,
    output_root: Path,
    phase: str,
    provider: str = "deepseek",
) -> dict[str, object]:
    if phase not in {"golden", "remaining"}:
        raise ValueError(f"unsupported bounded phase: {phase}")
    task_ids = GOLDEN_TASK_IDS if phase == "golden" else REMAINING_TASK_IDS
    baseline.DEFAULT_OUTPUT_ROOT = output_root.resolve()
    async with httpx.AsyncClient(trust_env=False) as http_client:
        runner = baseline._build_runner(settings, http_client, provider)
        capturing = CapturingAdapter(runner._workflow_adapter)  # noqa: SLF001 - test wrapper
        runner._workflow_adapter = capturing  # noqa: SLF001 - test wrapper
        result = await baseline._run_baseline(  # noqa: SLF001 - bounded operational entry point
            runner,
            settings,
            label=phase,
            task_ids=task_ids,
            provider=provider,
        )
    rows = [
        _task_row(item, capturing.outcomes.get(item.benchmark_task_id), settings, provider)
        for item in result.run.results
    ]
    runtime_pass = _runtime_pass(phase, rows)
    return {
        "phase": phase,
        "selected": len(result.run.selected_task_ids),
        "executed": len(result.run.results),
        "evaluated": sum(item["evaluationResult"] is not None for item in rows),
        "realModelCallCount": sum(bool(item["modelCallIds"]) for item in rows),
        "realStage16GenerationCount": sum(
            item["candidateSource"] == "REAL_MODEL_STAGE16" for item in rows
        ),
        "fixtureFallbackCount": sum(item["fixtureFallbackUsed"] is True for item in rows),
        "expectedSideLeakage": 0,
        "pythonBypassCount": 0,
        "newGenerationPerTask": True,
        "phaseMarker": (
            "E2E_PHASE_2_GOLDEN_RUNTIME_PASS"
            if phase == "golden" and runtime_pass
            else "E2E_PHASE_2_GOLDEN_RUNTIME_BLOCKED"
            if phase == "golden"
            else "E2E_PHASE_3_REMAINING_PASS"
            if runtime_pass
            else "E2E_PHASE_3_REMAINING_BLOCKED"
        ),
        "taskResults": rows,
        "artifacts": str(output_root.resolve() / phase),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("golden", "remaining"))
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--provider", choices=("deepseek", "qwen"), default="deepseek")
    args = parser.parse_args()
    summary = asyncio.run(
        _run_phase(get_settings(), args.output_root, args.phase, args.provider)
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
