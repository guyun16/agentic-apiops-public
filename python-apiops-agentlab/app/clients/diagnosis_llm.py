"""Minimal provider selection for the Diagnosis boundary."""

from __future__ import annotations

from dataclasses import dataclass

import httpx

from app.clients.llm import LLMClient
from app.clients.llm_provider import build_llm, provider_identity, require_provider_credentials
from app.core.settings import AppSettings


@dataclass(frozen=True, slots=True)
class DiagnosisLLMIdentity:
    """Non-secret provider/model identity for one Diagnosis execution."""

    provider: str
    model: str


def diagnosis_llm_identity(settings: AppSettings) -> DiagnosisLLMIdentity:
    """Resolve the configured Diagnosis provider into its trace identity."""

    identity = provider_identity(settings, settings.diagnosis_llm_provider)
    return DiagnosisLLMIdentity(provider=identity.provider, model=identity.model)


def require_diagnosis_llm_credentials(settings: AppSettings) -> None:
    """Require the selected provider key without exposing its value."""

    require_provider_credentials(settings, settings.diagnosis_llm_provider)


def build_diagnosis_llm(http_client: httpx.AsyncClient, settings: AppSettings) -> LLMClient:
    """Build the selected Diagnosis client behind the existing LLMClient boundary."""

    return build_llm(
        http_client,
        settings,
        provider=settings.diagnosis_llm_provider,
    )


__all__ = [
    "DiagnosisLLMIdentity",
    "build_diagnosis_llm",
    "diagnosis_llm_identity",
    "require_diagnosis_llm_credentials",
]
