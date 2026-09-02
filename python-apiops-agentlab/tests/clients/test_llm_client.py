"""Deterministic tests for the provider-neutral LLM protocol."""

from __future__ import annotations

import asyncio

from app.clients.llm import LLMClient


class FakeLLMClient:
    async def complete(self, prompt: str) -> str:
        return f"fake:{prompt}"


async def consume(client: LLMClient) -> str:
    return await client.complete("hello")


def test_fake_can_be_substituted_for_llm_protocol() -> None:
    fake = FakeLLMClient()

    assert isinstance(fake, LLMClient)
    assert asyncio.run(consume(fake)) == "fake:hello"
