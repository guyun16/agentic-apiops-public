"""Run one provider-only Qwen native JSON Schema capability probe."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
from time import perf_counter

import httpx
from jsonschema import ValidationError as JsonSchemaValidationError
from jsonschema import validate as validate_json_schema
from pydantic import SecretStr

from app.clients.llm import StructuredOutputSpec
from app.clients.llm_provider import build_llm
from app.clients.qwen_structured_output import schema_digest
from app.core.settings import AppSettings

SCHEMA_NAME = "qwen_prompt2_1_provider_smoke_v1"
SCHEMA = {
    "type": "object",
    "properties": {
        "status": {"type": "string", "enum": ["ok"]},
        "count": {"type": "integer"},
    },
    "required": ["status", "count"],
    "additionalProperties": False,
}
OUTPUT_SPEC = StructuredOutputSpec(schema_name=SCHEMA_NAME, schema=SCHEMA, strict=True)
PROMPT = "Return the required structured object with status ok and count 1."


def _digest(value: object) -> str:
    if isinstance(value, str):
        payload = value.encode("utf-8")
    else:
        payload = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _metadata_summary(llm: object) -> dict[str, object]:
    metadata = getattr(llm, "last_completion_metadata", None)
    return {
        "providerRequestIdPresent": bool(getattr(metadata, "provider_request_id", None)),
        "finishReason": getattr(metadata, "finish_reason", None),
        "promptTokens": getattr(metadata, "prompt_tokens", None),
        "completionTokens": getattr(metadata, "completion_tokens", None),
        "totalTokens": getattr(metadata, "total_tokens", None),
        "providerResponseModel": getattr(metadata, "model", None),
        "structuredOutputMode": getattr(metadata, "structured_output_mode", None),
        "schemaName": getattr(metadata, "schema_name", None),
        "schemaDigest": getattr(metadata, "schema_digest", None),
    }


async def _run(settings: AppSettings) -> dict[str, object]:
    started = perf_counter()
    response_length: int | None = None
    response_digest: str | None = None
    parsed = False
    schema_valid = False
    error_class: str | None = None
    error_status_code: int | None = None
    async with httpx.AsyncClient(trust_env=False) as http_client:
        llm = build_llm(http_client, settings, provider="qwen")
        try:
            raw = await llm.complete_structured(PROMPT, output_spec=OUTPUT_SPEC)  # type: ignore[attr-defined]
            response_length = len(raw)
            response_digest = _digest(raw)
            payload = json.loads(raw)
            parsed = True
            validate_json_schema(payload, SCHEMA)
            schema_valid = True
        except (JsonSchemaValidationError, json.JSONDecodeError) as exc:
            error_class = type(exc).__name__
        except Exception as exc:  # noqa: BLE001 - safe provider-boundary summary
            error_class = type(exc).__name__
            error_status_code = getattr(exc, "status_code", None)
        metadata = _metadata_summary(llm)

    expected_digest = schema_digest(SCHEMA)
    native_mode = metadata["structuredOutputMode"] == "JSON_SCHEMA"
    schema_identity = (
        metadata["schemaName"] == SCHEMA_NAME and metadata["schemaDigest"] == expected_digest
    )
    provider_success = error_class is None
    model_matches = metadata["providerResponseModel"] == llm.model
    return {
        "provider": llm.provider,
        "model": llm.model,
        "baseUrl": settings.qwen_base_url,
        "requestFormatType": "json_schema",
        "schemaName": SCHEMA_NAME,
        "schemaDigest": expected_digest,
        "strict": True,
        "enableThinking": False,
        "stream": False,
        "maxTokensSent": False,
        "providerSuccess": provider_success,
        "returnedJsonParsed": parsed,
        "returnedJsonSchemaValid": schema_valid,
        "returnedModelMatches": model_matches,
        "nativeMode": native_mode,
        "schemaIdentity": schema_identity,
        "responseLength": response_length,
        "responseDigest": response_digest,
        "latencyMs": round((perf_counter() - started) * 1000, 2),
        "providerMetadata": metadata,
        "errorClass": error_class,
        "errorStatusCode": error_status_code,
        "pass": all(
            (
                llm.provider == "Qwen",
                provider_success,
                parsed,
                schema_valid,
                model_matches,
                native_mode,
                schema_identity,
                metadata["providerRequestIdPresent"] is True,
            )
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--timeout", type=float, default=60.0)
    args = parser.parse_args()
    api_key = os.environ.get("QWEN_API_KEY", "").strip()
    if not api_key:
        raise SystemExit("QWEN_API_KEY is required")
    settings = AppSettings(
        qwen_api_key=SecretStr(api_key),
        qwen_timeout_seconds=args.timeout,
    )
    summary = asyncio.run(_run(settings))
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    return 0 if summary["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
