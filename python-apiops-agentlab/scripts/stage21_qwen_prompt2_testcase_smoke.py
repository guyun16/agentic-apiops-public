"""Run bounded Qwen TestCase positive and intentional-invalid real-model smokes."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
from collections.abc import Mapping
from pathlib import Path

import httpx
from pydantic import SecretStr

from app.benchmark import RealModelStage20WorkflowAdapter, StaticFixtureAdapter
from app.benchmark.models import BenchmarkTask
from app.clients.llm_provider import build_llm
from app.clients.qwen_structured_output import (
    TESTCASE_CANDIDATE_OUTPUT_SPEC,
    TESTCASE_CANDIDATE_SCHEMA_NAME,
    schema_digest,
)
from app.core.settings import AppSettings
from app.evaluator import EvaluationFacts
from app.tracing import ModelCall

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
POSITIVE_TASK = (
    REPOSITORY_ROOT
    / "python-apiops-agentlab"
    / "tests"
    / "benchmark"
    / "fixtures"
    / "formal"
    / "tasks"
    / "bench_task_formal_testcase_happy_create_order_contract.json"
)
INVALID_TASK = (
    REPOSITORY_ROOT
    / "python-apiops-agentlab"
    / "tests"
    / "benchmark"
    / "fixtures"
    / "formal"
    / "tasks"
    / "bench_task_formal_testcase_invalid_http_method.json"
)


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _load_task(path: Path) -> BenchmarkTask:
    return BenchmarkTask.model_validate_json(path.read_text(encoding="utf-8"))


def _fact(facts: EvaluationFacts, name: str) -> object | None:
    return next(
        (item.value for item in facts.structured_facts if item.name == name),
        None,
    )


def _candidate_details(facts: EvaluationFacts) -> dict[str, object]:
    candidate = _fact(facts, "candidate")
    requests = (
        [
            step.get("request")
            for step in candidate.get("steps", [])
            if isinstance(step, dict) and isinstance(step.get("request"), dict)
        ]
        if isinstance(candidate, dict) and isinstance(candidate.get("steps"), list)
        else []
    )
    return {
        "candidateObjectObserved": isinstance(candidate, dict),
        "candidateDigest": _digest(candidate) if isinstance(candidate, dict) else None,
        "intendedExtraFieldObserved": (isinstance(candidate, dict) and "agentThought" in candidate),
        "intendedInvalidMethodObserved": any(
            request.get("method") == "CREATE" for request in requests
        ),
    }


def _native_trace_details(outcome: object) -> dict[str, object]:
    trace_records = getattr(outcome, "trace_records", ())
    calls = [record for record in trace_records if isinstance(record, ModelCall)]
    call_ids = {record.model_call_id for record in calls}
    expected_digest = schema_digest(TESTCASE_CANDIDATE_OUTPUT_SPEC.schema)
    native_identity = bool(calls) and all(
        record.structured_output_mode == "JSON_SCHEMA"
        and record.schema_name == TESTCASE_CANDIDATE_SCHEMA_NAME
        and record.schema_digest == expected_digest
        for record in calls
    )
    terminal_calls = [record for record in calls if record.event.value == "TERMINAL"]
    response_models = {
        record.token_usage.provider_metadata.response_model
        for record in terminal_calls
        if record.token_usage is not None
        and record.token_usage.provider_metadata is not None
        and record.token_usage.provider_metadata.response_model is not None
    }
    calls_with_request_proof = sum(
        record.token_usage is not None
        and record.token_usage.provider_metadata is not None
        and record.token_usage.provider_metadata.provider_request_id is not None
        and record.token_usage.provider_metadata.response_model == record.model_identity.model
        for record in terminal_calls
    )
    return {
        "traceModelCallRecordCount": len(calls),
        "traceModelCallCount": len(call_ids),
        "nativeRootObjectSchema": native_identity,
        "nativeSchemaName": TESTCASE_CANDIDATE_SCHEMA_NAME,
        "nativeSchemaDigest": expected_digest,
        "providerSuccess": bool(terminal_calls)
        and all(record.status.value == "SUCCESS" for record in terminal_calls),
        "providerIdentityMatch": bool(calls)
        and all(
            record.model_identity.provider == "Qwen"
            and record.model_identity.model == "qwen3.8-max"
            for record in calls
        ),
        "callsWithRequestProof": calls_with_request_proof,
        "requestProvenanceComplete": bool(terminal_calls)
        and calls_with_request_proof == len(terminal_calls),
        "observedResponseModels": sorted(response_models),
    }


async def _run_case(
    settings: AppSettings,
    *,
    path: Path,
    label: str,
) -> dict[str, object]:
    task = _load_task(path)
    setup = await StaticFixtureAdapter().setup(task)
    async with httpx.AsyncClient(trust_env=False) as http_client:
        llm = build_llm(http_client, settings, provider="qwen")
        outcome = await RealModelStage20WorkflowAdapter(
            llm,
            repository_root=REPOSITORY_ROOT,
        ).execute(
            task,
            setup,
            trace_id=f"trace:stage21-qwen-prompt2-testcase-{label}",
            agent_run_id=f"agent_run:stage21-qwen-prompt2-testcase-{label}",
        )

    generation_status = _fact(outcome.facts, "candidate_status")
    trace_details = _native_trace_details(outcome)
    return {
        "label": label,
        "taskId": task.benchmark_task_id,
        "executionMode": outcome.execution_mode.value,
        "javaExecutionStatus": outcome.java_execution_status.value,
        "provider": llm.provider,
        "model": llm.model,
        "modelCallCount": len(outcome.model_call_ids),
        "modelCallIdsObserved": bool(outcome.model_call_ids),
        "validJson": outcome.facts.validity.valid_json,
        "schemaValid": outcome.facts.validity.schema_valid,
        "contractAccepted": outcome.facts.validity.contract_accepted,
        "generationStatus": generation_status,
        "candidate": _candidate_details(outcome.facts),
        "repairAttemptCount": max(0, len(outcome.model_call_ids) - 1),
        "realModelPath": outcome.execution_mode.value == "REAL_MODEL",
        "trace": trace_details,
    }


async def _run(settings: AppSettings) -> dict[str, object]:
    positive = await _run_case(settings, path=POSITIVE_TASK, label="positive")
    invalid = await _run_case(
        settings,
        path=INVALID_TASK,
        label="intentional-invalid-method",
    )
    positive_pass = all(
        (
            positive["realModelPath"] is True,
            positive["javaExecutionStatus"] == "NOT_APPLICABLE",
            positive["provider"] == "Qwen",
            positive["modelCallIdsObserved"] is True,
            positive["validJson"] is True,
            positive["schemaValid"] is True,
            positive["contractAccepted"] is True,
            positive["trace"]["nativeRootObjectSchema"] is True,
            positive["trace"]["providerSuccess"] is True,
            positive["trace"]["providerIdentityMatch"] is True,
            positive["trace"]["requestProvenanceComplete"] is True,
        )
    )
    invalid_candidate = invalid["candidate"]
    invalid_pass = all(
        (
            invalid["realModelPath"] is True,
            invalid["javaExecutionStatus"] == "NOT_APPLICABLE",
            invalid["provider"] == "Qwen",
            invalid["modelCallIdsObserved"] is True,
            invalid["validJson"] is True,
            invalid_candidate["candidateObjectObserved"] is True
            if isinstance(invalid_candidate, Mapping)
            else False,
            invalid_candidate["intendedInvalidMethodObserved"] is True
            if isinstance(invalid_candidate, Mapping)
            else False,
            invalid["schemaValid"] is False,
            invalid["contractAccepted"] is False,
            invalid["trace"]["nativeRootObjectSchema"] is True,
            invalid["trace"]["providerSuccess"] is True,
            invalid["trace"]["providerIdentityMatch"] is True,
            invalid["trace"]["requestProvenanceComplete"] is True,
        )
    )
    return {
        "provider": "qwen",
        "positive": positive,
        "intentionalInvalid": invalid,
        "positivePass": positive_pass,
        "intentionalInvalidPass": invalid_pass,
        "pass": positive_pass and invalid_pass,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--timeout", type=float, default=60.0)
    args = parser.parse_args()
    api_key = os.environ.get("QWEN_API_KEY", "").strip()
    if not api_key:
        raise SystemExit("QWEN_API_KEY is required")
    settings = AppSettings(
        testcase_llm_provider="qwen",
        qwen_api_key=SecretStr(api_key),
        qwen_timeout_seconds=args.timeout,
    )
    summary = asyncio.run(_run(settings))
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    return 0 if summary["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
