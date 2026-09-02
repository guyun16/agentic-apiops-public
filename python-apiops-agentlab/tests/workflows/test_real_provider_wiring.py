from __future__ import annotations

import json

import httpx
import pytest

from app.clients.deepseek import DeepSeekClient, DeepSeekHttpError
from app.clients.llm import LLMClient


@pytest.mark.anyio
async def test_deepseek_adapter_uses_existing_protocol_and_json_mode() -> None:
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": '{"status":"ok"}'}}]},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        client = DeepSeekClient(
            http_client,
            api_key="test-key",
            base_url="https://api.deepseek.test/",
            model="deepseek-v4-flash",
            timeout_seconds=2,
        )
        assert isinstance(client, LLMClient)
        result = await client.complete("Return one JSON object.")

    request = requests[0]
    assert result == '{"status":"ok"}'
    assert str(request.url) == "https://api.deepseek.test/chat/completions"
    assert request.headers["authorization"] == "Bearer test-key"
    payload = json.loads(request.content)
    assert payload["model"] == "deepseek-v4-flash"
    assert payload["response_format"] == {"type": "json_object"}
    assert payload["thinking"] == {"type": "disabled"}


@pytest.mark.anyio
async def test_deepseek_http_failure_does_not_expose_response_body() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"secret": "must-not-leak"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        client = DeepSeekClient(
            http_client,
            api_key="test-key",
            base_url="https://api.deepseek.test",
            model="deepseek-v4-flash",
            timeout_seconds=2,
        )
        with pytest.raises(DeepSeekHttpError) as captured:
            await client.complete("Return JSON.")

    error = captured.value
    assert error.status_code == 401
    assert str(error) == "DeepSeek request returned HTTP 401"
    assert "must-not-leak" not in str(error)
