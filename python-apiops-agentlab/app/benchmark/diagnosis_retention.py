"""Opt-in formal-run evidence sink at existing model and diagnosis boundaries.

This module knows no GroundTruth or review verdicts. Hashes of original values
use the tracing algorithm; hashes of retained values are explicitly separate.
Failure is latched so a workflow exception handler cannot silently continue a run.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from app.agents.diagnosis_contract import context_payload, observe_diagnosis_contract
from app.clients.llm import StructuredOutputSpec
from app.rag.context import ContextPack
from app.tracing.models import ModelCall, TraceEvent
from app.tracing.redaction import canonical_json, canonical_json_hash, redact_value
from app.tracing.workflow import _ACTIVE_TRACE_STEP

MAX_RETAINED_CHARS = 2_000_000


def write_once(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
        stream.flush()


class DiagnosisRetention:
    def __init__(self, root: Path, secrets: tuple[str, ...] = ()) -> None:
        self.root = root
        self.secrets = tuple(value for value in secrets if value)
        self.failure: str | None = None
        self.task_id: str | None = None
        self.calls: list[dict] = []
        self.original_prompts: dict[str, str] = {}

    def safe(self, value: object) -> object:
        serialized = canonical_json(value)
        if len(serialized) > MAX_RETAINED_CHARS:
            raise ValueError("retention bound exceeded; content must not be truncated")
        safe = redact_value(value, max_summary_chars=MAX_RETAINED_CHARS)

        # Prompts can embed JSON; the shared text redactor handles header syntax,
        # while this sink also covers quoted credential fields in embedded JSON.
        def scrub(item):
            if isinstance(item, str):
                for secret in self.secrets:
                    item = item.replace(secret, "[REDACTED]")
                return re.sub(
                    r'(?i)("(?:password|authorization|api[_-]?key|access[_-]?token|'
                    r'refresh[_-]?token|client[_-]?secret)"\s*:\s*")[^"\r\n]*(")',
                    r"\1[REDACTED]\2",
                    item,
                )
            if isinstance(item, dict):
                return {key: scrub(child) for key, child in item.items()}
            if isinstance(item, list):
                return [scrub(child) for child in item]
            return item

        return scrub(safe)

    def persist(self, relative: str, payload: dict) -> None:
        try:
            write_once(self.root / relative, payload)
        except Exception as exc:
            self.failure = f"retention persistence failed: {type(exc).__name__}"
            raise RuntimeError(self.failure) from None

    def observe(self, task, candidate, context, records) -> None:
        try:
            if not isinstance(context, ContextPack):
                raise ValueError("complete diagnosis lacks its actual bounded context")
            original = candidate.model_dump(mode="json")
            evidence = context_payload(context)
            retained = self.safe(original)
            bounded = self.safe(evidence)
            observation = observe_diagnosis_contract(original, evidence)
            terminal = [
                record
                for record in records
                if isinstance(record, ModelCall) and record.event is TraceEvent.TERMINAL
            ]
            serialized_evidence = json.dumps(evidence, ensure_ascii=False, sort_keys=True)
            evidence_calls = [
                record.model_call_id
                for record in terminal
                if serialized_evidence in self.original_prompts.get(record.model_call_id, "")
            ]
            if not evidence_calls:
                raise ValueError("final bounded evidence not found in actual model-visible input")
            payload = {
                "schemaVersion": "stage21-diagnosis-retention/v1",
                "taskId": task.benchmark_task_id,
                "traceId": terminal[-1].trace_id if terminal else None,
                "modelCallIds": [record.model_call_id for record in terminal],
                "evidenceVisibleInModelCallIds": evidence_calls,
                "originalCandidateDigest": observation["candidateDigest"],
                "originalEvidenceDigest": observation["evidenceDigest"],
                "retainedCandidateDigest": canonical_json_hash(retained),
                "retainedEvidenceDigest": canonical_json_hash(bounded),
                "redactionChangedCandidate": retained != original,
                "redactionChangedEvidence": bounded != evidence,
                "completeStructuredReport": True,
                "diagnosisReport": retained,
                "boundedEvidence": bounded,
                "contractObservation": observation,
            }
            name = canonical_json_hash(task.benchmark_task_id)[:20]
            self.persist(f"reports/{name}.json", payload)
        except Exception as exc:
            self.failure = f"diagnosis retention failed: {type(exc).__name__}"
            raise RuntimeError(self.failure) from None


class RetainingLLM:
    """Qwen's native structured capability is preserved without changing requests."""

    def __init__(self, client, sink: DiagnosisRetention) -> None:
        self.client = client
        self.sink = sink

    def __getattr__(self, name):
        return getattr(self.client, name)

    async def complete(self, prompt: str) -> str:
        return await self._call(prompt, None)

    async def complete_structured(self, prompt: str, *, output_spec: StructuredOutputSpec) -> str:
        return await self._call(prompt, output_spec)

    async def _call(self, prompt: str, spec: StructuredOutputSpec | None) -> str:
        context = _ACTIVE_TRACE_STEP.get()
        if context is None:
            self.sink.failure = "model call without existing trace context"
            raise RuntimeError(self.sink.failure)
        starts = [
            record
            for record in context.recorder.typed_records
            if isinstance(record, ModelCall)
            and record.event is TraceEvent.START
            and record.agent_step_id == context.agent_step_id
        ]
        if not starts:
            self.sink.failure = "model call missing trace START"
            raise RuntimeError(self.sink.failure)
        start = starts[-1]
        try:
            retained_prompt = self.sink.safe(prompt)
            payload = {
                "taskId": self.sink.task_id,
                "traceId": context.trace_id,
                "modelCallId": start.model_call_id,
                "promptIdentity": context.prompt.model_dump(mode="json"),
                "originalInputDigest": canonical_json_hash(prompt),
                "retainedInputDigest": canonical_json_hash(retained_prompt),
                "modelVisibleInputRedacted": retained_prompt,
                "structuredOutputSpec": None
                if spec is None
                else {
                    "name": spec.schema_name,
                    "schema": dict(spec.schema),
                    "strict": spec.strict,
                },
            }
            if payload["originalInputDigest"] != start.model_input.sha256:
                raise ValueError("input digest mismatch with original trace")
            key = canonical_json_hash(start.model_call_id)[:20]
            self.sink.persist(f"calls/{key}-input.json", payload)
            self.sink.original_prompts[start.model_call_id] = prompt
        except Exception as exc:
            self.sink.failure = f"model input retention failed: {type(exc).__name__}"
            raise RuntimeError(self.sink.failure) from None
        try:
            output = (
                await self.client.complete(prompt)
                if spec is None
                else await self.client.complete_structured(prompt, output_spec=spec)
            )
        except Exception as exc:
            self.sink.persist(
                f"calls/{key}-output.json",
                {
                    "modelCallId": start.model_call_id,
                    "status": "FAILED",
                    "errorType": type(exc).__name__,
                },
            )
            raise
        try:
            retained_output = self.sink.safe(output)
            self.sink.persist(
                f"calls/{key}-output.json",
                {
                    "modelCallId": start.model_call_id,
                    "status": "SUCCESS",
                    "originalOutputDigest": canonical_json_hash(output),
                    "retainedOutputDigest": canonical_json_hash(retained_output),
                    "modelOutputRedacted": retained_output,
                },
            )
        except Exception as exc:
            self.sink.failure = f"model output retention failed: {type(exc).__name__}"
            raise RuntimeError(self.sink.failure) from None
        self.sink.calls.append(payload)
        return output
