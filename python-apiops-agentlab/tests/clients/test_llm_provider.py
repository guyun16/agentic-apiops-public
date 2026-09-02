"""Deterministic tests for shared provider selection."""

from __future__ import annotations

import httpx
import pytest
from pydantic import SecretStr, ValidationError

from app.clients.deepseek import DeepSeekClient
from app.clients.llm_provider import (
    build_llm,
    provider_identity,
    require_provider_credentials,
)
from app.clients.qwen import QwenClient
from app.core.errors import ApplicationError
from app.core.settings import AppSettings


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("provider", "expected_type", "expected_name"),
    [
        ("deepseek", DeepSeekClient, "DeepSeek"),
        ("qwen", QwenClient, "Qwen"),
    ],
)
async def test_build_llm_selects_provider_and_identity(
    provider: str,
    expected_type: type[object],
    expected_name: str,
) -> None:
    settings = AppSettings(
        deepseek_api_key=SecretStr("test-deepseek-key"),
        qwen_api_key=SecretStr("test-qwen-key"),
    )

    async with httpx.AsyncClient(trust_env=False) as http_client:
        client = build_llm(http_client, settings, provider=provider)

    assert isinstance(client, expected_type)
    assert client.provider == expected_name  # type: ignore[attr-defined]
    assert client.model == (  # type: ignore[attr-defined]
        settings.deepseek_model if provider == "deepseek" else settings.qwen_model
    )


def test_provider_credentials_fail_closed_without_secret_value() -> None:
    with pytest.raises(ApplicationError) as captured:
        require_provider_credentials(AppSettings(), "qwen")

    assert captured.value.code == "QWEN_NOT_CONFIGURED"
    assert "API key" in captured.value.message
    assert "test-qwen" not in captured.value.message


def test_unknown_provider_is_rejected_by_resolver_and_settings() -> None:
    with pytest.raises(ValueError, match="unsupported LLM provider"):
        provider_identity(AppSettings(), "glm")
    with pytest.raises(ValidationError):
        AppSettings(testcase_llm_provider="glm")  # type: ignore[arg-type]
