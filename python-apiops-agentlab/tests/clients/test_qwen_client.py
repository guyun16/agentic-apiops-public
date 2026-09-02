"""Deterministic tests for the Qwen provider adapter."""

from __future__ import annotations

import httpx
import pytest

from app.clients.llm import LLMClient
from app.clients.qwen import (
    QwenClient,
    QwenHttpError,
    QwenResponseError,
    QwenTimeoutError,
    QwenTransportError,
)


def _client(handler: httpx.MockTransportHandler) -> tuple[QwenClient, httpx.AsyncClient]:
    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return (
        QwenClient(
            http_client,
            api_key="fake-qwen-key",
            base_url="https://qwen.example.test/compatible-mode/v1/",
            model="qwen3.7-plus-2026-05-26",
            timeout_seconds=60.0,
        ),
        http_client,
    )


@pytest.mark.anyio
async def test_completion_uses_frozen_request_and_records_metadata() -> None:
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            headers={"x-request-id": "qwen-request-1"},
            json={
                "id": "completion-1",
                "model": "qwen3.7-plus-2026-05-26",
                "choices": [
                    {
                        "message": {"content": '{"ok":true}'},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": 11,
                    "completion_tokens": 7,
                    "total_tokens": 18,
                },
            },
        )

    client, http_client = _client(handler)
    try:
        result = await client.complete("Return one JSON object.")
    finally:
        await http_client.aclose()

    assert isinstance(client, LLMClient)
    assert result == '{"ok":true}'
    assert client.provider == "Qwen"
    assert client.model == "qwen3.7-plus-2026-05-26"
    assert len(requests) == 1
    request = requests[0]
    assert str(request.url) == (
        "https://qwen.example.test/compatible-mode/v1/chat/completions"
    )
    assert request.headers["Authorization"] == "Bearer fake-qwen-key"
    assert request.headers["Content-Type"] == "application/json"
    body = request.read()
    assert b"temperature" not in body
    assert b"top_p" not in body
    assert b"seed" not in body
    payload = httpx.Response(200, content=body).json()
    assert payload == {
        "model": "qwen3.7-plus-2026-05-26",
        "messages": [{"role": "user", "content": "Return one JSON object."}],
        "response_format": {"type": "json_object"},
        "enable_thinking": False,
        "stream": False,
    }
    assert client.last_completion_metadata is not None
    assert client.last_completion_metadata.provider_request_id == "qwen-request-1"
    assert client.last_completion_metadata.finish_reason == "stop"
    assert client.last_completion_metadata.prompt_tokens == 11
    assert client.last_completion_metadata.completion_tokens == 7
    assert client.last_completion_metadata.total_tokens == 18
    assert client.last_completion_metadata.model == "qwen3.7-plus-2026-05-26"


@pytest.mark.anyio
async def test_non_success_http_response_raises_qwen_http_error() -> None:
    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"message": "not retained"})

    client, http_client = _client(handler)
    try:
        with pytest.raises(QwenHttpError) as captured:
            await client.complete("Return JSON.")
    finally:
        await http_client.aclose()

    assert captured.value.status_code == 429


@pytest.mark.anyio
async def test_timeout_raises_qwen_timeout_error() -> None:
    async def handler(_: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out")

    client, http_client = _client(handler)
    try:
        with pytest.raises(QwenTimeoutError):
            await client.complete("Return JSON.")
    finally:
        await http_client.aclose()


@pytest.mark.anyio
async def test_transport_failure_raises_qwen_transport_error() -> None:
    async def handler(_: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("transport failed")

    client, http_client = _client(handler)
    try:
        with pytest.raises(QwenTransportError):
            await client.complete("Return JSON.")
    finally:
        await http_client.aclose()


@pytest.mark.anyio
@pytest.mark.parametrize(
    "payload",
    (
        {},
        {"choices": []},
        {"choices": [{"message": {"content": 7}}]},
    ),
)
async def test_malformed_envelope_raises_qwen_response_error(
    payload: dict[str, object],
) -> None:
    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    client, http_client = _client(handler)
    try:
        with pytest.raises(QwenResponseError):
            await client.complete("Return JSON.")
    finally:
        await http_client.aclose()


@pytest.mark.anyio
async def test_empty_content_raises_qwen_response_error() -> None:
    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "   "}}]},
        )

    client, http_client = _client(handler)
    try:
        with pytest.raises(QwenResponseError):
            await client.complete("Return JSON.")
    finally:
        await http_client.aclose()
