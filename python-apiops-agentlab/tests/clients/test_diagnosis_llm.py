"""Deterministic tests for Diagnosis provider selection."""

from __future__ import annotations

import httpx
import pytest
from pydantic import SecretStr, ValidationError

from app.clients.deepseek import DeepSeekClient
from app.clients.diagnosis_llm import (
    build_diagnosis_llm,
    diagnosis_llm_identity,
    require_diagnosis_llm_credentials,
)
from app.clients.qwen import QwenClient
from app.core.errors import ApplicationError
from app.core.settings import AppSettings


def test_default_identity_is_existing_deepseek() -> None:
    settings = AppSettings(
        diagnosis_llm_provider="deepseek",
        deepseek_model="deepseek-v4-flash",
    )

    assert diagnosis_llm_identity(settings).provider == "DeepSeek"
    assert diagnosis_llm_identity(settings).model == "deepseek-v4-flash"


def test_qwen_identity_is_configured_snapshot() -> None:
    settings = AppSettings(diagnosis_llm_provider="qwen")

    assert diagnosis_llm_identity(settings).provider == "Qwen"
    assert diagnosis_llm_identity(settings).model == "qwen3.8-max"


def test_missing_deepseek_key_is_rejected_without_secret_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)

    with pytest.raises(ApplicationError) as captured:
        require_diagnosis_llm_credentials(AppSettings(diagnosis_llm_provider="deepseek"))

    assert captured.value.code == "DEEPSEEK_NOT_CONFIGURED"
    assert "API key" in captured.value.message


def test_missing_qwen_key_is_rejected_without_secret_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("QWEN_API_KEY", raising=False)

    with pytest.raises(ApplicationError) as captured:
        require_diagnosis_llm_credentials(AppSettings(diagnosis_llm_provider="qwen"))

    assert captured.value.code == "QWEN_NOT_CONFIGURED"
    assert "API key" in captured.value.message


@pytest.mark.anyio
async def test_factory_returns_selected_client() -> None:
    async with httpx.AsyncClient(trust_env=False) as http_client:
        deepseek = build_diagnosis_llm(
            http_client,
            AppSettings(
                diagnosis_llm_provider="deepseek",
                deepseek_api_key=SecretStr("fake-deepseek-key"),
            ),
        )
        qwen = build_diagnosis_llm(
            http_client,
            AppSettings(
                diagnosis_llm_provider="qwen",
                qwen_api_key=SecretStr("fake-qwen-key"),
            ),
        )

    assert isinstance(deepseek, DeepSeekClient)
    assert deepseek.provider == "DeepSeek"
    assert isinstance(qwen, QwenClient)
    assert qwen.provider == "Qwen"


def test_unknown_provider_is_rejected_by_settings_validation() -> None:
    with pytest.raises(ValidationError):
        AppSettings(diagnosis_llm_provider="glm")  # type: ignore[arg-type]
