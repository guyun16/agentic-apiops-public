"""Run the frozen five-attempt Real Diagnosis provider stability probe."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
from collections.abc import Mapping
from typing import Any
from uuid import uuid4

import httpx

from app.agents.diagnosis import render_diagnosis_prompt
from app.clients.java_apiops import JavaApiOpsClient
from app.memory.fingerprint import normalize_identity
from app.rag.context import ContextPack, ContextPackBuilder
from app.schemas.runner import TestReport
from app.tracing.redaction import canonical_json_hash
from app.workflows.diagnosis_workflow import (
    _DEFAULT_CONTEXT_POLICY,
    diagnosis_initial_state,
    test_report_context_item,
)

PROJECT_ID = 41
RUN_ID = 4520
ATTEMPT_COUNT = 5
_PROVIDER_NAMES = {"deepseek": "DeepSeek", "qwen": "Qwen"}


def _provider_name(provider: str) -> str:
    try:
        return _PROVIDER_NAMES[provider]
    except KeyError as exc:
        raise ValueError("provider must be deepseek or qwen") from exc


def canonical_json(value: object) -> str:
    """Serialize one audit value without runtime-only ordering noise."""

    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _field(value: object, *names: str, default: object = None) -> object:
    if isinstance(value, Mapping):
        for name in names:
            if name in value:
                return value[name]
        return default
    for name in names:
        if hasattr(value, name):
            return getattr(value, name)
    return default


def _build_context_pack(report: TestReport) -> ContextPack:
    state = diagnosis_initial_state(
        report,
        trace_id="stability-probe-trace",
        agent_run_id="stability-probe-agent-run",
        workflow_id="stability-probe-workflow",
    )
    items = (test_report_context_item(state["report"]),) + state["supporting_context"]
    return ContextPackBuilder(
        _DEFAULT_CONTEXT_POLICY,
        project_scope=report.project_id,
    ).build(items)


def semantic_input_contract(report: TestReport, *, api_id: str) -> dict[str, object]:
    """Build the audit-only semantic contract from the production ContextPack."""

    pack = _build_context_pack(report)
    context_items = [
        {
            "sourceId": item.source_id,
            "sourceType": item.source_type.value,
            "contentDigest": sha256_text(item.content),
            "provenanceDigest": sha256_text(
                canonical_json(
                    [
                        reference.model_dump(mode="json", exclude_none=False)
                        for reference in item.provenance
                    ]
                )
            ),
            "truncated": item.truncated,
        }
        for item in pack.items
    ]
    return {
        "prompt": {"name": "diagnosis", "version": "v1", "mode": "INITIAL"},
        "projectId": report.project_id,
        "runId": report.run_id,
        "reportId": report.report_id,
        "apiId": api_id,
        "testReportDigest": sha256_text(
            canonical_json(report.model_dump(mode="json", exclude_none=False))
        ),
        "contextItems": context_items,
        "continuationReason": None,
    }


def raw_prompt_digest(
    report: TestReport,
    *,
    trace_id: str,
    agent_run_id: str,
) -> str:
    """Re-render the production initial prompt only to compare its digest."""

    prompt = render_diagnosis_prompt(
        _build_context_pack(report),
        report=report,
        trace_id=trace_id,
        agent_run_id=agent_run_id,
    )
    return canonical_json_hash(prompt)


async def _authority_snapshot(
    java: JavaApiOpsClient,
    *,
    token: str,
    trace_id: str,
) -> tuple[TestReport, str]:
    summaries = await java.list_test_runs(
        project_id=PROJECT_ID,
        token=token,
        trace_id=trace_id,
    )
    matches = tuple(item for item in summaries if item.run_id == RUN_ID)
    if len(matches) != 1:
        raise RuntimeError(f"expected one Java run summary for run {RUN_ID}")
    report = await java.get_test_report(
        project_id=PROJECT_ID,
        run_id=RUN_ID,
        token=token,
        trace_id=trace_id,
    )
    return report, matches[0].api_id


def _model_calls(records: list[Mapping[str, Any]]) -> list[dict[str, object]]:
    step_types = {
        str(_field(record, "agent_step_id", "agentStepId")): _field(
            record, "step_type", "stepType", default=None
        )
        for record in records
        if _field(record, "record_type", "recordType") == "agent_step"
    }
    grouped: dict[str, list[Mapping[str, Any]]] = {}
    for record in records:
        if _field(record, "record_type", "recordType") != "model_call":
            continue
        model_call_id = _field(record, "model_call_id", "modelCallId")
        if isinstance(model_call_id, str):
            grouped.setdefault(model_call_id, []).append(record)

    calls: list[dict[str, object]] = []
    for model_call_id, items in grouped.items():
        terminal = next(
            (item for item in items if _field(item, "event") == "TERMINAL"),
            items[-1],
        )
        start = next(
            (item for item in items if _field(item, "event") == "START"),
            items[0],
        )
        parent = _field(start, "parent_identity", "parentIdentity", default={})
        parent_step_id = _field(parent, "identity", default="")
        identity = _field(start, "model_identity", "modelIdentity", default={})
        prompt = _field(start, "prompt", default={})
        model_input = _field(start, "model_input", "modelInput", default={})
        model_output = _field(terminal, "model_output", "modelOutput", default={})
        usage = _field(terminal, "token_usage", "tokenUsage", default=None)
        provider_metadata = _field(usage, "provider_metadata", "providerMetadata", default={})
        latency = _field(terminal, "latency", default={})
        failure = _field(terminal, "failure", default=None)
        calls.append(
            {
                "modelCallId": model_call_id,
                "status": _field(terminal, "status"),
                "stepType": step_types.get(str(parent_step_id)),
                "provider": _field(identity, "provider"),
                "model": _field(identity, "model"),
                "promptName": _field(prompt, "name"),
                "promptVersion": _field(prompt, "version"),
                "modelInputDigest": _field(model_input, "sha256"),
                "modelOutputDigest": _field(model_output, "sha256"),
                "providerRequestId": _field(
                    provider_metadata,
                    "provider_request_id",
                    "providerRequestId",
                ),
                "finishReason": _field(provider_metadata, "finish_reason", "finishReason"),
                "promptTokens": _field(usage, "prompt_tokens", "promptTokens"),
                "completionTokens": _field(usage, "completion_tokens", "completionTokens"),
                "totalTokens": _field(usage, "total_tokens", "totalTokens"),
                "latencyMs": _field(latency, "duration_ms", "durationMs"),
                "failureCategory": _field(failure, "failure_category", "failureCategory"),
                "failureCode": _field(failure, "failure_code", "failureCode"),
                "failureErrorType": _field(failure, "error_type", "errorType"),
                "failureMessageSafe": _field(failure, "message"),
            }
        )
    return calls


def _trace_facts(records: list[Mapping[str, Any]]) -> dict[str, object]:
    calls = _model_calls(records)
    initial_calls = [item for item in calls if item.get("stepType") == "diagnosis_initial"]
    if not initial_calls:
        initial_calls = [
            item
            for item in calls
            if item.get("promptName") == "diagnosis"
            and item.get("promptName") != "diagnosis_memory_refinement"
        ][:1]
    tool_intents = [
        record
        for record in records
        if _field(record, "record_type", "recordType") == "tool_intent"
        and _field(record, "event") == "INTENT"
    ]
    tool_results = [
        record
        for record in records
        if _field(record, "record_type", "recordType") == "tool_result"
    ]
    retrievals = [
        record
        for record in records
        if _field(record, "record_type", "recordType") == "retrieval"
    ]
    rag_retrievals = [
        record
        for record in retrievals
        if _field(record, "retrieval_kind", "retrievalKind") == "JAVA_RAG_TOOL_RESULT"
    ]
    memory_retrievals = [
        record
        for record in retrievals
        if _field(record, "retrieval_kind", "retrievalKind") == "HISTORICAL_MEMORY"
    ]
    rag_requested = any(
        _field(record, "tool_name", "toolName") == "rag.search" for record in tool_intents
    )
    rag_status = (
        _field(tool_results[0], "tool_result_status", "toolResultStatus")
        if tool_results
        else None
    )
    rag_query_id = None
    rag_result_count = 0
    for retrieval in rag_retrievals:
        reference = _field(retrieval, "reference", default={})
        rag_query_id = rag_query_id or _field(reference, "rag_query_id", "ragQueryId")
        count = _field(retrieval, "result_count", "resultCount", default=0)
        if isinstance(count, int):
            rag_result_count += count
    return {
        "modelCalls": calls,
        "initialModelCalls": initial_calls,
        "continuationModelCallCount": sum(
            item.get("stepType") == "diagnosis_continuation" for item in calls
        ),
        "memoryRefinementModelCallCount": sum(
            item.get("stepType") == "diagnosis_memory_refinement" for item in calls
        ),
        "toolIntentCount": len(tool_intents),
        "toolCallCount": len(tool_results),
        "ragSearchRequested": rag_requested,
        "ragToolStatus": rag_status,
        "ragQueryId": rag_query_id,
        "ragRetrievalCount": rag_result_count,
        "historicalMemoryRetrievalCount": len(memory_retrievals),
    }


def _candidate(payload: Mapping[str, Any]) -> dict[str, object]:
    report = payload.get("report")
    if not isinstance(report, Mapping):
        return {
            "sufficientEvidence": None,
            "rootCauseHypothesesCount": None,
            "rootCauseRaw": None,
            "rootCauseNormalized": None,
            "evidenceRefItemIds": [],
            "recommendedChecksCount": None,
            "limitationsCount": None,
        }
    hypotheses = report.get("rootCauseHypotheses", [])
    first = hypotheses[0] if isinstance(hypotheses, list) and hypotheses else None
    statement = _field(first, "statement") if first is not None else None
    evidence_refs = _field(first, "evidenceRefs", "evidence_refs", default=[])
    return {
        "sufficientEvidence": report.get("sufficientEvidence"),
        "rootCauseHypothesesCount": len(hypotheses) if isinstance(hypotheses, list) else None,
        "rootCauseRaw": statement if isinstance(statement, str) else None,
        "rootCauseNormalized": (
            normalize_identity(statement) if isinstance(statement, str) else None
        ),
        "evidenceRefItemIds": [
            _field(reference, "itemId", "item_id")
            for reference in evidence_refs
            if _field(reference, "itemId", "item_id") is not None
        ],
        "recommendedChecksCount": len(report.get("recommendedChecks", [])),
        "limitationsCount": len(report.get("limitations", [])),
    }


def _application_error(payload: object) -> tuple[object, object]:
    if not isinstance(payload, Mapping):
        return None, None
    return payload.get("code"), payload.get("message")


async def _attempt(
    java: JavaApiOpsClient,
    python: httpx.AsyncClient,
    *,
    token: str,
    timeout: float,
    index: int,
    provider: str = "deepseek",
) -> dict[str, object]:
    expected_provider = _provider_name(provider)
    trace_id = f"real-{provider}-stability-{index}-{uuid4().hex}"
    authority: dict[str, object] = {}
    try:
        report, api_id = await _authority_snapshot(java, token=token, trace_id=trace_id)
        report_digest = sha256_text(
            canonical_json(report.model_dump(mode="json", exclude_none=False))
        )
        semantic = semantic_input_contract(report, api_id=api_id)
        semantic_digest = sha256_text(canonical_json(semantic))
        authority = {
            "projectId": report.project_id,
            "runId": report.run_id,
            "reportId": report.report_id,
            "apiId": api_id,
            "testReportDigest": report_digest,
            "semanticInputDigest": semantic_digest,
        }
    except Exception as exc:  # pragma: no cover - live boundary result
        return {
            "attempt": index,
            "traceId": trace_id,
            "authority": {"errorType": type(exc).__name__},
            "httpStatus": None,
            "applicationErrorCode": "AUTHORITY_PROBE_FAILED",
            "applicationErrorMessageSafe": "authority probe failed",
            "diagnosisStatus": None,
            "agentRunId": None,
            "expectedProvider": expected_provider,
            "providerMatches": False,
            "model": {},
            "candidate": _candidate({}),
            "facts": {},
            "probeErrorType": type(exc).__name__,
        }

    response = await python.post(
        "/api/v1/diagnosis/runs",
        headers={"Authorization": f"Bearer {token}", "X-Trace-Id": trace_id},
        json={"projectId": PROJECT_ID, "runId": RUN_ID},
        timeout=timeout,
    )
    try:
        payload = response.json()
    except ValueError:
        payload = {}
    error_code, error_message = _application_error(payload)

    trace_response = await python.get(
        f"/api/v1/traces/{trace_id}",
        headers={"Authorization": f"Bearer {token}"},
        timeout=timeout,
    )
    try:
        records_payload = trace_response.json() if trace_response.status_code == 200 else []
    except ValueError:
        records_payload = []
    records = records_payload if isinstance(records_payload, list) else []
    records = [record for record in records if isinstance(record, Mapping)]
    facts = _trace_facts(records)
    model_calls = facts.get("modelCalls", [])
    initial_model = facts.get("initialModelCalls", [])
    initial_model_record = initial_model[0] if initial_model else {}
    agent_run_id = _field(payload, "agentRunId", "agent_run_id")
    if not isinstance(agent_run_id, str):
        agent_run_id = _field(records[0], "agent_run_id", "agentRunId") if records else None
    computed_raw_digest = (
        raw_prompt_digest(
            report,
            trace_id=trace_id,
            agent_run_id=agent_run_id,
        )
        if isinstance(agent_run_id, str)
        else None
    )
    return {
        "attempt": index,
        "traceId": trace_id,
        "authority": authority,
        "httpStatus": response.status_code,
        "applicationErrorCode": error_code,
        "applicationErrorMessageSafe": error_message,
        "diagnosisStatus": _field(payload, "status"),
        "agentRunId": agent_run_id,
        "expectedProvider": expected_provider,
        "model": initial_model_record,
        "providerMatches": initial_model_record.get("provider") == expected_provider,
        "computedRawModelInputDigest": computed_raw_digest,
        "rawModelInputDigestMatchesRendered": (
            computed_raw_digest is not None
            and computed_raw_digest == initial_model_record.get("modelInputDigest")
        ),
        "candidate": _candidate(payload),
        "facts": {
            key: value
            for key, value in facts.items()
            if key not in {"modelCalls", "initialModelCalls"}
        },
        "modelCallCount": len(model_calls),
        "traceHttpStatus": trace_response.status_code,
    }


def classify(summary: Mapping[str, object]) -> str:
    attempts = summary.get("attempts", [])
    if not isinstance(attempts, list) or len(attempts) != ATTEMPT_COUNT:
        return "REAL_PROVIDER_STABILITY_UNRESOLVED"
    authority = [
        item.get("authority")
        for item in attempts
        if isinstance(item, Mapping) and isinstance(item.get("authority"), Mapping)
    ]
    if len(authority) != ATTEMPT_COUNT or any("errorType" in item for item in authority):
        return "REAL_PROVIDER_STABILITY_UNRESOLVED"
    authority_keys = {
        canonical_json(
            {
                key: item.get(key)
                for key in ("reportId", "apiId", "testReportDigest")
            }
        )
        for item in authority
    }
    if len(authority_keys) != 1:
        return "JAVA_AUTHORITY_INPUT_CHANGED"
    semantic_keys = {
        str(item.get("semanticInputDigest"))
        for item in authority
    }
    if len(semantic_keys) != 1:
        return "DIAGNOSIS_INPUT_INSTABILITY"

    expected_provider = _provider_name(str(summary.get("provider", "deepseek")))
    if any(
        isinstance(attempt.get("model"), Mapping)
        and attempt["model"].get("provider") != expected_provider
        for attempt in attempts
    ):
        return "PROVIDER_IDENTITY_MISMATCH"

    for attempt in attempts:
        if attempt.get("httpStatus") != 502:
            continue
        model = attempt.get("model")
        model_status = model.get("status") if isinstance(model, Mapping) else None
        failure_type = model.get("failureErrorType") if isinstance(model, Mapping) else None
        if model_status == "FAILED":
            return {
                "DeepSeekHttpError": "PROVIDER_HTTP_INSTABILITY",
                "DeepSeekTimeoutError": "PROVIDER_TIMEOUT_INSTABILITY",
                "DeepSeekTransportError": "PROVIDER_TRANSPORT_INSTABILITY",
                "DeepSeekResponseError": "PROVIDER_RESPONSE_FORMAT_INSTABILITY",
            }.get(str(failure_type), "PROVIDER_FAILURE_OBSERVABILITY_GAP")
        return "PROVIDER_FAILURE_OBSERVABILITY_GAP"

    comparable = [
        attempt
        for attempt in attempts
        if isinstance(attempt.get("model"), Mapping)
        and attempt["model"].get("status") == "SUCCESS"
        and attempt.get("httpStatus") == 200
    ]
    if len(comparable) != ATTEMPT_COUNT:
        return "REAL_PROVIDER_STABILITY_UNRESOLVED"
    candidates = [attempt["candidate"] for attempt in comparable]
    counts = {item.get("rootCauseHypothesesCount") for item in candidates}
    roots = {item.get("rootCauseNormalized") for item in candidates}
    sufficient = {item.get("sufficientEvidence") for item in candidates}
    if len(counts) > 1 and counts <= {0, 1}:
        return "REAL_MODEL_DIAGNOSIS_VARIANCE"
    if len(roots) > 1 and all(item.get("rootCauseHypothesesCount", 0) for item in candidates):
        return "REAL_MODEL_ROOT_CAUSE_VARIANCE"
    if len(counts) == len(roots) == len(sufficient) == 1:
        return "NO_REPRODUCIBLE_INSTABILITY"
    return "REAL_PROVIDER_STABILITY_UNRESOLVED"


async def run_probe(
    *,
    java_base_url: str,
    python_base_url: str,
    token: str,
    timeout: float,
    provider: str = "deepseek",
) -> dict[str, object]:
    expected_provider = _provider_name(provider)
    async with httpx.AsyncClient(trust_env=False, timeout=timeout) as http_client:
        java = JavaApiOpsClient(
            http_client,
            base_url=java_base_url,
            timeout_seconds=timeout,
        )
        async with httpx.AsyncClient(
            base_url=python_base_url.rstrip("/"),
            trust_env=False,
            timeout=timeout,
        ) as python:
            attempts = []
            for index in range(1, ATTEMPT_COUNT + 1):
                attempts.append(
                    await _attempt(
                        java,
                        python,
                        token=token,
                        timeout=timeout,
                        index=index,
                        provider=provider,
                    )
                )
    semantic_digests = [
        item.get("authority", {}).get("semanticInputDigest")
        for item in attempts
        if isinstance(item.get("authority"), Mapping)
    ]
    raw_digests = [
        item.get("model", {}).get("modelInputDigest")
        for item in attempts
        if isinstance(item.get("model"), Mapping)
    ]
    return {
        "projectId": PROJECT_ID,
        "runId": RUN_ID,
        "provider": provider,
        "expectedProvider": expected_provider,
        "attemptCount": ATTEMPT_COUNT,
        "attempts": attempts,
        "semanticInputDigests": semantic_digests,
        "rawModelInputDigests": raw_digests,
        "semanticInputSame": (
            len(set(semantic_digests)) == 1 and len(semantic_digests) == ATTEMPT_COUNT
        ),
        "rawModelInputSame": len(set(raw_digests)) == 1 and len(raw_digests) == ATTEMPT_COUNT,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--provider",
        choices=tuple(_PROVIDER_NAMES),
        default=os.environ.get("DIAGNOSIS_LLM_PROVIDER", "deepseek"),
    )
    parser.add_argument("--java-base-url", default=os.environ.get("JAVA_APIOPS_BASE_URL", ""))
    parser.add_argument("--python-base-url", default=os.environ.get("PYTHON_BASE_URL", ""))
    parser.add_argument("--timeout", type=float, default=90.0)
    args = parser.parse_args()
    token = os.environ.get("JAVA_APIOPS_TOKEN", "").strip()
    if not args.java_base_url or not args.python_base_url or not token:
        raise SystemExit(
            "JAVA_APIOPS_BASE_URL, PYTHON_BASE_URL, and JAVA_APIOPS_TOKEN are required"
        )
    summary = asyncio.run(
        run_probe(
            java_base_url=args.java_base_url,
            python_base_url=args.python_base_url,
            token=token,
            timeout=args.timeout,
            provider=args.provider,
        )
    )
    summary["classification"] = classify(summary)
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
