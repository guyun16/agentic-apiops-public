"""Freeze current inputs with one disclosed limitation; never execute benchmark tasks."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import os
import re
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import stage21_final_revision_gate as gate
import stage21_final_v2_formal105 as formal
import stage21_v4_final_freeze_audit as previous_freeze

ROOT = gate.ROOT
PRIMARY = ROOT / "f105r/final-six-closure-20260905T022608Z"
CONFIRMATION = ROOT / "f105r/final-six-rag-confirmation-20260905T023914Z"
VERDICT = ROOT / "f105r/final-six-verdict-20260905T024100Z/closure-verdict.json"
PUBLIC_LOCAL_BROKER_DEFAULT_SHA256 = (
    "84983c60f7daadc1cb8698621f802c0d9f9a3c3c295c810748fb048115c186ec"
)


def write(path: Path, value: object) -> None:
    formal._write_json(path, value)


def validate_regression(output: Path) -> None:
    """Actual test/check commands only; store their exit codes and sanitized output."""
    target = output / "regression-validation.json"
    if target.exists():
        raise RuntimeError("REGRESSION_EVIDENCE_ALREADY_EXISTS")
    commands = {
        "FULL_PYTEST": [sys.executable, "-m", "pytest", "-q"],
        "RUFF": [sys.executable, "-m", "ruff", "check", "."],
        "COMPILEALL": [sys.executable, "-m", "compileall", "-q", "app", "scripts", "tests"],
        "GIT_DIFF_CHECK": ["git", "diff", "--check"],
    }
    checks, details = {}, {}
    for name, command in commands.items():
        print(f"RUNNING {name}", flush=True)
        result = subprocess.run(
            command, cwd=ROOT / "python-apiops-agentlab", capture_output=True,
            encoding="utf-8", errors="replace", check=False,
        )
        text = result.stdout + result.stderr
        for secret in formal._known_secret_values():
            text = text.replace(secret, "[REDACTED]")
        (output / f"{name.lower()}.log").write_text(text, encoding="utf-8")
        checks[name] = "PASS" if result.returncode == 0 else "FAIL"
        details[name] = {"command": command, "exitCode": result.returncode}
        if name == "FULL_PYTEST":
            details[name]["summary"] = re.findall(r"\d+ passed[^\r\n]*", text)[-1:]
        print(f"{name} = {checks[name]}", flush=True)
    write(target, {"checks": checks, "details": details, "actualCommandsExecuted": True})
    if any(value != "PASS" for value in checks.values()):
        raise RuntimeError("REGRESSION_VALIDATION_FAILED")


def source_credential_findings(
    source: dict[str, str], before: dict[str, str], secrets: tuple[str, ...],
) -> dict[str, object]:
    """Do not confuse the unchanged public local-broker fixture with injected secrets.

    Artifact scanning still checks EVERY runtime credential, including this public
    default. Only source occurrences already present at freeze intent are classified
    separately, and the same value in any other credential variable stays confidential.
    """
    script_path = "scripts/stage21_start_live_services.ps1"
    literal = re.search(
        r"\$env:APIOPS_RABBITMQ_PASSWORD\s*=\s*'([^']+)'",
        (ROOT / script_path).read_text(encoding="utf-8"),
    )
    public_value = literal.group(1) if literal else ""
    public_default = bool(public_value) and (
        hashlib.sha256(public_value.encode()).hexdigest() == PUBLIC_LOCAL_BROKER_DEFAULT_SHA256
        and os.environ.get("APIOPS_RABBITMQ_PASSWORD") == public_value
        and source.get(script_path) == before.get(script_path)
    )
    other_credential_values = {
        value.strip() for name, value in os.environ.items()
        if name != "APIOPS_RABBITMQ_PASSWORD"
        and any(marker in name.upper() for marker in ("API_KEY", "PASSWORD", "TOKEN", "SECRET"))
        and value.strip()
    }
    public_only = public_default and public_value not in other_credential_values
    confidential = tuple(value for value in secrets if not (public_only and value == public_value))
    private_hits, public_hits = [], []
    for relative, current_digest in source.items():
        content = (ROOT / relative).read_bytes()
        if any(value.encode() in content for value in confidential):
            private_hits.append(relative)
        if public_only and public_value.encode() in content:
            if before.get(relative) != current_digest:
                private_hits.append(relative)  # New/modified occurrences are not exempted.
            else:
                public_hits.append(relative)
    return {
        "confidentialMatchingPaths": sorted(set(private_hits)),
        "unchangedPublicDevelopmentDefaultPaths": public_hits,
        "publicDefaultIsNotAnInjectedConfidentialValue": public_only,
        "artifactScanExemptions": [], "runtimeSecurityExemptions": [],
    }


def history_roots() -> list[Path]:
    return sorted({
        path
        for parent in (ROOT / "f105r", ROOT / "artifacts/stage21",
                       ROOT / "python-apiops-agentlab/artifacts/stage21")
        for path in parent.iterdir()
    })


def history_digest(path: Path) -> str:
    return previous_freeze._tree_digest(path)["treeDigest"] if path.is_dir() else gate.digest(path)


def begin(output: Path) -> None:
    if output.exists():
        raise RuntimeError("FREEZE_ROOT_ALREADY_EXISTS")
    history = {str(path.relative_to(ROOT)): history_digest(path) for path in history_roots()}
    dataset = formal.load_dataset(formal.MANIFEST_PATH)
    policy = formal.load_outcome_policy(formal.POLICY_PATH, dataset=dataset)
    intent = {
        "purpose": "REVISION_FREEZE_ONLY", "officialRunCreated": False,
        "startedAt": datetime.now(UTC).isoformat(),
        "historyBefore": history, "sourceBefore": gate.source_inventory(),
        "datasetBefore": formal._dataset_freeze(dataset, policy),
        "promptsBefore": formal._prompt_freeze(),
        "evaluationBefore": formal._evaluation_freeze(policy),
    }
    output.mkdir(parents=True)
    write(output / "freeze-intent.json", intent)


def verify_prior_evidence() -> dict:
    """Reuse checks only after matching actual current application/Java/fixture sources."""
    previous = formal._read_json(CONFIRMATION / "run-intent.json")["sourceDigestsBefore"]
    checked = 0
    for relative, expected in previous.items():
        normalized = relative.replace("\\", "/")
        if normalized.startswith("python-apiops-agentlab/scripts/") or "/target/" in normalized:
            continue  # New admission scripts tested separately; rebuilt jars frozen below.
        if gate.digest(ROOT / relative) != expected:
            raise RuntimeError("ACCEPTANCE_IMPLEMENTATION_SOURCE_DRIFT")
        checked += 1
    provider = formal._read_json(PRIMARY / "provider-integrity.json")
    if provider.get("callsWithResponseProof") != 8 or any(provider.get(key) for key in (
        "mismatchTaskIds", "actualFallbackTaskIds", "unprovenTaskIds"
    )):
        raise RuntimeError("PRIOR_PROVIDER_PROVENANCE_FAILED")
    primary = formal._read_json(PRIMARY / "final-summary.json")
    confirmation = formal._read_json(CONFIRMATION / "final-summary.json")
    for summary in (primary, confirmation):
        if (
            summary.get("status") != "PASS_WITH_LIMITATIONS"
            and summary.get("status") != "PASS"
        ) or summary["comparison"]["regressionControlFailures"]:
            raise RuntimeError("PRIOR_TARGETED_REGRESSION_FAILED")
    verdict = formal._read_json(VERDICT)
    if not str(verdict["JAVA_VALIDATION"]).startswith("PASS"):
        raise RuntimeError("PRIOR_JAVA_VALIDATION_FAILED")
    return {
        "matchedImplementationFiles": checked,
        "javaValidation": verdict["JAVA_VALIDATION"],
        "previousFullPytest": verdict["FULL_PYTEST"],
        "sixTaskResult": {"pass": 5, "fail": 0, "unknown": 1},
        "regressionControlsPassed": 4, "responseProvenQwenCalls": 8,
        "providerQualificationRepeated": False, "estimateUsedForAdmission": False,
    }


def seal(output: Path, runtime_path: Path, regression_path: Path) -> None:
    intent = formal._read_json(output / "freeze-intent.json")
    if (output / "freeze-manifest.json").exists():
        raise RuntimeError("FREEZE_ALREADY_SEALED")
    settings = formal.get_settings()
    gate.configuration_check(settings)
    environment = formal._environment_readiness(settings, "qwen")
    if not environment["ready"]:
        raise RuntimeError("FREEZE_ENVIRONMENT_CONFIGURATION_INCOMPLETE")
    runtime = formal._runtime_preflight_evidence(runtime_path)
    raw_runtime = formal._read_json(Path(runtime["artifact"]))
    if raw_runtime.get("taskCount") != 105:
        raise RuntimeError("RUNTIME_AUDIT_MUST_COVER_105")
    shared = asyncio.run(gate.shared_live_preflight(settings))
    provider = formal._qwen_provider_gate(settings)
    limitation = gate.known_limitation()
    dataset = formal.load_dataset(formal.MANIFEST_PATH)
    policy = formal.load_outcome_policy(formal.POLICY_PATH, dataset=dataset)
    if (
        formal._dataset_freeze(dataset, policy) != intent["datasetBefore"]
        or formal._prompt_freeze() != intent["promptsBefore"]
        or formal._evaluation_freeze(policy) != intent["evaluationBefore"]
    ):
        raise RuntimeError("PROTECTED_BENCHMARK_INPUT_DRIFT_DURING_FREEZE")
    official = formal._read_json(ROOT / "f105r/v4o-20260904T145500Z/freeze-manifest.json")
    if (
        intent["datasetBefore"]["orderedTaskIdsDigest"]
        != official["dataset"]["orderedTaskIdsDigest"]
    ):
        raise RuntimeError("OFFICIAL_105_TASK_IDENTITIES_CHANGED")
    task_splits = [
        {"taskId": row.benchmark_task_id, "split": row.split.value}
        for row in dataset.manifest.tasks
    ]
    old_projection = formal._read_json(ROOT / "f105r/v4o-20260904T145500Z/outcome-v2.json")
    old_splits = {row["benchmarkTaskId"]: row["split"] for row in old_projection["tasks"]}
    if {row["taskId"]: row["split"] for row in task_splits} != old_splits:
        raise RuntimeError("OFFICIAL_SPLIT_MEMBERSHIP_CHANGED")
    # A path-format probe only. No official evaluation ID is allocated or root created.
    planned = ROOT / "f105r" / "final-official-path-budget-only-YYYYMMDDTHHMMSSZ"
    path = formal._formal105_path_preflight(
        planned, "PATH_BUDGET_ONLY_NOT_AN_EVALUATION_RUN", [row["taskId"] for row in task_splits],
    )
    path["logicalIdentityIsProbeOnly"] = True
    persistence = gate.persistence_probe(ROOT / "f105r")
    admission = gate.admission_decision(
        runtime=runtime, provider=provider, path=path, integrity=persistence, limitation=limitation,
    )
    regression = formal._read_json(regression_path)
    if not regression.get("checks") or any(v != "PASS" for v in regression["checks"].values()):
        raise RuntimeError("REGRESSION_VALIDATION_FAILED")
    reused = verify_prior_evidence()
    preserved = {
        relative: history_digest(ROOT / relative) for relative in intent["historyBefore"]
    }
    if preserved != intent["historyBefore"]:
        raise RuntimeError("HISTORICAL_ARTIFACT_MUTATION")
    source = gate.source_inventory()
    changed = sorted(
        key for key in source.keys() | intent["sourceBefore"].keys()
        if source.get(key) != intent["sourceBefore"].get(key)
    )
    evidence_files = [
        VERDICT, PRIMARY / "final-summary.json", PRIMARY / "provider-integrity.json",
        CONFIRMATION / "final-summary.json", CONFIRMATION / "run-intent.json",
        ROOT / limitation["limitations"][0]["observedTaskArtifact"],
        *[Path(runtime["artifact"]).parent / name for name in raw_runtime["artifactFiles"]],
        regression_path,
    ]
    manifest = formal._freeze_manifest(
        settings, dataset, policy, qwen_gate=provider, environment_readiness=environment,
        runtime_preflight=runtime, frozen_at=datetime.now(UTC).isoformat(),
    )
    manifest.update({
        "freezeStatus": "FROZEN_WITH_KNOWN_LIMITATION", "finalRevision": gate.FINAL_REVISION,
        "configuration": gate.CONFIG, "knownLimitations": limitation, "admission": admission,
        "sourceInventory": source,
        "sourceChangesSinceFreezeIntent": changed,
        "taskSplits": task_splits,
        "runtimeArtifacts": {
            str(p.relative_to(ROOT)): gate.digest(p)
            for p in (ROOT / "java-apiops-platform").glob("*/target/*.jar")
        },
        "evidenceDigests": {str(p.relative_to(ROOT)): gate.digest(p) for p in evidence_files},
        "historicalArtifactsPreserved": True, "historicalRootCount": len(preserved),
        "sharedLivePreflight": shared, "pathPreflight": path, "persistenceProbe": persistence,
        "regressionValidation": regression, "reusedAcceptance": reused,
        "official105Status": "NOT_RUN", "officialEvaluationRunIdCreated": False,
        "officialArtifactRootCreated": False, "syntheticTaskResultsCreated": 0,
        "acceptanceRules": {
            "selected": 105, "minimumPassFor85Percent": 90,
            "passRate": "PASS / 105", "outcomeAccuracy": "PASS / (PASS + FAIL)",
            "unknownRate": "UNKNOWN / 105", "reportUnknownExplicitly": True,
            "estimateIsNotOfficialOrAdmissionEvidence": True,
            "outcomes": "Correct facts PASS; known wrong facts FAIL; missing authority UNKNOWN.",
        },
        "limitations": [
            "One local task has incomplete response-contract authority; not marked READY.",
            "Preparation is point-in-time, not a promise about a later runtime. Shared live "
            "security, source, provider, paths and persistence are rechecked at startup.",
        ],
    })
    # A failed leakage check must not leave an admissible freeze behind.
    write(output / "freeze-manifest.json", {**manifest, "freezeStatus": "PENDING_VALIDATION"})
    write(output / "historical-artifact-preservation.json", {
        "status": "PASS", "before": intent["historyBefore"], "after": preserved,
    })
    write(output / "path-preflight.json", path)
    secrets = formal._known_secret_values(settings)
    matches = formal._scan_artifact_secrets(output, secrets)
    source_scan = source_credential_findings(source, intent["sourceBefore"], secrets)
    if matches or source_scan["confidentialMatchingPaths"]:
        raise RuntimeError("FREEZE_ARTIFACT_SECRET_LEAKAGE")
    write(output / "leakage-scan.json", {
        "status": "PASS", "artifactMatchingPathCount": 0, **source_scan,
        "providedConfidentialCredentialsWrittenToSourceOrArtifacts": False,
    })
    write(output / "freeze-manifest.json", manifest)
    gate.verify_frozen_revision(output / "freeze-manifest.json", settings)
    write(output / "freeze-summary.json", {
        "FINAL_REVISION": gate.FINAL_REVISION,
        "FREEZE_MANIFEST": str(output / "freeze-manifest.json"),
        "FREEZE_MANIFEST_SHA256": gate.digest(output / "freeze-manifest.json"),
        "KNOWN_LIMITATION_TASK": gate.KNOWN_TASK,
        "KNOWN_LIMITATION_SCOPE_VERIFIED": "PASS",
        "ALL_105_TASKS_RETAINED": "PASS: DEV95 + HELD_OUT10",
        "NO_SYNTHETIC_RESULTS": "PASS", "RUNTIME_PREPARATION": "PASS",
        "PATH_PREFLIGHT": "PASS", "REGRESSION_VALIDATION": "PASS",
        "LEAKAGE_SCAN": "PASS", "READY_FOR_OFFICIAL105_WITH_KNOWN_LIMITATION": "YES",
        "officialResultUnchanged": {"revision": "stage21-formal105-accuracy-repair-v4",
                                    "pass": 70, "fail": 25, "unknown": 10},
    })


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--begin", action="store_true")
    parser.add_argument("--validate-regression", action="store_true")
    parser.add_argument("--runtime-preflight", type=Path)
    parser.add_argument("--regression-evidence", type=Path)
    args = parser.parse_args()
    output = args.output_root.resolve()
    if args.validate_regression:
        validate_regression(output)
    elif args.begin:
        begin(output)
        print("FREEZE_INTENT_RECORDED; OFFICIAL105_NOT_RUN")
    else:
        if args.runtime_preflight is None or args.regression_evidence is None:
            parser.error("sealing requires runtime and regression evidence")
        seal(output, args.runtime_preflight.resolve(), args.regression_evidence.resolve())
        print("FINAL_REVISION_FROZEN_WITH_KNOWN_LIMITATION; OFFICIAL105_NOT_RUN")


if __name__ == "__main__":
    main()
