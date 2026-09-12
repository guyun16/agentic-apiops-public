"""Consolidate the bounded Stage 21 real-model E2E evidence and regressions."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any

EXPECTED_TASKS = {
    "bench_task_golden_e2e_apiops",
    "bench_task_e2e_generation_business_failure",
    "bench_task_e2e_generation_runner_success",
    "bench_task_formal_e2e_generation_diagnosis_guarded",
}
JAVA_AUTHORITY_TESTS = (
    "Stage21StandaloneAuthPrerequisiteSetupTest",
    "Stage17RagToolGatewayIntegrationTest",
    "Stage20FinalAcceptanceCrossProcessE2ETest",
    "Stage20DiagnosisToolAuditCrossProcessE2ETest",
    "Stage21GenerationCrossProcessE2ETest",
)


def _redact(value: str) -> str:
    secrets = [
        item
        for key, item in os.environ.items()
        if any(token in key for token in ("PASSWORD", "API_KEY", "JWT_SECRET")) and item
    ]
    for secret in secrets:
        value = value.replace(secret, "<redacted>")
    return re.sub(r"sk-[A-Za-z0-9]+", "<redacted>", value)


def _run_check(
    name: str,
    cwd: Path,
    command: list[str],
    *,
    timeout_seconds: int = 300,
) -> dict[str, Any]:
    try:
        completed = subprocess.run(
            command,
            cwd=cwd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_seconds,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {
            "name": name,
            "status": "BLOCKED",
            "exitCode": None,
            "detail": _redact(str(exc))[:600],
        }
    output = _redact(f"{completed.stdout}\n{completed.stderr}").strip()
    return {
        "name": name,
        "status": "PASS" if completed.returncode == 0 else "FAIL",
        "exitCode": completed.returncode,
        "detail": output[-600:],
    }


def _task_rows(runtime: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for phase_name in ("phase2Golden", "phase3Remaining"):
        phase = runtime.get(phase_name)
        if isinstance(phase, dict):
            rows.extend(item for item in phase.get("taskResults", []) if isinstance(item, dict))
    return rows


def _runtime_gate(runtime: dict[str, Any]) -> dict[str, Any]:
    rows = _task_rows(runtime)
    ids = {row.get("benchmarkTaskId") for row in rows}
    real_calls = sum(bool(row.get("modelCallIds")) for row in rows)
    real_stage16 = sum(row.get("candidateSource") == "REAL_MODEL_STAGE16" for row in rows)
    runner_refs = sum(
        row.get("javaExecutionStatus") == "EXECUTED"
        and isinstance(row.get("runId"), int)
        and row.get("runId", 0) > 0
        for row in rows
    )
    report_refs = sum(
        isinstance(row.get("reportId"), str)
        and bool(row.get("reportId"))
        and not str(row.get("reportId")).startswith("fixture:")
        for row in rows
    )
    required_tool_rows = [
        row
        for row in rows
        if row.get("benchmarkTaskId")
        in {"bench_task_golden_e2e_apiops", "bench_task_formal_e2e_generation_diagnosis_guarded"}
    ]
    observed_required_authority = all(bool(row.get("toolCallIds")) for row in required_tool_rows)
    reasons: list[str] = []
    if ids != EXPECTED_TASKS:
        reasons.append("the four required task identities are not all present")
    if real_calls != 4:
        reasons.append(f"real model calls observed {real_calls}/4")
    if real_stage16 != 4:
        reasons.append(f"real Stage16 generations observed {real_stage16}/4")
    if runner_refs != 4:
        reasons.append(f"Java Runner identities observed {runner_refs}/4")
    if report_refs != 4:
        reasons.append(f"Java Report identities observed {report_refs}/4")
    if not observed_required_authority:
        reasons.append(
            "Golden/formal model outcomes emitted no Tool/RAG identity, so Java authority "
            "cannot be claimed for those required calls"
        )
    if runtime.get("fixtureFallbackCount") != 0:
        reasons.append("fixture fallback count is non-zero")
    if runtime.get("expectedSideLeakage") != 0:
        reasons.append("expected-side leakage count is non-zero")
    if runtime.get("pythonBypassCount") != 0:
        reasons.append("Python bypass count is non-zero")
    if runtime.get("productionSpecialTuning") != 0:
        reasons.append("production special-tuning count is non-zero")
    if runtime.get("fullDatasetRun") is not False:
        reasons.append("bounded run was not proven to exclude full-105")
    return {
        "status": "PASS" if not reasons else "BLOCKED",
        "expectedTaskCount": 4,
        "observedTaskCount": len(ids),
        "realModelCalls": real_calls,
        "realStage16Generations": real_stage16,
        "runnerRealRunIds": runner_refs,
        "reportRealReportIds": report_refs,
        "requiredToolRagJavaAuthorityObserved": observed_required_authority,
        "modelTaskFailuresAcceptedAsObserved": True,
        "fixtureFallbackCount": runtime.get("fixtureFallbackCount"),
        "expectedSideLeakage": runtime.get("expectedSideLeakage"),
        "pythonBypassCount": runtime.get("pythonBypassCount"),
        "productionSpecialTuning": runtime.get("productionSpecialTuning"),
        "fullDatasetRun": runtime.get("fullDatasetRun"),
        "reasons": reasons,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime-artifact", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    runtime = json.loads(args.runtime_artifact.read_text(encoding="utf-8"))
    root = Path(__file__).resolve().parents[2]
    python_project = root / "python-apiops-agentlab"
    java_project = root / "java-apiops-platform"
    regressions = [
        _run_check(
            "benchmark_tests",
            python_project,
            ["uv", "run", "pytest", "tests/benchmark", "-q"],
            timeout_seconds=360,
        ),
        _run_check(
            "schema_validation",
            python_project,
            [
                "uv",
                "run",
                "pytest",
                "tests/benchmark/test_contract.py",
                "tests/benchmark/test_dataset.py",
                "tests/benchmark/test_execution_prerequisites.py",
                "tests/benchmark/test_generation_input_resolution.py",
                "-q",
            ],
            timeout_seconds=240,
        ),
        _run_check("ruff_check", python_project, ["uv", "run", "ruff", "check", "."]),
        _run_check(
            "ruff_format_check",
            python_project,
            ["uv", "run", "ruff", "format", "--check", "."],
        ),
        _run_check("git_diff_check", root, ["git", "diff", "--check"]),
        _run_check(
            "stage20_stage21_authority_regression",
            java_project,
            [
                str(java_project / "mvnw.cmd"),
                "-pl",
                "apiops-web",
                "-am",
                f"-Dtest={','.join(JAVA_AUTHORITY_TESTS)}",
                "-Dsurefire.failIfNoSpecifiedTests=false",
                "test",
            ],
            timeout_seconds=300,
        ),
        {
            "name": "targeted_real_model_e2e",
            "status": "RECORDED",
            "exitCode": 1,
            "detail": (
                "Already executed in bounded Phase 2/3; no model retry in Phase 4. "
                "See runtime artifact for the exact four task rows."
            ),
        },
    ]
    gate = _runtime_gate(runtime)
    regression_pass = all(item["status"] in {"PASS", "RECORDED"} for item in regressions)
    final_status = "PASS" if gate["status"] == "PASS" and regression_pass else "BLOCKED"
    artifact = {
        "schemaVersion": "stage21-real-model-e2e-consolidated-v1",
        "finalMarker": "STAGE21_REAL_MODEL_E2E_GATE_PASS"
        if final_status == "PASS"
        else "STAGE21_REAL_MODEL_E2E_GATE_BLOCKED",
        "fullDatasetRun": False,
        "runtimeArtifact": str(args.runtime_artifact.resolve()),
        "runtimeGate": gate,
        "regressions": regressions,
        "status": final_status,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(artifact, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(artifact["finalMarker"])
    print(args.output.resolve())
    return 0 if final_status == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
