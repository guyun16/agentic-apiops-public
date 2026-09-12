"""Qwen adapter for the existing provider-neutral LLMClient boundary."""

from __future__ import annotations

from dataclasses import dataclass

import httpx
from pydantic import BaseModel, ConfigDict, StrictInt, StrictStr, ValidationError

from app.clients.llm import StructuredOutputSpec


class QwenError(RuntimeError):
    """Base class for stable Qwen provider failures."""


class QwenHttpError(QwenError):
    """Qwen returned a non-success HTTP response."""

    def __init__(self, status_code: int) -> None:
        self.status_code = status_code
        super().__init__(f"Qwen request returned HTTP {status_code}")


class QwenTimeoutError(QwenError):
    """Qwen exceeded its configured timeout."""


class QwenTransportError(QwenError):
    """Qwen failed before returning an HTTP response."""


class QwenResponseError(QwenError):
    """Qwen returned an unusable completion response."""


@dataclass(frozen=True, slots=True)
class QwenCompletionMetadata:
    """Non-secret provider facts from the most recent completion."""

    provider_request_id: str | None = None
    finish_reason: str | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None
    model: str | None = None
    structured_output_mode: str = "JSON_OBJECT"
    schema_name: str | None = None
    schema_digest: str | None = None


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


class QwenClient:
    """Minimal async Qwen implementation of ``LLMClient``."""

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
        self._last_completion_metadata: QwenCompletionMetadata | None = None

    @property
    def provider(self) -> str:
        """Return the stable non-secret provider identity for tracing."""

        return "Qwen"

    @property
    def last_completion_metadata(self) -> QwenCompletionMetadata | None:
        """Return provider facts observed for the most recent request."""

        return self._last_completion_metadata

    @property
    def model(self) -> str:
        """Return the non-secret configured model name for evidence."""

        return self._model

    async def complete(self, prompt: str) -> str:
        """Return one JSON-mode completion through the provider-neutral signature."""

        return await self._complete(
            prompt,
            response_format={"type": "json_object"},
            structured_output_mode="JSON_OBJECT",
            schema_name=None,
            schema_digest=None,
        )

    async def complete_structured(
        self,
        prompt: str,
        *,
        output_spec: StructuredOutputSpec,
    ) -> str:
        """Return one completion using Qwen's provider-native JSON Schema mode."""

        if not isinstance(output_spec, StructuredOutputSpec):
            raise TypeError("output_spec must be a StructuredOutputSpec")
        from app.clients.qwen_structured_output import schema_digest

        return await self._complete(
            prompt,
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": output_spec.schema_name,
                    "strict": output_spec.strict,
                    "schema": dict(output_spec.schema),
                },
            },
            structured_output_mode="JSON_SCHEMA",
            schema_name=output_spec.schema_name,
            schema_digest=schema_digest(output_spec.schema),
        )

    async def _complete(
        self,
        prompt: str,
        *,
        response_format: dict[str, object],
        structured_output_mode: str,
        schema_name: str | None,
        schema_digest: str | None,
    ) -> str:
        """Send one request while keeping legacy and native modes separate."""

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
                    "response_format": response_format,
                    "enable_thinking": False,
                    "stream": False,
                },
                timeout=self._timeout_seconds,
            )
        except httpx.TimeoutException as exc:
            raise QwenTimeoutError("Qwen request timed out") from exc
        except httpx.TransportError as exc:
            raise QwenTransportError("Qwen request failed during transport") from exc

        if not 200 <= response.status_code < 300:
            raise QwenHttpError(response.status_code)
        try:
            completion = _ChatCompletion.model_validate(response.json())
            choice = completion.choices[0]
            content = choice.message.content
        except (ValueError, ValidationError, IndexError) as exc:
            raise QwenResponseError("Qwen returned an invalid completion") from exc
        if not content.strip():
            raise QwenResponseError("Qwen returned an empty completion")
        usage = completion.usage
        self._last_completion_metadata = QwenCompletionMetadata(
            provider_request_id=response.headers.get("x-request-id")
            or response.headers.get("request-id")
            or completion.id,
            finish_reason=choice.finish_reason,
            prompt_tokens=usage.prompt_tokens if usage is not None else None,
            completion_tokens=usage.completion_tokens if usage is not None else None,
            total_tokens=usage.total_tokens if usage is not None else None,
            model=completion.model,
            structured_output_mode=structured_output_mode,
            schema_name=schema_name,
            schema_digest=schema_digest,
        )
        return content


__all__ = [
    "QwenClient",
    "QwenCompletionMetadata",
    "QwenError",
    "QwenHttpError",
    "QwenResponseError",
    "QwenTimeoutError",
    "QwenTransportError",
]
