"""Shared provider selection for the existing provider-neutral LLM boundary."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import httpx

from app.clients.deepseek import DeepSeekClient
from app.clients.llm import LLMClient
from app.clients.qwen import QwenClient
from app.core.errors import ApplicationError
from app.core.settings import AppSettings

LLMProviderName = Literal["deepseek", "qwen"]


@dataclass(frozen=True, slots=True)
class LLMProviderIdentity:
    """Non-secret provider/model identity for one LLM execution."""

    provider: str
    model: str


def normalize_provider(value: str) -> LLMProviderName:
    """Accept only the two explicitly supported provider names."""

    if value == "deepseek":
        return "deepseek"
    if value == "qwen":
        return "qwen"
    raise ValueError("unsupported LLM provider")


def provider_identity(settings: AppSettings, provider: str) -> LLMProviderIdentity:
    """Resolve a selected provider into its configured non-secret identity."""

    normalized = normalize_provider(provider)
    if normalized == "deepseek":
        return LLMProviderIdentity(provider="DeepSeek", model=settings.deepseek_model)
    return LLMProviderIdentity(provider="Qwen", model=settings.qwen_model)


def require_provider_credentials(settings: AppSettings, provider: str) -> None:
    """Require the selected provider key without exposing its value."""

    normalized = normalize_provider(provider)
    credential = settings.deepseek_api_key if normalized == "deepseek" else settings.qwen_api_key
    if credential is not None and credential.get_secret_value().strip():
        return
    provider_name = "DeepSeek" if normalized == "deepseek" else "Qwen"
    raise ApplicationError(
        f"{provider_name.upper()}_NOT_CONFIGURED",
        f"{provider_name} API key is not configured.",
        503,
    )


def build_llm(
    http_client: httpx.AsyncClient,
    settings: AppSettings,
    *,
    provider: str,
) -> LLMClient:
    """Build the selected concrete client behind the existing LLMClient protocol."""

    normalized = normalize_provider(provider)
    require_provider_credentials(settings, normalized)
    if normalized == "deepseek":
        api_key = settings.deepseek_api_key
        assert api_key is not None
        return DeepSeekClient(
            http_client,
            api_key=api_key.get_secret_value(),
            base_url=settings.deepseek_base_url,
            model=settings.deepseek_model,
            timeout_seconds=settings.deepseek_timeout_seconds,
        )
    api_key = settings.qwen_api_key
    assert api_key is not None
    return QwenClient(
        http_client,
        api_key=api_key.get_secret_value(),
        base_url=settings.qwen_base_url,
        model=settings.qwen_model,
        timeout_seconds=settings.qwen_timeout_seconds,
    )


__all__ = [
    "LLMProviderIdentity",
    "LLMProviderName",
    "build_llm",
    "normalize_provider",
    "provider_identity",
    "require_provider_credentials",
]
