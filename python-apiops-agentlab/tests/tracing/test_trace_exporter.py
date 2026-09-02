from __future__ import annotations

import json

import pytest

from app.tracing import (
    AgentRun,
    AgentStep,
    IdentityAuthority,
    InMemoryTraceSink,
    JsonlTraceSink,
    ModelCall,
    ModelIdentity,
    ParentIdentity,
    PromptIdentity,
    TraceEvent,
    TraceExportLimitError,
    TraceLimits,
    TraceRecorder,
    TraceStatus,
    digest_payload,
    read_trace_jsonl,
)


def _start_run(*, sequence: int | None = None) -> AgentRun:
    return AgentRun(
        trace_id="trace-export",
        agent_run_id="run-export",
        event=TraceEvent.START,
        status=TraceStatus.RUNNING,
        sequence=sequence,
    )


def test_jsonl_append_and_typed_readback_preserve_identity_parent_and_sequence(
    tmp_path,
) -> None:
    path = tmp_path / "trace.jsonl"
    sink = JsonlTraceSink(path)
    recorder = TraceRecorder(sink)
    recorder.record(_start_run())
    recorder.record(
        AgentStep(
            trace_id="trace-export",
            agent_run_id="run-export",
            agent_step_id="step-generate",
            step_type="generation",
            parent_identity=ParentIdentity(
                authority=IdentityAuthority.PYTHON,
                kind="agent_run",
                identity="run-export",
            ),
            event=TraceEvent.START,
            status=TraceStatus.RUNNING,
        )
    )
    recorder.record(
        ModelCall(
            trace_id="trace-export",
            agent_run_id="run-export",
            agent_step_id="step-generate",
            parent_identity=ParentIdentity(
                authority=IdentityAuthority.PYTHON,
                kind="agent_step",
                identity="step-generate",
            ),
            event=TraceEvent.START,
            status=TraceStatus.RUNNING,
            model_call_id="model-call-export",
            model_identity=ModelIdentity(provider="fake", model="fake-model"),
            prompt=PromptIdentity(name="testcase_generate", version="v1"),
            model_input=digest_payload({"prompt": "bounded"}),
        )
    )

    records = read_trace_jsonl(path)

    assert [record.sequence for record in records] == [1, 2, 3]
    assert isinstance(records[0], AgentRun)
    assert isinstance(records[1], AgentStep)
    assert isinstance(records[2], ModelCall)
    assert records[2].agent_run_id == "run-export"
    assert records[2].agent_step_id == "step-generate"
    assert records[2].parent_identity is not None
    assert records[2].parent_identity.identity == "step-generate"
    assert len(path.read_text(encoding="utf-8").splitlines()) == 3


def test_jsonl_physical_line_order_is_not_logical_order_authority(tmp_path) -> None:
    path = tmp_path / "out-of-order.jsonl"
    sink = JsonlTraceSink(path)
    terminal = AgentRun(
        trace_id="trace-order",
        agent_run_id="run-order",
        event=TraceEvent.TERMINAL,
        status=TraceStatus.SUCCESS,
        sequence=2,
    )
    start = _start_run(sequence=1).model_copy(
        update={"trace_id": "trace-order", "agent_run_id": "run-order"}
    )
    sink.write(terminal.model_dump(mode="json", exclude_none=False))
    sink.write(start.model_dump(mode="json", exclude_none=False))

    physical = read_trace_jsonl(path)
    logical = tuple(sorted(physical, key=lambda record: record.sequence or 0))

    assert [record.sequence for record in physical] == [2, 1]
    assert [record.sequence for record in logical] == [1, 2]
    assert logical[0].agent_run_id == logical[1].agent_run_id == "run-order"


def test_exporter_redacts_sensitive_summary_and_enforces_record_and_file_limits(tmp_path) -> None:
    record = AgentRun(
        trace_id="trace-secret",
        agent_run_id="run-secret",
        event=TraceEvent.START,
        status=TraceStatus.RUNNING,
    )
    sink = JsonlTraceSink(tmp_path / "safe.jsonl")
    sink.write(
        record.model_copy(
            update={"sequence": 1},
        ).model_dump(mode="json", exclude_none=False)
        | {"summary": "Authorization: Bearer test-token-placeholder"}
    )
    contents = (tmp_path / "safe.jsonl").read_text(encoding="utf-8")
    assert "test-token-placeholder" not in contents
    assert "[REDACTED]" in contents

    oversized = JsonlTraceSink(
        tmp_path / "oversized.jsonl",
        limits=TraceLimits(max_record_bytes=100),
    )
    with pytest.raises(TraceExportLimitError):
        oversized.write(
            record.model_copy(update={"sequence": 1}).model_dump(mode="json", exclude_none=False)
        )

    bounded_file = JsonlTraceSink(tmp_path / "bounded.jsonl", max_file_bytes=10)
    with pytest.raises(TraceExportLimitError):
        bounded_file.write(
            record.model_copy(update={"sequence": 1}).model_dump(mode="json", exclude_none=False)
        )


def test_exporter_serialization_is_single_line_json() -> None:
    sink = InMemoryTraceSink()
    recorder = TraceRecorder(sink)
    recorder.record(_start_run())

    assert json.dumps(sink.records[0], ensure_ascii=False).count("\n") == 0
