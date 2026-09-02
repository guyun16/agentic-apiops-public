"""DeepSeek adapter for the existing provider-neutral LLMClient boundary."""

from __future__ import annotations

from dataclasses import dataclass

import httpx
from pydantic import BaseModel, ConfigDict, StrictInt, StrictStr, ValidationError


class DeepSeekError(RuntimeError):
    """Base class for stable DeepSeek provider failures."""


class DeepSeekHttpError(DeepSeekError):
    """DeepSeek returned a non-success HTTP response."""

    def __init__(self, status_code: int) -> None:
        self.status_code = status_code
        super().__init__(f"DeepSeek request returned HTTP {status_code}")


class DeepSeekTimeoutError(DeepSeekError):
    """DeepSeek exceeded its configured timeout."""


class DeepSeekTransportError(DeepSeekError):
    """DeepSeek failed before returning an HTTP response."""


class DeepSeekResponseError(DeepSeekError):
    """DeepSeek returned an unusable completion response."""


@dataclass(frozen=True, slots=True)
class DeepSeekCompletionMetadata:
    """Non-secret provider facts from the most recent completion."""

    provider_request_id: str | None = None
    finish_reason: str | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None
    model: str | None = None


class _Message(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)

    content: StrictStr


class _Choice(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)

    message: _Message
    finish_reason: StrictStr | None = None


class _Usage(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)

    prompt_tokens: StrictInt | None = None
    completion_tokens: StrictInt | None = None
    total_tokens: StrictInt | None = None


class _ChatCompletion(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)

    choices: list[_Choice]
    id: StrictStr | None = None
    model: StrictStr | None = None
    usage: _Usage | None = None


class DeepSeekClient:
    """Minimal async DeepSeek implementation of ``LLMClient``."""

    def __init__(
        self,
        http_client: httpx.AsyncClient,
        *,
        api_key: str,
        base_url: str,
        model: str,
        timeout_seconds: float,
    ) -> None:
        for name, value in (
            ("api_key", api_key),
            ("base_url", base_url),
            ("model", model),
        ):
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must be a non-empty string")
        if (
            isinstance(timeout_seconds, bool)
            or not isinstance(timeout_seconds, (int, float))
            or timeout_seconds <= 0
        ):
            raise ValueError("timeout_seconds must be greater than zero")

        self._http_client = http_client
        self._api_key = api_key.strip()
        self._base_url = base_url.rstrip("/")
        self._model = model.strip()
        self._timeout_seconds = float(timeout_seconds)
        self._last_completion_metadata: DeepSeekCompletionMetadata | None = None

    @property
    def provider(self) -> str:
        """Return the stable non-secret provider identity for tracing."""

        return "DeepSeek"

    @property
    def last_completion_metadata(self) -> DeepSeekCompletionMetadata | None:
        """Return provider facts observed for the most recent request."""

        return self._last_completion_metadata

    @property
    def model(self) -> str:
        """Return the non-secret configured model name for evidence."""

        return self._model

    async def complete(self, prompt: str) -> str:
        """Return one JSON-mode completion through the provider-neutral signature."""

        if not isinstance(prompt, str) or not prompt.strip():
            raise ValueError("prompt must be a non-empty string")
        self._last_completion_metadata = None
        try:
            response = await self._http_client.post(
                f"{self._base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self._model,
                    "messages": [{"role": "user", "content": prompt}],
                    "response_format": {"type": "json_object"},
                    "thinking": {"type": "disabled"},
                    "stream": False,
                },
                timeout=self._timeout_seconds,
            )
        except httpx.TimeoutException as exc:
            raise DeepSeekTimeoutError("DeepSeek request timed out") from exc
        except httpx.TransportError as exc:
            raise DeepSeekTransportError("DeepSeek request failed during transport") from exc

        if not 200 <= response.status_code < 300:
            raise DeepSeekHttpError(response.status_code)
        try:
            completion = _ChatCompletion.model_validate(response.json())
            choice = completion.choices[0]
            content = choice.message.content
        except (ValueError, ValidationError, IndexError) as exc:
            raise DeepSeekResponseError("DeepSeek returned an invalid completion") from exc
        if not content.strip():
            raise DeepSeekResponseError("DeepSeek returned an empty completion")
        usage = completion.usage
        self._last_completion_metadata = DeepSeekCompletionMetadata(
            provider_request_id=response.headers.get("x-request-id")
            or response.headers.get("request-id")
            or completion.id,
            finish_reason=choice.finish_reason,
            prompt_tokens=usage.prompt_tokens if usage is not None else None,
            completion_tokens=usage.completion_tokens if usage is not None else None,
            total_tokens=usage.total_tokens if usage is not None else None,
            model=completion.model,
        )
        return content


__all__ = [
    "DeepSeekClient",
    "DeepSeekCompletionMetadata",
    "DeepSeekError",
    "DeepSeekHttpError",
    "DeepSeekResponseError",
    "DeepSeekTimeoutError",
    "DeepSeekTransportError",
]
