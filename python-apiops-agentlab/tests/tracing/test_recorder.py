from app.tracing import (
    AgentRun,
    InMemoryTraceSink,
    ToolResultRecord,
    TraceLimits,
    TraceRecorder,
    TraceStatus,
    digest_payload,
)


def running_run() -> AgentRun:
    return AgentRun(
        trace_id="trace-1",
        agent_run_id="run-1",
        status=TraceStatus.RUNNING,
    )


def test_recorder_assigns_per_run_monotonic_sequence_and_returns_no_route_boolean() -> None:
    sink = InMemoryTraceSink()
    recorder = TraceRecorder(sink)

    assert recorder.record(running_run()) is None
    recorder.record(running_run())

    assert [record["sequence"] for record in sink.records] == [1, 2]
    assert recorder.accepted_records == 2
    assert recorder.degraded is False


def test_recorder_preserves_parent_and_redacts_serialized_summary() -> None:
    sink = InMemoryTraceSink()
    recorder = TraceRecorder(sink)
    result = ToolResultRecord(
        trace_id="trace-1",
        agent_run_id="run-1",
        tool_name="rag.search",
        result_summary="Authorization: Bearer test-token-placeholder",
        sanitized=True,
        truncated=False,
        status=TraceStatus.SUCCESS,
    )

    recorder.record(result)
    stored = sink.records[0]

    assert stored["sequence"] == 1
    assert "test-token-placeholder" not in str(stored)


def test_recorder_stops_after_per_run_record_limit() -> None:
    sink = InMemoryTraceSink()
    recorder = TraceRecorder(
        sink,
        limits=TraceLimits(max_run_records=2),
    )

    recorder.record(running_run())
    recorder.record(running_run())
    recorder.record(running_run())

    assert len(sink.records) == 2
    assert recorder.degraded is True
    assert any("run_record_count_limit" in reason for reason in recorder.degradation_reasons)


def test_recorder_stops_after_single_record_size_limit() -> None:
    sink = InMemoryTraceSink()
    recorder = TraceRecorder(
        sink,
        limits=TraceLimits(max_record_bytes=200),
    )

    recorder.record(running_run())
    recorder.record(running_run())

    assert sink.records == ()
    assert recorder.degraded is True
    assert any("single_record_size_limit" in reason for reason in recorder.degradation_reasons)


def test_recorder_stops_when_run_byte_limit_would_be_exceeded() -> None:
    sink = InMemoryTraceSink()
    recorder = TraceRecorder(
        sink,
        limits=TraceLimits(max_run_bytes=500),
    )

    recorder.record(running_run())
    recorder.record(running_run())

    assert len(sink.records) == 1
    assert any("run_size_limit" in reason for reason in recorder.degradation_reasons)


class FailingSink:
    def __init__(self) -> None:
        self.calls = 0

    def write(self, record: dict[str, object]) -> None:
        self.calls += 1
        raise RuntimeError("sink is unavailable")


def test_sink_exception_is_contained_without_retrying_business_fact() -> None:
    sink = FailingSink()
    recorder = TraceRecorder(sink)

    recorder.record(running_run())

    assert sink.calls == 1
    assert recorder.degraded is True
    assert recorder.accepted_records == 1
    assert len(recorder.typed_records) == 1
    assert recorder.typed_records[0].sequence == 1


class FailOnceSink:
    def __init__(self) -> None:
        self.calls = 0
        self.persisted: list[dict[str, object]] = []

    def write(self, record: dict[str, object]) -> None:
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError("first write is unavailable")
        self.persisted.append(dict(record))


def test_sequence_continues_after_persistence_failure_without_retry() -> None:
    sink = FailOnceSink()
    recorder = TraceRecorder(sink)

    recorder.record(running_run())
    recorder.record(running_run())

    assert sink.calls == 2
    assert recorder.degraded is True
    assert recorder.accepted_records == 2
    assert [record.sequence for record in recorder.typed_records] == [1, 2]
    assert [record["sequence"] for record in sink.persisted] == [2]


def test_java_tool_call_id_is_preserved_and_never_fabricated() -> None:
    sink = InMemoryTraceSink()
    recorder = TraceRecorder(sink)
    java_result = ToolResultRecord(
        trace_id="trace-1",
        agent_run_id="run-1",
        tool_name="rag.search",
        java_tool_call_id="java-authority-call-1",
        result_summary=digest_payload({"status": "ok"}).summary,
        sanitized=True,
        truncated=False,
        status=TraceStatus.SUCCESS,
    )
    no_java_result = ToolResultRecord(
        trace_id="trace-1",
        agent_run_id="run-1",
        tool_name="rag.search",
        sanitized=True,
        truncated=False,
        status=TraceStatus.SUCCESS,
    )

    recorder.record(java_result)
    recorder.record(no_java_result)
    records = sink.records

    assert records[0]["java_tool_call_id"] == "java-authority-call-1"
    assert records[1]["java_tool_call_id"] is None
