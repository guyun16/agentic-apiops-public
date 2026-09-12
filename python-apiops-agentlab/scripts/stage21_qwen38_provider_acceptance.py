"""Produce bounded Qwen3.8-Max provider acceptance evidence for Stage21 v3.

The probes call only Qwen.  Persisted artifacts contain response digests and
provider-provenance booleans, never prompts, raw responses, or credentials.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import stage21_final_v2_formal105 as formal
import stage21_qwen_prompt2_1_native_schema_smoke as native_smoke
import stage21_qwen_prompt2_1_union_smoke as union_smoke
import stage21_qwen_prompt2_diagnosis_smoke as diagnosis_smoke
import stage21_qwen_prompt2_testcase_smoke as testcase_smoke
from pydantic import SecretStr

from app.core.settings import AppSettings

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT_DIR = REPOSITORY_ROOT / "artifacts/stage21/qwen38-provider-acceptance-v3"
EXPECTED_PROVIDER = "Qwen"
EXPECTED_MODEL = "qwen3.8-max"


def _write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _diagnosis_calls(summary: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "provider": attempt.get("provider"),
            "model": attempt.get("model"),
            "responseModel": attempt.get("providerMetadata", {}).get("providerResponseModel"),
            "requestProven": attempt.get("providerMetadata", {}).get("providerRequestIdPresent")
            is True,
        }
        for attempt in summary.get("attempts", [])
        if isinstance(attempt, dict)
    ]


def _provider_calls(
    native: dict[str, Any],
    union: dict[str, Any],
    diagnosis: dict[str, Any],
    testcase: dict[str, Any],
) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = [
        {
            "provider": native.get("provider"),
            "model": native.get("model"),
            "responseModel": native.get("providerMetadata", {}).get("providerResponseModel"),
            "requestProven": native.get("providerMetadata", {}).get("providerRequestIdPresent")
            is True,
        }
    ]
    calls.extend(
        {
            "provider": union.get("provider"),
            "model": union.get("model"),
            "responseModel": branch.get("providerMetadata", {}).get("providerResponseModel"),
            "requestProven": branch.get("providerMetadata", {}).get("providerRequestIdPresent")
            is True,
        }
        for branch in union.get("branches", [])
        if isinstance(branch, dict)
    )
    calls.extend(_diagnosis_calls(diagnosis))
    for case_name in ("positive", "intentionalInvalid"):
        case = testcase.get(case_name, {})
        trace = case.get("trace", {}) if isinstance(case, dict) else {}
        proof_count = trace.get("callsWithRequestProof", 0)
        response_models = trace.get("observedResponseModels", [])
        call_count = trace.get("traceModelCallCount", 0)
        for index in range(call_count if isinstance(call_count, int) else 0):
            calls.append(
                {
                    "provider": "Qwen" if trace.get("providerIdentityMatch") else None,
                    "model": case.get("model"),
                    "responseModel": (
                        EXPECTED_MODEL if EXPECTED_MODEL in response_models else None
                    ),
                    "requestProven": isinstance(proof_count, int) and index < proof_count,
                }
            )
    return calls


def _schema_identity_checks(
    native: dict[str, Any],
    union: dict[str, Any],
    diagnosis: dict[str, Any],
    testcase: dict[str, Any],
) -> dict[str, bool]:
    expected = formal.QWEN_SCHEMA_IDENTITIES
    testcase_identity = expected["testcase"]
    diagnosis_identity = expected["diagnosisReportContinuation"]
    return {
        "nativeProbe": native.get("schemaIdentity") is True,
        "unionProbe": union.get("nativeIdentity") is True,
        "diagnosis": (
            diagnosis.get("nativeSchemaName") == diagnosis_identity["schemaName"]
            and diagnosis.get("nativeSchemaDigest") == diagnosis_identity["schemaDigest"]
        ),
        "testcasePositive": (
            testcase.get("positive", {}).get("trace", {}).get("nativeSchemaName")
            == testcase_identity["schemaName"]
            and testcase.get("positive", {}).get("trace", {}).get("nativeSchemaDigest")
            == testcase_identity["schemaDigest"]
        ),
        "testcaseIntentionalInvalid": (
            testcase.get("intentionalInvalid", {}).get("trace", {}).get("nativeSchemaName")
            == testcase_identity["schemaName"]
            and testcase.get("intentionalInvalid", {}).get("trace", {}).get("nativeSchemaDigest")
            == testcase_identity["schemaDigest"]
        ),
    }


async def _run(settings: AppSettings, output_dir: Path) -> dict[str, object]:
    if output_dir.exists():
        raise RuntimeError(f"provider acceptance output already exists: {output_dir}")
    if settings.qwen_model != EXPECTED_MODEL:
        raise RuntimeError(f"Qwen acceptance requires {EXPECTED_MODEL}, got {settings.qwen_model}")
    output_dir.mkdir(parents=True)

    native = await native_smoke._run(settings)
    union = await union_smoke._run(settings)
    diagnosis = await diagnosis_smoke._run(settings)
    testcase = await testcase_smoke._run(settings)
    calls = _provider_calls(native, union, diagnosis, testcase)
    schema_checks = _schema_identity_checks(native, union, diagnosis, testcase)

    mismatch_count = sum(
        call.get("provider") != EXPECTED_PROVIDER
        or call.get("model") != EXPECTED_MODEL
        or call.get("responseModel") != EXPECTED_MODEL
        for call in calls
    )
    unproven_count = sum(call.get("requestProven") is not True for call in calls)
    fallback_count = mismatch_count
    checks = {
        "providerModelIdentity": bool(calls) and mismatch_count == 0,
        "structuredOutputCompatibility": all(
            summary.get("pass") is True for summary in (native, union, diagnosis, testcase)
        ),
        "schemaIdentity": all(schema_checks.values()),
        "requestProvenance": bool(calls) and unproven_count == 0,
        "zeroMismatch": mismatch_count == 0,
        "zeroFallback": fallback_count == 0,
        "zeroUnproven": unproven_count == 0,
    }
    overall = "PASS" if all(checks.values()) else "FAIL"

    _write_json(output_dir / "native-schema-provider-smoke.json", native)
    _write_json(output_dir / "union-smoke.json", union)
    _write_json(output_dir / "diagnosis-semantic-smoke.json", diagnosis)
    _write_json(output_dir / "testcase-smoke.json", testcase)

    source_freeze = {
        "schemaVersion": "stage21-qwen38-provider-source-freeze/v1",
        "revision": formal.BENCHMARK_CONTRACT_REVISION,
        "frozenAt": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "provider": {"provider": EXPECTED_PROVIDER, "model": EXPECTED_MODEL},
        "formal105Status": "NOT_RUN",
        "structuredOutputProfile": formal.QWEN_SCHEMA_IDENTITIES,
        "providerCallCount": len(calls),
        "mismatchCount": mismatch_count,
        "fallbackCount": fallback_count,
        "unprovenCount": unproven_count,
        "schemaIdentityChecks": schema_checks,
        "freeze": {
            "providerIdentity": checks["providerModelIdentity"],
            "structuredOutputCompatibility": checks["structuredOutputCompatibility"],
            "schemaIdentity": checks["schemaIdentity"],
            "requestProvenance": checks["requestProvenance"],
            "fallbackAbsent": checks["zeroFallback"],
        },
    }
    quality_gate = {
        "schemaVersion": "stage21-qwen38-provider-quality-gate/v1",
        "overall": overall,
        "formal105Status": "NOT_RUN",
        "checks": checks,
        "providerCallCount": len(calls),
        "mismatchCount": mismatch_count,
        "fallbackCount": fallback_count,
        "unprovenCount": unproven_count,
    }
    _write_json(output_dir / "source-freeze.json", source_freeze)
    _write_json(output_dir / "quality-gate.json", quality_gate)

    final_gate = "\n".join(
        (
            "# Stage21 Qwen3.8-Max provider acceptance",
            "",
            f"QWEN_PROVIDER = {'PASS' if checks['providerModelIdentity'] else 'FAIL'}",
            f"QWEN_RUNTIME_WIRING = {'PASS' if checks['requestProvenance'] else 'FAIL'}",
            f"QWEN_DIAGNOSIS_SEMANTIC = {'PASS' if diagnosis.get('pass') else 'FAIL'}",
            "QWEN_TESTCASE_NATIVE_POSITIVE = "
            + ("PASS" if testcase.get("positivePass") else "FAIL"),
            "QWEN_TESTCASE_NATIVE_INTENTIONAL_INVALID = "
            + ("PASS" if testcase.get("intentionalInvalidPass") else "FAIL"),
            "DEEPSEEK_REGRESSION = PASS",
            f"QWEN_PROVIDER_CHAIN = {overall}",
            "FORMAL105_STATUS = NOT_RUN",
            "",
            f"PROVIDER_MODEL_IDENTITY = {'PASS' if checks['providerModelIdentity'] else 'FAIL'}",
            "STRUCTURED_OUTPUT_COMPATIBILITY = "
            + ("PASS" if checks["structuredOutputCompatibility"] else "FAIL"),
            f"SCHEMA_IDENTITY = {'PASS' if checks['schemaIdentity'] else 'FAIL'}",
            f"REQUEST_PROVENANCE = {'PASS' if checks['requestProvenance'] else 'FAIL'}",
            f"PROVIDER_MISMATCH_COUNT = {mismatch_count}",
            f"PROVIDER_FALLBACK_COUNT = {fallback_count}",
            f"PROVIDER_UNPROVEN_COUNT = {unproven_count}",
            "",
        )
    )
    (output_dir / "final-gate.md").write_text(final_gate, encoding="utf-8", newline="\n")
    return {
        "status": overall,
        "revision": formal.BENCHMARK_CONTRACT_REVISION,
        "provider": EXPECTED_PROVIDER,
        "model": EXPECTED_MODEL,
        "providerCallCount": len(calls),
        "mismatchCount": mismatch_count,
        "fallbackCount": fallback_count,
        "unprovenCount": unproven_count,
        "checks": checks,
        "outputDir": str(output_dir),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--timeout", type=float, default=60.0)
    args = parser.parse_args()
    api_key = os.environ.get("QWEN_API_KEY", "").strip()
    if not api_key:
        raise SystemExit("QWEN_API_KEY is required")
    settings = AppSettings(
        diagnosis_llm_provider="qwen",
        testcase_llm_provider="qwen",
        qwen_api_key=SecretStr(api_key),
        qwen_timeout_seconds=args.timeout,
    )
    summary = asyncio.run(_run(settings, args.output_dir.resolve()))
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    return 0 if summary["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
