from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.clients.llm import StructuredOutputSpec
from app.clients.qwen_structured_output import (
    DIAGNOSIS_REPORT_OUTPUT_SPEC,
    TESTCASE_CANDIDATE_OUTPUT_SPEC,
    schema_digest,
)
from app.tracing import InMemoryTraceSink, InstrumentedLLM, PromptIdentity, TraceRecorder
from app.tracing.workflow import trace_step_scope


class _NativeQwen:
    provider = "Qwen"
    model = "qwen3.7-plus-2026-05-26"

    def __init__(self) -> None:
        self.last_completion_metadata = SimpleNamespace(
            provider_request_id="qwen-trace-request",
            finish_reason="stop",
            prompt_tokens=10,
            completion_tokens=4,
            total_tokens=14,
            model=self.model,
        )
        self.legacy_calls = 0
        self.native_calls: list[StructuredOutputSpec] = []

    async def complete(self, prompt: str) -> str:
        del prompt
        self.legacy_calls += 1
        return '{"legacy":true}'

    async def complete_structured(
        self,
        prompt: str,
        *,
        output_spec: StructuredOutputSpec,
    ) -> str:
        del prompt
        self.native_calls.append(output_spec)
        return '{"native":true}'


class _LegacyDeepSeek:
    provider = "DeepSeek"
    model = "deepseek-v4-flash"

    def __init__(self) -> None:
        self.last_completion_metadata = None
        self.calls = 0

    async def complete(self, prompt: str) -> str:
        del prompt
        self.calls += 1
        return '{"legacy":true}'


@pytest.mark.anyio
async def test_instrumented_native_call_records_schema_identity_and_legacy_mode() -> None:
    sink = InMemoryTraceSink()
    recorder = TraceRecorder(sink)
    qwen = _NativeQwen()
    llm = InstrumentedLLM(qwen)
    prompt_identity = PromptIdentity(name="diagnosis", version="v1")

    with trace_step_scope(
        recorder,
        trace_id="trace-native",
        agent_run_id="run-native",
        agent_step_id="step-native",
        prompt=prompt_identity,
    ):
        assert await llm.complete_structured(
            "report-only",
            output_spec=DIAGNOSIS_REPORT_OUTPUT_SPEC,
        ) == '{"native":true}'
        assert await llm.complete("legacy dual output") == '{"legacy":true}'

    calls = [record for record in recorder.typed_records if record.record_type == "model_call"]
    assert len(calls) == 4
    native_start, native_terminal, legacy_start, legacy_terminal = calls
    assert native_start.structured_output_mode == "JSON_SCHEMA"
    assert native_start.schema_name == "diagnosis_report_v1"
    assert native_start.schema_digest == schema_digest(DIAGNOSIS_REPORT_OUTPUT_SPEC.schema)
    assert native_terminal.structured_output_mode == "JSON_SCHEMA"
    assert native_terminal.schema_name == native_start.schema_name
    assert native_terminal.schema_digest == native_start.schema_digest
    assert native_terminal.token_usage is not None
    assert native_terminal.token_usage.provider_metadata is not None
    assert native_terminal.token_usage.provider_metadata.response_model == qwen.model
    assert legacy_start.structured_output_mode == "JSON_OBJECT"
    assert legacy_start.schema_name is None
    assert legacy_start.schema_digest is None
    assert legacy_terminal.structured_output_mode == "JSON_OBJECT"
    assert qwen.native_calls == [DIAGNOSIS_REPORT_OUTPUT_SPEC]
    assert qwen.legacy_calls == 1


@pytest.mark.anyio
async def test_instrumented_legacy_client_does_not_claim_native_capability() -> None:
    sink = InMemoryTraceSink()
    recorder = TraceRecorder(sink)
    deepseek = _LegacyDeepSeek()
    llm = InstrumentedLLM(deepseek)

    assert llm.supports_structured_output is False
    with trace_step_scope(
        recorder,
        trace_id="trace-deepseek",
        agent_run_id="run-deepseek",
        agent_step_id="step-deepseek",
        prompt=PromptIdentity(name="testcase", version="v1"),
    ):
        from app.clients.llm import complete_with_structured_output

        result = await complete_with_structured_output(
            llm,
            "legacy is allowed",
            output_spec=TESTCASE_CANDIDATE_OUTPUT_SPEC,
        )

    assert result == '{"legacy":true}'
    assert deepseek.calls == 1
    records = [record for record in recorder.typed_records if record.record_type == "model_call"]
    assert records[0].structured_output_mode == "JSON_OBJECT"
    assert records[-1].structured_output_mode == "JSON_OBJECT"
