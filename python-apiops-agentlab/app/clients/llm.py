"""Provider-neutral asynchronous language-model client protocol."""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class LLMClient(Protocol):
    """Minimal async boundary for a future language-model implementation."""

    async def complete(self, prompt: str) -> str:
        """Return a provider-neutral completion for a prompt."""
