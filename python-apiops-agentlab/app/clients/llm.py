"""Provider-neutral asynchronous language-model client protocol."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(frozen=True, slots=True)
class StructuredOutputSpec:
    """Provider-neutral description of one native structured-output request."""

    schema_name: str
    schema: Mapping[str, object]
    strict: bool = True

    def __post_init__(self) -> None:
        if not isinstance(self.schema_name, str) or not self.schema_name.strip():
            raise ValueError("schema_name must be a non-empty string")
        if not isinstance(self.schema, Mapping):
            raise TypeError("schema must be a mapping")
        if not isinstance(self.strict, bool):
            raise TypeError("strict must be a boolean")


@runtime_checkable
class LLMClient(Protocol):
    """Minimal async boundary for a future language-model implementation."""

    async def complete(self, prompt: str) -> str:
        """Return a provider-neutral completion for a prompt."""


@runtime_checkable
class StructuredLLMClient(LLMClient, Protocol):
    """Optional native structured-output capability."""

    async def complete_structured(
        self,
        prompt: str,
        *,
        output_spec: StructuredOutputSpec,
    ) -> str:
        """Return a completion constrained by the provider-native schema."""


async def complete_with_structured_output(
    llm: LLMClient,
    prompt: str,
    *,
    output_spec: StructuredOutputSpec,
    native_required: bool = False,
) -> str:
    """Use native structured output when available, otherwise apply explicit policy."""

    supports_native = getattr(llm, "supports_structured_output", None)
    if supports_native is not False and isinstance(llm, StructuredLLMClient):
        return await llm.complete_structured(prompt, output_spec=output_spec)
    if native_required:
        raise TypeError("native structured output is not supported by this LLM client")
    return await llm.complete(prompt)


__all__ = [
    "LLMClient",
    "StructuredLLMClient",
    "StructuredOutputSpec",
    "complete_with_structured_output",
]
