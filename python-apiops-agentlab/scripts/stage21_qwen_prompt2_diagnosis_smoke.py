"""Run the frozen five-attempt Qwen Diagnosis semantic smoke."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
from time import perf_counter

import httpx
from jsonschema import ValidationError as JsonSchemaValidationError
from jsonschema import validate as validate_json_schema
from pydantic import SecretStr

from app.agents.diagnosis import (
    DiagnosisCandidateParseError,
    DiagnosisEvidenceReferenceError,
    DiagnosisIdentityError,
    DiagnosisInference,
    DiagnosisSemanticContractError,
    render_diagnosis_prompt,
)
from app.clients.llm import StructuredOutputSpec
from app.clients.llm_provider import build_llm
from app.clients.qwen_structured_output import (
    DIAGNOSIS_REPORT_OUTPUT_SPEC,
    DIAGNOSIS_REPORT_SCHEMA_NAME,
    schema_digest,
)
from app.core.settings import AppSettings
from app.rag.context import ContextPack, ContextPackBuilder
from app.schemas.diagnosis_report import DiagnosisReport
from app.schemas.runner import TestReport
from app.tools import ToolIntent
from app.workflows.diagnosis_workflow import (
    _DEFAULT_CONTEXT_POLICY,
    test_report_context_item,
)

ATTEMPT_COUNT = 5
PROJECT_ID = 41
RUN_ID = 4520
REPORT_ID = "report:stage21-qwen-prompt2-dns"
TRACE_ID = "trace:stage21-qwen-prompt2-diagnosis"
AGENT_RUN_ID = "agent_run:stage21-qwen-prompt2-diagnosis"
REPORT_ONLY_CONTINUATION_REASON = (
    "The tool budget is exhausted; return only a final DiagnosisReport."
)


def _digest(value: object) -> str:
    if isinstance(value, str):
        payload = value.encode("utf-8")
    else:
        payload = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _report() -> TestReport:
    return TestReport.model_validate(
        {
            "projectId": PROJECT_ID,
            "taskId": 321,
            "runId": RUN_ID,
            "reportId": REPORT_ID,
            "status": "EXECUTION_FAILED",
            "startedAt": "2026-09-02T00:00:00Z",
            "finishedAt": "2026-09-02T00:00:01Z",
            "summary": {
                "totalCases": 1,
                "totalSteps": 1,
                "totalAssertions": 0,
                "passedAssertions": 0,
                "failedAssertions": 0,
                "failureType": "DNS_ERROR",
            },
            "cases": [
                {
                    "caseId": "case-stage21-qwen-dns",
                    "status": "EXECUTION_FAILED",
                    "failureType": "DNS_ERROR",
                    "steps": [
                        {
                            "stepId": "step-stage21-qwen-dns",
                            "status": "EXECUTION_FAILED",
                            "failureType": "DNS_ERROR",
                            "responseStatusCode": None,
                            "durationMs": 1000,
                            "assertionResults": [],
                        }
                    ],
                }
            ],
        }
    )


class _DigestingLLM:
    """Capture only bounded response facts while preserving the LLMClient call."""

    def __init__(self, client: object) -> None:
        self._client = client
        self.response_length: int | None = None
        self.response_digest: str | None = None
        self.provider_call_succeeded = False
        self.json_parse_ok = False
        self.native_schema_valid: bool | None = None

    @property
    def provider(self) -> str:
        return self._client.provider  # type: ignore[attr-defined]

    @property
    def model(self) -> str:
        return self._client.model  # type: ignore[attr-defined]

    @property
    def last_completion_metadata(self) -> object | None:
        return self._client.last_completion_metadata  # type: ignore[attr-defined]

    def _capture(self, raw: str, *, output_spec: StructuredOutputSpec | None = None) -> str:
        self.provider_call_succeeded = True
        self.response_length = len(raw) if isinstance(raw, str) else None
        self.response_digest = _digest(raw) if isinstance(raw, str) else None
        self.json_parse_ok = False
        if output_spec is not None:
            self.native_schema_valid = False
        if not isinstance(raw, str):
            return raw
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            return raw
        self.json_parse_ok = True
        if output_spec is not None:
            try:
                validate_json_schema(payload, output_spec.schema)
            except JsonSchemaValidationError:
                self.native_schema_valid = False
            else:
                self.native_schema_valid = True
        return raw

    async def complete(self, prompt: str) -> str:
        raw = await self._client.complete(prompt)  # type: ignore[attr-defined]
        return self._capture(raw)

    async def complete_structured(
        self,
        prompt: str,
        *,
        output_spec: StructuredOutputSpec,
    ) -> str:
        raw = await self._client.complete_structured(  # type: ignore[attr-defined]
            prompt,
            output_spec=output_spec,
        )
        return self._capture(raw, output_spec=output_spec)


def _context_pack(report: TestReport) -> ContextPack:
    return ContextPackBuilder(
        _DEFAULT_CONTEXT_POLICY,
        project_scope=PROJECT_ID,
    ).build((test_report_context_item(report),))


def _candidate_summary(decision: DiagnosisReport | ToolIntent) -> dict[str, object]:
    if isinstance(decision, DiagnosisReport):
        return {
            "kind": "DIAGNOSIS_REPORT",
            "sufficientEvidence": decision.sufficient_evidence,
            "rootCauseHypothesesCount": len(decision.root_cause_hypotheses),
            "confidenceValues": [
                hypothesis.confidence for hypothesis in decision.root_cause_hypotheses
            ],
            "evidenceRefCount": sum(
                len(hypothesis.evidence_refs) for hypothesis in decision.root_cause_hypotheses
            ),
            "limitationsCount": len(decision.limitations),
            "recommendedChecksCount": len(decision.recommended_checks),
        }
    return {"kind": "TOOL_INTENT", "toolName": decision.tool_name}


def _metadata_summary(client: _DigestingLLM) -> dict[str, object]:
    metadata = client.last_completion_metadata
    return {
        "provider": client.provider,
        "model": client.model,
        "providerResponseModel": getattr(metadata, "model", None),
        "providerRequestIdPresent": bool(getattr(metadata, "provider_request_id", None)),
        "finishReason": getattr(metadata, "finish_reason", None),
        "promptTokens": getattr(metadata, "prompt_tokens", None),
        "completionTokens": getattr(metadata, "completion_tokens", None),
        "totalTokens": getattr(metadata, "total_tokens", None),
        "structuredOutputMode": getattr(metadata, "structured_output_mode", None),
        "schemaName": getattr(metadata, "schema_name", None),
        "schemaDigest": getattr(metadata, "schema_digest", None),
    }


async def _run(settings: AppSettings) -> dict[str, object]:
    report = _report()
    context_pack = _context_pack(report)
    prompt = render_diagnosis_prompt(
        context_pack,
        report=report,
        trace_id=TRACE_ID,
        agent_run_id=AGENT_RUN_ID,
        continuation_reason=REPORT_ONLY_CONTINUATION_REASON,
    )
    input_summary = {
        "projectId": PROJECT_ID,
        "runId": RUN_ID,
        "reportIdDigest": _digest(REPORT_ID),
        "fixtureDigest": _digest(report.model_dump(mode="json", exclude_none=False)),
        "contextPackDigest": _digest(
            [
                {
                    "sourceId": item.source_id,
                    "sourceType": item.source_type.value,
                    "contentDigest": _digest(item.content),
                }
                for item in context_pack.items
            ]
        ),
        "promptDigest": _digest(prompt),
    }
    attempts: list[dict[str, object]] = []
    async with httpx.AsyncClient(trust_env=False) as http_client:
        for index in range(1, ATTEMPT_COUNT + 1):
            client = _DigestingLLM(build_llm(http_client, settings, provider="qwen"))
            started = perf_counter()
            pydantic_report = False
            identity_validation = False
            citation_validation = False
            semantic_validation = False
            try:
                decision = await DiagnosisInference(client).generate(
                    context_pack,
                    report=report,
                    trace_id=TRACE_ID,
                    agent_run_id=AGENT_RUN_ID,
                    continuation_reason=REPORT_ONLY_CONTINUATION_REASON,
                )
            except DiagnosisSemanticContractError as exc:
                result = "SEMANTIC_FAIL"
                error_class = type(exc).__name__
                candidate = None
                pydantic_report = True
                identity_validation = True
                citation_validation = True
            except DiagnosisCandidateParseError as exc:
                result = "STRUCTURED_OUTPUT_FAIL"
                error_class = type(exc).__name__
                candidate = None
                pydantic_report = False
                identity_validation = False
                citation_validation = False
            except DiagnosisIdentityError as exc:
                result = "IDENTITY_FAIL"
                error_class = type(exc).__name__
                candidate = None
                pydantic_report = True
                identity_validation = False
                citation_validation = False
            except DiagnosisEvidenceReferenceError as exc:
                result = "CITATION_FAIL"
                error_class = type(exc).__name__
                candidate = None
                pydantic_report = True
                identity_validation = True
                citation_validation = False
            except Exception as exc:  # noqa: BLE001 - safe live-boundary summary
                result = "PROVIDER_OR_RUNTIME_FAIL"
                error_class = type(exc).__name__
                candidate = None
            else:
                result = "PASS" if isinstance(decision, DiagnosisReport) else "TOOL_INTENT"
                error_class = None
                candidate = _candidate_summary(decision)
                pydantic_report = isinstance(decision, DiagnosisReport)
                identity_validation = pydantic_report
                citation_validation = pydantic_report
                semantic_validation = pydantic_report
            attempts.append(
                {
                    "attempt": index,
                    "result": result,
                    "provider": client.provider,
                    "model": client.model,
                    "responseLength": client.response_length,
                    "responseDigest": client.response_digest,
                    "latencyMs": round((perf_counter() - started) * 1000, 2),
                    "providerMetadata": _metadata_summary(client),
                    "providerSuccess": client.provider_call_succeeded,
                    "structuredJson": client.json_parse_ok,
                    "nativeSchemaValidation": client.native_schema_valid,
                    "pydanticDiagnosisReport": pydantic_report,
                    "identityValidation": identity_validation,
                    "citationValidation": citation_validation,
                    "semanticValidation": semantic_validation,
                    "candidate": candidate,
                    "errorClass": error_class,
                }
            )
    passed = [attempt for attempt in attempts if attempt["result"] == "PASS"]
    return {
        "provider": "qwen",
        "expectedProvider": "Qwen",
        "attemptCount": len(attempts),
        "input": input_summary,
        "attempts": attempts,
        "promptStable": len({input_summary["promptDigest"]}) == 1,
        "allProviderIdentityMatch": all(attempt["provider"] == "Qwen" for attempt in attempts),
        "providerSuccessCount": sum(bool(attempt["providerSuccess"]) for attempt in attempts),
        "structuredOutputPassCount": sum(bool(attempt["structuredJson"]) for attempt in attempts),
        "nativeSchemaValidationPassCount": sum(
            bool(attempt["nativeSchemaValidation"]) for attempt in attempts
        ),
        "pydanticPassCount": sum(bool(attempt["pydanticDiagnosisReport"]) for attempt in attempts),
        "identityPassCount": sum(bool(attempt["identityValidation"]) for attempt in attempts),
        "citationPassCount": sum(bool(attempt["citationValidation"]) for attempt in attempts),
        "semanticPassCount": sum(bool(attempt["semanticValidation"]) for attempt in attempts),
        "nativeSchemaName": DIAGNOSIS_REPORT_SCHEMA_NAME,
        "nativeSchemaDigest": schema_digest(DIAGNOSIS_REPORT_OUTPUT_SPEC.schema),
        "pass": (
            len(attempts) == ATTEMPT_COUNT
            and len(passed) == ATTEMPT_COUNT
            and all(
                attempt["providerSuccess"] is True
                and attempt["nativeSchemaValidation"] is True
                and attempt["structuredJson"] is True
                and attempt["pydanticDiagnosisReport"] is True
                and attempt["identityValidation"] is True
                and attempt["citationValidation"] is True
                and attempt["semanticValidation"] is True
                for attempt in attempts
            )
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--timeout", type=float, default=60.0)
    args = parser.parse_args()
    api_key = os.environ.get("QWEN_API_KEY", "").strip()
    if not api_key:
        raise SystemExit("QWEN_API_KEY is required")
    settings = AppSettings(
        diagnosis_llm_provider="qwen",
        qwen_api_key=SecretStr(api_key),
        qwen_timeout_seconds=args.timeout,
    )
    summary = asyncio.run(_run(settings))
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    return 0 if summary["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
