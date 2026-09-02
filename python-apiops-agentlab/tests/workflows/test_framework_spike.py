"""Deterministic tests for the Stage 15 framework component spike."""

from __future__ import annotations

import asyncio
from typing import get_type_hints

import pytest
from pydantic import ValidationError

from app.clients.llm import LLMClient
from app.workflows.framework_spike import (
    DeterministicFakeLLM,
    OperationCandidate,
    normalize_operation_id,
    render_candidate_prompt,
    run_candidate_spike,
)


def test_fake_uses_existing_llm_protocol_and_prompt_template() -> None:
    fake = DeterministicFakeLLM('{"operation_id":"list_users","method":"GET"}')

    assert isinstance(fake, LLMClient)

    candidate = asyncio.run(run_candidate_spike(fake, operation_id="list_users", http_method="GET"))

    assert candidate == OperationCandidate(operation_id="list_users", method="GET")
    assert fake.prompts == [render_candidate_prompt(operation_id="list_users", http_method="GET")]
    assert "list_users" in fake.prompts[0]
    assert "GET" in fake.prompts[0]


@pytest.mark.parametrize(
    "response",
    [
        '{"operation_id":"list_users","method":"TRACE"}',
        '{"method":"GET"}',
        '{"operation_id":"list_users"}',
    ],
)
def test_invalid_structured_candidate_is_rejected(response: str) -> None:
    fake = DeterministicFakeLLM(response)

    with pytest.raises(ValidationError):
        asyncio.run(run_candidate_spike(fake, operation_id="list_users", http_method="GET"))


def test_candidate_rejects_unknown_fields() -> None:
    fake = DeterministicFakeLLM('{"operation_id":"list_users","method":"GET","extra":"nope"}')

    with pytest.raises(ValidationError):
        asyncio.run(run_candidate_spike(fake, operation_id="list_users", http_method="GET"))


def test_normalize_operation_id_is_typed_deterministic_and_local() -> None:
    hints = get_type_hints(normalize_operation_id)

    assert hints == {"operation_id": str, "return": str}
    assert normalize_operation_id("  List-Users / V1  ") == "list_users_v1"
    assert normalize_operation_id("  List-Users / V1  ") == "list_users_v1"
