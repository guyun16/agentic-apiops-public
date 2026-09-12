from __future__ import annotations

from app.benchmark.models import TaskType
from app.benchmark.provider_integrity import verify_provider_integrity
from app.benchmark.runner import (
    BenchmarkExecutionMode,
    BenchmarkLifecycleStatus,
    BenchmarkTaskResult,
    BenchmarkTaskStatus,
    FormalEvidenceSnapshot,
    JavaExecutionStatus,
)

EXPECTED_MODEL = "qwen3.8-max"


def _call(
    call_id: str,
    *,
    provider: str = "Qwen",
    model: str = EXPECTED_MODEL,
    response_model: str | None = EXPECTED_MODEL,
    request_id: str | None = "request-1",
) -> dict[str, object]:
    return {
        "record_type": "model_call",
        "event": "TERMINAL",
        "status": "SUCCESS",
        "model_call_id": call_id,
        "model_identity": {"provider": provider, "model": model},
        "token_usage": {
            "provider_metadata": {
                "provider_request_id": request_id,
                "response_model": response_model,
            }
        },
    }


def _result(
    task_id: str,
    *,
    call_ids: tuple[str, ...] = (),
    calls: tuple[dict[str, object], ...] = (),
) -> BenchmarkTaskResult:
    return BenchmarkTaskResult(
        evaluationRunId="evaluation_run:provider-integrity",
        benchmarkTaskId=task_id,
        taskType=TaskType.FAILURE_DIAGNOSIS,
        status=BenchmarkTaskStatus.SUCCESS,
        executionMode=BenchmarkExecutionMode.REAL_MODEL,
        javaExecutionStatus=JavaExecutionStatus.NOT_APPLICABLE,
        agentRunId=f"agent_run:{task_id}",
        traceId=f"trace:{task_id}",
        modelCallIds=call_ids,
        modelCallCount=len(call_ids),
        formalEvidence=FormalEvidenceSnapshot(traceEvidence=calls),
        caseId=f"case:{task_id}",
        setupStatus=BenchmarkLifecycleStatus.SUCCESS,
        cleanupStatus=BenchmarkLifecycleStatus.SUCCESS,
        durationMs=1.0,
    )


def _verify(*results: BenchmarkTaskResult) -> dict[str, object]:
    return verify_provider_integrity(
        results,
        expected_provider="Qwen",
        expected_model=EXPECTED_MODEL,
    )


def test_legitimate_no_model_call_is_not_silent_fallback() -> None:
    evidence = _verify(_result("no-call"))

    assert evidence["status"] == "NO_MODEL_CALL"
    assert evidence["noModelCallTaskIds"] == ["no-call"]
    assert evidence["silentFallbackDetected"] is False


def test_missing_per_call_trace_is_provider_unproven_not_fallback() -> None:
    evidence = _verify(_result("legacy", call_ids=("model-call-1",)))

    assert evidence["status"] == "PROVIDER_UNPROVEN"
    assert evidence["unprovenTaskIds"] == ["legacy"]
    assert evidence["silentFallbackDetected"] is False


def test_actual_qwen_response_proves_provider_while_no_call_task_remains_valid() -> None:
    evidence = _verify(
        _result("qwen", call_ids=("model-call-1",), calls=(_call("model-call-1"),)),
        _result("approval-no-call"),
    )

    assert evidence["status"] == "PROVIDER_PROVEN"
    assert evidence["provenTaskIds"] == ["qwen"]
    assert evidence["noModelCallTaskIds"] == ["approval-no-call"]
    assert evidence["callsWithResponseProof"] == 1
    assert evidence["silentFallbackDetected"] is False


def test_single_unexpected_provider_is_mismatch_not_claimed_fallback() -> None:
    evidence = _verify(
        _result(
            "mismatch",
            call_ids=("model-call-1",),
            calls=(
                _call(
                    "model-call-1",
                    provider="DeepSeek",
                    model="deepseek-v4-flash",
                    response_model="deepseek-v4-flash",
                ),
            ),
        )
    )

    assert evidence["status"] == "PROVIDER_MISMATCH"
    assert evidence["silentFallbackDetected"] is False


def test_mixed_expected_and_unexpected_calls_are_actual_fallback() -> None:
    evidence = _verify(
        _result("qwen", call_ids=("qwen-1",), calls=(_call("qwen-1"),)),
        _result(
            "fallback",
            call_ids=("deepseek-1",),
            calls=(
                _call(
                    "deepseek-1",
                    provider="DeepSeek",
                    model="deepseek-v4-flash",
                    response_model="deepseek-v4-flash",
                ),
            ),
        ),
    )

    assert evidence["status"] == "ACTUAL_FALLBACK"
    assert evidence["silentFallbackDetected"] is True


def test_configured_identity_without_response_proof_remains_unproven() -> None:
    evidence = _verify(
        _result(
            "unproven",
            call_ids=("model-call-1",),
            calls=(
                _call(
                    "model-call-1",
                    response_model=None,
                    request_id=None,
                ),
            ),
        )
    )

    assert evidence["status"] == "PROVIDER_UNPROVEN"
    assert evidence["silentFallbackDetected"] is False
