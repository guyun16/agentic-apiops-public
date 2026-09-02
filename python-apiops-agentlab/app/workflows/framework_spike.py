"""Minimal deterministic spike for framework component boundaries."""

from __future__ import annotations

import re
from typing import Literal

from langchain_core.prompts import PromptTemplate
from pydantic import BaseModel, ConfigDict, Field

from app.clients.llm import LLMClient

CandidateMethod = Literal["GET", "POST", "PUT", "PATCH", "DELETE"]

CANDIDATE_PROMPT = PromptTemplate.from_template(
    "Return one operation candidate as JSON with operation_id and method. "
    "Input operation_id={operation_id}; HTTP method={http_method}."
)


class OperationCandidate(BaseModel):
    """Local experiment type; it is not a shared TestCase Contract."""

    model_config = ConfigDict(extra="forbid", strict=True)

    operation_id: str = Field(min_length=1)
    method: CandidateMethod


class DeterministicFakeLLM:
    """A provider-free LLMClient implementation for deterministic tests."""

    def __init__(self, response: str) -> None:
        self._response = response
        self.prompts: list[str] = []

    async def complete(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return self._response


def render_candidate_prompt(*, operation_id: str, http_method: str) -> str:
    """Render model input semantics without performing model or business work."""

    return CANDIDATE_PROMPT.format(operation_id=operation_id, http_method=http_method)


async def run_candidate_spike(
    llm: LLMClient,
    *,
    operation_id: str,
    http_method: str,
) -> OperationCandidate:
    """Call the existing LLM boundary and parse its output as a local candidate."""

    prompt = render_candidate_prompt(operation_id=operation_id, http_method=http_method)
    raw_output = await llm.complete(prompt)
    return OperationCandidate.model_validate_json(raw_output)


def normalize_operation_id(operation_id: str) -> str:
    """Normalize an operation id using only deterministic local string operations."""

    return re.sub(r"[^a-z0-9]+", "_", operation_id.strip().lower()).strip("_")


__all__ = [
    "CANDIDATE_PROMPT",
    "CandidateMethod",
    "DeterministicFakeLLM",
    "OperationCandidate",
    "normalize_operation_id",
    "render_candidate_prompt",
    "run_candidate_spike",
]
