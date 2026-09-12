"""Classify provider provenance from persisted per-call trace evidence."""

from __future__ import annotations

from collections.abc import Sequence
from enum import StrEnum
from typing import Any

from .runner import BenchmarkTaskResult


class ProviderIntegrityStatus(StrEnum):
    """Mutually exclusive provider-evidence outcomes for one persisted run."""

    PROVIDER_PROVEN = "PROVIDER_PROVEN"
    NO_MODEL_CALL = "NO_MODEL_CALL"
    PROVIDER_UNPROVEN = "PROVIDER_UNPROVEN"
    PROVIDER_MISMATCH = "PROVIDER_MISMATCH"
    ACTUAL_FALLBACK = "ACTUAL_FALLBACK"


def _text(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _terminal_model_calls(result: BenchmarkTaskResult) -> list[dict[str, Any]]:
    evidence = result.formal_evidence
    if evidence is None:
        return []
    calls: list[dict[str, Any]] = []
    for record in evidence.trace_evidence:
        if (
            record.get("record_type") == "model_call"
            and record.get("event") == "TERMINAL"
            and isinstance(record, dict)
        ):
            calls.append(record)
    return calls


def _call_identity(record: dict[str, Any]) -> tuple[str | None, str | None]:
    identity = record.get("model_identity")
    if not isinstance(identity, dict):
        return None, None
    return _text(identity.get("provider")), _text(identity.get("model"))


def _response_evidence(record: dict[str, Any]) -> tuple[str | None, str | None]:
    usage = record.get("token_usage")
    metadata = usage.get("provider_metadata") if isinstance(usage, dict) else None
    if not isinstance(metadata, dict):
        return None, None
    return _text(metadata.get("response_model")), _text(metadata.get("provider_request_id"))


def verify_provider_integrity(
    results: Sequence[BenchmarkTaskResult],
    *,
    expected_provider: str,
    expected_model: str,
) -> dict[str, object]:
    """Verify actual provider calls without treating legitimate no-call routes as fallback."""

    if not expected_provider.strip() or not expected_model.strip():
        raise ValueError("expected provider and model must be non-empty")
    expected_identity = (expected_provider.casefold(), expected_model)
    task_statuses: dict[str, ProviderIntegrityStatus] = {}
    observed_identities: set[tuple[str, str]] = set()
    observed_response_models: set[str] = set()
    total_terminal_calls = 0
    calls_with_response_proof = 0

    for result in results:
        terminal = _terminal_model_calls(result)
        if not result.model_call_ids and not terminal:
            task_statuses[result.benchmark_task_id] = ProviderIntegrityStatus.NO_MODEL_CALL
            continue
        if not terminal:
            task_statuses[result.benchmark_task_id] = ProviderIntegrityStatus.PROVIDER_UNPROVEN
            continue

        total_terminal_calls += len(terminal)
        expected_seen = False
        unexpected_seen = False
        incomplete_seen = False
        terminal_ids: set[str] = set()
        for record in terminal:
            call_id = _text(record.get("model_call_id"))
            if call_id is not None:
                terminal_ids.add(call_id)
            provider, model = _call_identity(record)
            response_model, request_id = _response_evidence(record)
            if provider is None or model is None:
                incomplete_seen = True
                continue
            identity = (provider.casefold(), model)
            observed_identities.add(identity)
            if response_model is not None:
                observed_response_models.add(response_model)
            configured_matches = identity == expected_identity
            response_matches = response_model == expected_model
            if configured_matches and response_matches and request_id is not None:
                expected_seen = True
                calls_with_response_proof += 1
            elif not configured_matches or (
                response_model is not None and not response_matches
            ):
                unexpected_seen = True
            else:
                incomplete_seen = True

        missing_terminal_ids = set(result.model_call_ids) - terminal_ids
        if expected_seen and unexpected_seen:
            status = ProviderIntegrityStatus.ACTUAL_FALLBACK
        elif unexpected_seen:
            status = ProviderIntegrityStatus.PROVIDER_MISMATCH
        elif incomplete_seen or missing_terminal_ids or not expected_seen:
            status = ProviderIntegrityStatus.PROVIDER_UNPROVEN
        else:
            status = ProviderIntegrityStatus.PROVIDER_PROVEN
        task_statuses[result.benchmark_task_id] = status

    values = set(task_statuses.values())
    mixed_identity = expected_identity in observed_identities and any(
        identity != expected_identity for identity in observed_identities
    )
    mixed_response_model = expected_model in observed_response_models and any(
        model != expected_model for model in observed_response_models
    )
    if ProviderIntegrityStatus.ACTUAL_FALLBACK in values or mixed_identity or mixed_response_model:
        overall = ProviderIntegrityStatus.ACTUAL_FALLBACK
    elif ProviderIntegrityStatus.PROVIDER_MISMATCH in values:
        overall = ProviderIntegrityStatus.PROVIDER_MISMATCH
    elif ProviderIntegrityStatus.PROVIDER_UNPROVEN in values:
        overall = ProviderIntegrityStatus.PROVIDER_UNPROVEN
    elif ProviderIntegrityStatus.PROVIDER_PROVEN in values:
        overall = ProviderIntegrityStatus.PROVIDER_PROVEN
    else:
        overall = ProviderIntegrityStatus.NO_MODEL_CALL

    def task_ids(status: ProviderIntegrityStatus) -> list[str]:
        return sorted(task_id for task_id, value in task_statuses.items() if value is status)

    return {
        "schemaVersion": "stage21-provider-integrity/v2",
        "status": overall.value,
        "expectedProvider": expected_provider,
        "expectedModel": expected_model,
        "taskCount": len(results),
        "terminalModelCallCount": total_terminal_calls,
        "callsWithResponseProof": calls_with_response_proof,
        "provenTaskIds": task_ids(ProviderIntegrityStatus.PROVIDER_PROVEN),
        "noModelCallTaskIds": task_ids(ProviderIntegrityStatus.NO_MODEL_CALL),
        "unprovenTaskIds": task_ids(ProviderIntegrityStatus.PROVIDER_UNPROVEN),
        "mismatchTaskIds": task_ids(ProviderIntegrityStatus.PROVIDER_MISMATCH),
        "actualFallbackTaskIds": task_ids(ProviderIntegrityStatus.ACTUAL_FALLBACK),
        "observedIdentities": [
            {"provider": provider, "model": model}
            for provider, model in sorted(observed_identities)
        ],
        "observedResponseModels": sorted(observed_response_models),
        "silentFallbackDetected": overall is ProviderIntegrityStatus.ACTUAL_FALLBACK,
    }


__all__ = ["ProviderIntegrityStatus", "verify_provider_integrity"]
