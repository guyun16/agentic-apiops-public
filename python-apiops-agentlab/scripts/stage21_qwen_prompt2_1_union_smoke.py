"""Probe the smallest Qwen native anyOf union needed by Diagnosis auditing."""

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

SCHEMA_NAME = "diagnosis_dual_output_union_probe_v1"
SCHEMA = {
    "anyOf": [
        {
            "type": "object",
            "properties": {
                "kind": {"type": "string", "enum": ["report_probe"]},
                "value": {"type": "string"},
            },
            "required": ["kind", "value"],
            "additionalProperties": False,
        },
        {
            "type": "object",
            "properties": {
                "kind": {"type": "string", "enum": ["tool_probe"]},
                "tool": {"type": "string"},
            },
            "required": ["kind", "tool"],
            "additionalProperties": False,
        },
    ]
}
OUTPUT_SPEC = StructuredOutputSpec(schema_name=SCHEMA_NAME, schema=SCHEMA, strict=True)
PROMPTS = (
    ("REPORT", 'Return branch A only: {"kind":"report_probe","value":"ok"}.'),
    ("TOOL", 'Return branch B only: {"kind":"tool_probe","tool":"probe.tool"}.'),
)


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()


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
    expected_digest = schema_digest(SCHEMA)
    branches: list[dict[str, object]] = []
    async with httpx.AsyncClient(trust_env=False) as http_client:
        llm = build_llm(http_client, settings, provider="qwen")
        for label, prompt in PROMPTS:
            started = perf_counter()
            response_length: int | None = None
            response_digest: str | None = None
            actual_kind: str | None = None
            parsed = False
            schema_valid = False
            error_class: str | None = None
            try:
                raw = await llm.complete_structured(prompt, output_spec=OUTPUT_SPEC)  # type: ignore[attr-defined]
                response_length = len(raw)
                response_digest = _digest(raw)
                payload = json.loads(raw)
                parsed = True
                validate_json_schema(payload, SCHEMA)
                schema_valid = True
                actual_kind = payload.get("kind") if isinstance(payload, dict) else None
            except (JsonSchemaValidationError, json.JSONDecodeError) as exc:
                error_class = type(exc).__name__
            except Exception as exc:  # noqa: BLE001 - safe provider-boundary summary
                error_class = type(exc).__name__
            metadata = _metadata_summary(llm)
            branches.append(
                {
                    "label": label,
                    "expectedKind": "report_probe" if label == "REPORT" else "tool_probe",
                    "actualKind": actual_kind,
                    "providerSuccess": error_class is None,
                    "returnedJsonParsed": parsed,
                    "returnedJsonSchemaValid": schema_valid,
                    "expectedBranch": actual_kind
                    == ("report_probe" if label == "REPORT" else "tool_probe"),
                    "responseLength": response_length,
                    "responseDigest": response_digest,
                    "latencyMs": round((perf_counter() - started) * 1000, 2),
                    "providerMetadata": metadata,
                    "errorClass": error_class,
                }
            )

    native_identity = all(
        branch["providerMetadata"]["structuredOutputMode"] == "JSON_SCHEMA"
        and branch["providerMetadata"]["schemaName"] == SCHEMA_NAME
        and branch["providerMetadata"]["schemaDigest"] == expected_digest
        and branch["providerMetadata"]["providerRequestIdPresent"] is True
        for branch in branches
    )
    return {
        "provider": llm.provider,
        "model": llm.model,
        "schemaName": SCHEMA_NAME,
        "schemaDigest": expected_digest,
        "requestFormatType": "json_schema",
        "strict": True,
        "branchCount": len(branches),
        "branches": branches,
        "nativeIdentity": native_identity,
        "pass": llm.provider == "Qwen"
        and len(branches) == len(PROMPTS)
        and native_identity
        and all(
            branch["providerSuccess"] is True
            and branch["returnedJsonParsed"] is True
            and branch["returnedJsonSchemaValid"] is True
            and branch["expectedBranch"] is True
            for branch in branches
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
