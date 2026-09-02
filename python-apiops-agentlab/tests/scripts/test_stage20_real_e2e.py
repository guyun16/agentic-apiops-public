"""Deterministic checks for the Stage 20 cross-process harness boundary."""

from __future__ import annotations

import json

from app.tracing import (
    InMemoryTraceSink,
    ToolResultRecord,
    TraceRecorder,
    TraceStatus,
)
from scripts.stage20_real_e2e import (
    DiagnosisE2EConfig,
    FinalE2EConfig,
    RunnerFailureE2EConfig,
    _trace_tool_reference,
)


def test_final_environment_is_strict_configurable_and_does_not_expose_token(
    monkeypatch,
) -> None:
    token = "final-secret-token"
    for name, value in {
        "JAVA_APIOPS_BASE_URL": "http://127.0.0.1:54321",
        "JAVA_APIOPS_TOKEN": token,
        "STAGE20_PROJECT_ID": "42",
        "STAGE20_API_ID": "api-list-products",
        "STAGE20_TRACE_ID": "trace-final",
        "STAGE20_DEMO_ORDER_BASE_URL": "http://127.0.0.1:18080/",
        "STAGE20_RUNNER_READBACK_DEADLINE_SECONDS": "60",
    }.items():
        monkeypatch.setenv(name, value)

    config = FinalE2EConfig.from_environment()
    public_result = {
        "projectId": config.project_id,
        "apiId": config.api_id,
        "traceId": config.trace_id,
        "demoOrderBaseUrl": config.demo_order_base_url,
    }

    assert config.demo_order_base_url == "http://127.0.0.1:18080"
    assert config.readback_deadline_seconds == 60
    assert token not in json.dumps(public_result)


def test_diagnosis_environment_is_strict_and_keeps_token_out_of_result(
    monkeypatch,
) -> None:
    token = "secret-token-that-must-not-be-emitted"
    values = {
        "JAVA_APIOPS_BASE_URL": "http://127.0.0.1:54321",
        "JAVA_APIOPS_TOKEN": token,
        "STAGE20_PROJECT_ID": "42",
        "STAGE20_RUN_ID": "701",
        "STAGE20_TRACE_ID": "trace-cross-process",
    }
    for name, value in values.items():
        monkeypatch.setenv(name, value)

    config = DiagnosisE2EConfig.from_environment()
    public_result = {
        "projectId": config.project_id,
        "runId": config.run_id,
        "traceId": config.trace_id,
        "toolCallCount": 1,
        "rawFallbackUsed": False,
    }

    assert config.base_url == "http://127.0.0.1:54321"
    assert token not in json.dumps(public_result)


def test_tool_call_id_is_read_back_from_the_existing_trace_recorder() -> None:
    sink = InMemoryTraceSink()
    recorder = TraceRecorder(sink)
    recorder.record(
        ToolResultRecord(
            trace_id="trace-cross-process",
            agent_run_id="agent-cross-process",
            agent_step_id="step-cross-process",
            project_id=42,
            status=TraceStatus.SUCCESS,
            tool_name="rag.search",
            java_tool_call_id="java-runtime-generated-id",
            result_summary="sanitized digest only",
            sanitized=True,
            truncated=False,
        )
    )

    record, rag_query_id = _trace_tool_reference(sink.records)

    assert record["java_tool_call_id"] == "java-runtime-generated-id"
    assert record["agent_step_id"] == "step-cross-process"
    assert rag_query_id is None


def test_runner_failure_environment_requires_validated_dsl_and_keeps_deadline_configurable(
    monkeypatch,
) -> None:
    testcase = json.dumps(
        {
            "schemaVersion": "1.0.0",
            "caseId": "runner-failure",
            "projectId": 42,
            "apiId": "api",
            "name": "runner failure",
            "environment": {"baseUrl": "http://127.0.0.1:1", "variables": {}},
            "steps": [
                {
                    "stepId": "status",
                    "name": "status",
                    "request": {"method": "GET", "path": "/"},
                    "assertions": [{"type": "STATUS_CODE", "expected": 201}],
                    "extractors": [],
                }
            ],
        }
    )
    for name, value in {
        "JAVA_APIOPS_BASE_URL": "http://127.0.0.1:54321",
        "JAVA_APIOPS_TOKEN": "secret-token",
        "STAGE20_PROJECT_ID": "42",
        "STAGE20_TRACE_ID": "trace-runner-failure",
        "STAGE20_TESTCASE_JSON": testcase,
        "STAGE20_RUNNER_READBACK_DEADLINE_SECONDS": "60",
    }.items():
        monkeypatch.setenv(name, value)

    config = RunnerFailureE2EConfig.from_environment()

    assert config.project_id == 42
    assert config.readback_deadline_seconds == 60
    assert config.testcase_json == testcase
    public_result = {
        "projectId": config.project_id,
        "traceId": config.trace_id,
        "readbackDeadlineSeconds": config.readback_deadline_seconds,
    }
    assert "secret-token" not in json.dumps(public_result)
