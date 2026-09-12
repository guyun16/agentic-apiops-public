"""Freeze Stage21 revision v4 and audit it without executing Formal105 or a model."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path

import stage21_final_v2_formal105 as formal

from app.benchmark import generation_inputs
from app.evaluator import evaluator

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
V2_OFFICIAL_ROOT = REPOSITORY_ROOT / "f105r/official-accuracy-v2-20260904T072119Z"
V3_RESIDUAL_ROOT = (
    REPOSITORY_ROOT / "f105r/v3-residual-systemic-fix-final-20260904T132813Z"
)
V3_RESIDUAL_SUMMARY = V3_RESIDUAL_ROOT / "residual-live-summary.json"
V3_RESIDUAL_TRANSITIONS = V3_RESIDUAL_ROOT / "residual-transition-audit.json"
DECISION_SOURCES = (
    REPOSITORY_ROOT / "python-apiops-agentlab/app/evaluator/evaluator.py",
    REPOSITORY_ROOT / "python-apiops-agentlab/app/benchmark/outcome_v2.py",
    REPOSITORY_ROOT / "python-apiops-agentlab/app/benchmark/success.py",
)
LEAKAGE_TARGETS = (
    formal.MANIFEST_PATH,
    formal.POLICY_PATH,
    formal.GUARDED_TASK_PATH,
    formal.GUARDED_GROUND_TRUTH_PATH,
    formal.FORMAL_GUARDED_TASK_PATH,
    formal.FORMAL_GUARDED_GROUND_TRUTH_PATH,
    formal.AUTHORITY_BINDING_SOURCE_PATH,
    formal.GENERATION_INPUT_RESOLVER_PATH,
    formal.GENERATION_LIVE_METADATA_PATH,
)
OUTCOME_NAMES = frozenset({"PASS", "FAIL", "UNKNOWN"})
IDENTITY_PREFIXES = ("bench_task_", "gt_stage21_")
PROVENANCE_PREFIXES = ("evaluation_run:", "agent_run:", "trace:", "model_call:")


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _tree_digest(root: Path) -> dict[str, object]:
    if not root.is_dir():
        raise RuntimeError(f"historical artifact root is missing: {root}")
    digest = hashlib.sha256()
    files = sorted(path for path in root.rglob("*") if path.is_file())
    for path in files:
        relative = path.relative_to(root).as_posix()
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return {
        "root": str(root),
        "fileCount": len(files),
        "treeDigest": digest.hexdigest(),
    }


def _literal_strings(node: ast.AST) -> set[str]:
    return {
        value.value
        for value in ast.walk(node)
        if isinstance(value, ast.Constant) and isinstance(value.value, str)
    }


def _contains_outcome(node: ast.AST | None) -> bool:
    if node is None:
        return False
    for value in ast.walk(node):
        if isinstance(value, ast.Constant) and value.value in OUTCOME_NAMES:
            return True
        if isinstance(value, ast.Attribute) and value.attr in OUTCOME_NAMES:
            return True
    return False


def _outcome_specific_shortcuts(source_path: Path) -> list[dict[str, object]]:
    """Find identity-conditional direct outcome returns in official decision code."""

    source = source_path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(source_path))
    findings: list[dict[str, object]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.If):
            continue
        identities = sorted(
            value
            for value in _literal_strings(node.test)
            if value.startswith(IDENTITY_PREFIXES)
        )
        if not identities:
            continue
        returns = [value for value in ast.walk(node) if isinstance(value, ast.Return)]
        if any(_contains_outcome(value.value) for value in returns):
            findings.append(
                {
                    "source": str(source_path),
                    "line": node.lineno,
                    "identities": identities,
                    "reason": "identity condition reaches a direct PASS/FAIL/UNKNOWN return",
                }
            )
    return findings


def _all_strings(value: object) -> Iterable[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for key, item in value.items():
            yield str(key)
            yield from _all_strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _all_strings(item)


def _residual_provenance_ids() -> set[str]:
    values: set[str] = set()
    for path in V3_RESIDUAL_ROOT.rglob("*.json"):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        values.update(
            item
            for item in _all_strings(payload)
            if item.startswith(PROVENANCE_PREFIXES)
        )
    return values


def _gt_model_output_leakage() -> dict[str, object]:
    provenance_ids = _residual_provenance_ids()
    artifact_digests = {
        _sha256_file(path)
        for path in V3_RESIDUAL_ROOT.rglob("task-*.json")
        if path.is_file()
    }
    findings: list[dict[str, object]] = []
    for path in LEAKAGE_TARGETS:
        text = path.read_text(encoding="utf-8")
        for marker in ("qwen3.8-max", "Qwen3.8", "qwen3.8"):
            if marker.casefold() in text.casefold():
                findings.append(
                    {"source": str(path), "kind": "PROVIDER_MODEL_MARKER", "value": marker}
                )
        matches = sorted(identifier for identifier in provenance_ids if identifier in text)
        if matches:
            findings.append(
                {
                    "source": str(path),
                    "kind": "RESIDUAL_PROVENANCE_ID",
                    "count": len(matches),
                }
            )
        digest_matches = sorted(digest for digest in artifact_digests if digest in text)
        if digest_matches:
            findings.append(
                {
                    "source": str(path),
                    "kind": "RESIDUAL_TASK_ARTIFACT_DIGEST",
                    "count": len(digest_matches),
                }
            )
    return {
        "status": "PASS" if not findings else "FAIL",
        "findingCount": len(findings),
        "findings": findings,
        "checks": {
            "providerModelMarkersAbsentFromGtTaskEvaluatorContracts": not any(
                item["kind"] == "PROVIDER_MODEL_MARKER" for item in findings
            ),
            "residualProvenanceIdsAbsent": not any(
                item["kind"] == "RESIDUAL_PROVENANCE_ID" for item in findings
            ),
            "residualTaskArtifactDigestsAbsent": not any(
                item["kind"] == "RESIDUAL_TASK_ARTIFACT_DIGEST" for item in findings
            ),
        },
        "residualProvenanceIdsChecked": len(provenance_ids),
        "residualTaskArtifactDigestsChecked": len(artifact_digests),
    }


def _task_specific_rule_audit() -> dict[str, object]:
    rag_ids = set(evaluator._ACCEPTED_EVIDENCE_SOURCE_AUTHORITY)  # noqa: SLF001
    expected_rag_ids = {
        (identity, "v2" if identity.endswith("report_constraint_primary") else "v1")
        for identity in formal.EXACT_AUTHORITY_GROUND_TRUTH_IDS[:-1]
    }
    expected_rag_ids.add(("gt_stage21_formal_failure_multi_evidence_report", "v2"))
    # Register the final residual correction contracts exactly: one live report
    # slot and one schema source, or only that schema source. No wildcard aliases.
    report_slot = "<CURRENT_JAVA_REPORT>"
    index_source = "stage21-rag-v2/project-41/orders-constraint-index"
    final_rag_bindings = {
        ("gt_stage21_failure_diagnosis", "v3"): (
            (report_slot, "rag:orders-unique-index"), (report_slot, index_source),
        ),
        ("gt_stage21_rag_multi_hit", "v2"): (
            (report_slot, "rag:orders-unique-index"), (report_slot, index_source),
        ),
        ("gt_stage21_rag_irrelevant_distractor", "v1"): (
            ("rag:orders-constraint-001",), (index_source,),
        ),
        ("gt_stage21_formal_rag_near_match_exact", "v1"): (
            ("rag:orders-unique-index",), (index_source,),
        ),
    }
    expected_rag_ids.update(final_rag_bindings)
    final_rag_bindings_match = all(
        evaluator._ACCEPTED_EVIDENCE_SOURCE_AUTHORITY.get(key) == value  # noqa: SLF001
        for key, value in final_rag_bindings.items()
    )
    live_ids = set(generation_inputs._LIVE_RUNNER_GENERATION_TASK_IDS)  # noqa: SLF001
    expected_live_ids = {
        *formal.LIVE_RUNNER_GENERATION_TASK_IDS,
        "bench_task_testcase_business_inventory_runner",
    }
    guarded_task = formal._read_json(formal.GUARDED_TASK_PATH)  # noqa: SLF001
    guarded_truth = formal._read_json(formal.GUARDED_GROUND_TRUTH_PATH)  # noqa: SLF001
    formal_guarded_task = formal._read_json(  # noqa: SLF001
        formal.FORMAL_GUARDED_TASK_PATH
    )
    formal_guarded_truth = formal._read_json(  # noqa: SLF001
        formal.FORMAL_GUARDED_GROUND_TRUTH_PATH
    )
    inventory_truth_path = (
        formal.MANIFEST_PATH.parent
        / (
            "formal/ground_truth/"
            "gt_stage21_testcase_inventory_conflict_runner.json"
        )
    )
    inventory_truth = formal._read_json(inventory_truth_path)  # noqa: SLF001
    inventory_expected = tuple(
        (item["name"], item["value"]) for item in inventory_truth["expected_facts"]
    )
    inventory_facts_match = (
        inventory_expected == evaluator._INVENTORY_CONFLICT_RUNNER_EXPECTED_FACTS  # noqa: SLF001
    )
    rules = [
        {
            "name": "RAG_ACCEPTED_SOURCE_AUTHORITY",
            "identityCount": len(rag_ids),
            "identityMode": "EXACT_GROUND_TRUTH_ID_VERSION_AND_EXPECTED_EVIDENCE_TUPLE",
            "inputAuthority": "FROZEN_GT_EXPECTED_IDS_AND_JAVA_RAG_SOURCE_IDS",
            "output": "EXPECTED_EVIDENCE_ID_SET_ONLY",
            "directOutcome": False,
            "status": (
                "PASS" if rag_ids == expected_rag_ids and final_rag_bindings_match else "FAIL"
            ),
        },
        {
            "name": "INVENTORY_LEGACY_SEMANTIC_AUTHORITY",
            "identityCount": 1,
            "identityMode": "EXACT_GT_ID_AND_COMPLETE_EXPECTED_FACT_TUPLE",
            "inputAuthority": "JAVA_TEST_REPORT_RUNNER_SUCCESS_HTTP_409_AND_BUSINESS_CODE",
            "output": "ACCEPTED_STRUCTURED_FACT_NAME_ONLY",
            "directOutcome": False,
            "status": "PASS" if inventory_facts_match else "FAIL",
        },
        {
            "name": "LIVE_RUNNER_GENERATION_METADATA",
            "identityCount": len(live_ids),
            "identityMode": "EXACT_BENCHMARK_TASK_ID",
            "inputAuthority": "FROZEN_METADATA_AND_STRICT_LIVE_JAVA_RUNNER_CONTRACT",
            "output": "RESOLVED_GENERATION_METADATA_ONLY",
            "directOutcome": False,
            "status": "PASS" if live_ids == expected_live_ids else "FAIL",
        },
        {
            "name": "GUARDED_DIAGNOSIS_CONTRACT",
            "identityCount": 2,
            "identityMode": "EXACT_TASK_AND_GT_VERSION",
            "inputAuthority": "CURRENT_JAVA_REPORT_AND_JAVA_DENY",
            "output": "EVALUATION_REQUIREMENTS_ONLY",
            "directOutcome": False,
            "status": (
                "PASS"
                if guarded_task["groundTruthRef"]
                == {
                    "groundTruthId": "gt_stage21_e2e_diagnosis_tool_guarded",
                    "version": "v4",
                }
                and guarded_truth["expected_evidence_ids"] == ["CURRENT_JAVA_REPORT"]
                and guarded_truth["expected_safety_outcome"] == "JAVA_DENIED"
                and guarded_truth["expected_diagnosis"] == "BUSINESS_ERROR"
                and formal_guarded_task["groundTruthRef"]
                == {
                    "groundTruthId": (
                        "gt_stage21_formal_e2e_generation_diagnosis_guarded"
                    ),
                    "version": "v2",
                }
                and formal_guarded_truth["expected_evidence_ids"]
                == ["CURRENT_JAVA_REPORT"]
                and formal_guarded_truth["expected_safety_outcome"] == "JAVA_DENIED"
                and formal_guarded_truth["expected_diagnosis"] == "NONE"
                else "FAIL"
            ),
        },
    ]
    return {
        "status": "PASS" if all(row["status"] == "PASS" for row in rules) else "FAIL",
        "ruleGroupCount": len(rules),
        "identityBindingCount": sum(int(row["identityCount"]) for row in rules),
        "rules": rules,
    }


def _anti_overfit_audit() -> dict[str, object]:
    shortcuts = [
        finding
        for source in DECISION_SOURCES
        for finding in _outcome_specific_shortcuts(source)
    ]
    rules = _task_specific_rule_audit()
    leakage = _gt_model_output_leakage()
    status = (
        "PASS"
        if not shortcuts and rules["status"] == "PASS" and leakage["status"] == "PASS"
        else "FAIL"
    )
    return {
        "schemaVersion": "stage21-v4-anti-overfit-audit/v1",
        "status": status,
        "taskSpecificRules": rules,
        "outcomeSpecificShortcuts": {
            "status": "PASS" if not shortcuts else "FAIL",
            "count": len(shortcuts),
            "findings": shortcuts,
            "decisionSources": [str(path) for path in DECISION_SOURCES],
        },
        "gtModelOutputLeakage": leakage,
        "contractPrinciple": (
            "real input and frozen GroundTruth contract plus Java/Python authority "
            "produce metric facts; only general outcome policy produces PASS/FAIL/UNKNOWN"
        ),
    }


def _residual_13_regression() -> dict[str, object]:
    summary = formal._read_json(V3_RESIDUAL_SUMMARY)  # noqa: SLF001
    transitions = formal._read_json(V3_RESIDUAL_TRANSITIONS)  # noqa: SLF001
    rows = transitions.get("tasks")
    if not isinstance(rows, list):
        raise RuntimeError("residual transition task rows are missing")
    status_counts = {name: 0 for name in ("PASS", "FAIL", "UNKNOWN")}
    for row in rows:
        status_counts[str(row.get("newStatus"))] = (
            status_counts.get(str(row.get("newStatus")), 0) + 1
        )
    checks = {
        "summaryPass": summary.get("status") == "PASS",
        "selected13": summary.get("selectedTaskCount") == 13 and len(rows) == 13,
        "allPass": status_counts == {"PASS": 13, "FAIL": 0, "UNKNOWN": 0},
        "outcomeAccuracy100": summary.get("residualOutcomeAccuracy", {}).get("value") == 1.0,
        "full105NotRun": summary.get("full105Status") == "NOT_RUN",
        "providerIntegrity": summary.get("providerIntegrity", {}).get("status")
        == "PROVIDER_PROVEN",
    }
    return {
        "status": "PASS" if all(checks.values()) else "FAIL",
        "artifact": str(V3_RESIDUAL_SUMMARY),
        "artifactDigest": _sha256_file(V3_RESIDUAL_SUMMARY),
        "transitionArtifact": str(V3_RESIDUAL_TRANSITIONS),
        "transitionArtifactDigest": _sha256_file(V3_RESIDUAL_TRANSITIONS),
        "taskCount": len(rows),
        "statusCounts": status_counts,
        "checks": checks,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--runtime-preflight", type=Path, required=True)
    parser.add_argument("--planned-official-root", type=Path, required=True)
    parser.add_argument(
        "--qwen-acceptance-dir",
        type=Path,
        default=formal.QWEN_ACCEPTANCE_DIR,
    )
    args = parser.parse_args()

    output_root = formal._ensure_new_output_root(args.output_root)  # noqa: SLF001
    planned_official_root = args.planned_official_root.resolve()
    if planned_official_root.exists():
        raise RuntimeError(f"planned Official105 root already exists: {planned_official_root}")

    history_before = {
        "v2Official": _tree_digest(V2_OFFICIAL_ROOT),
        "v3Residual": _tree_digest(V3_RESIDUAL_ROOT),
    }
    dataset = formal.load_dataset(formal.MANIFEST_PATH)
    policy = formal.load_outcome_policy(formal.POLICY_PATH, dataset=dataset)
    dataset_before = formal._dataset_freeze(dataset, policy)  # noqa: SLF001
    settings = formal.get_settings()
    qwen_gate = formal._qwen_provider_gate(  # noqa: SLF001
        settings,
        args.qwen_acceptance_dir,
    )
    environment = formal._environment_readiness(settings, "qwen")  # noqa: SLF001
    if environment.get("ready") is not True:
        missing = [
            name for name, ready in environment["required"].items() if not ready
        ]
        raise RuntimeError("v4 environment readiness is incomplete: " + ", ".join(missing))
    runtime = formal._runtime_preflight_evidence(args.runtime_preflight)  # noqa: SLF001
    task_ids = tuple(entry.benchmark_task_id for entry in dataset.manifest.tasks)
    path_preflight = formal._formal105_path_preflight(  # noqa: SLF001
        planned_official_root,
        "evaluation_run:stage21-v4-official105-planned",
        task_ids,
    )
    if path_preflight["overBudgetCount"] != 0:
        raise RuntimeError("v4 planned Official105 root exceeds the path budget")

    anti_overfit = _anti_overfit_audit()
    residual = _residual_13_regression()
    if anti_overfit["status"] != "PASS" or residual["status"] != "PASS":
        raise RuntimeError("v4 anti-overfit or residual regression audit is not PASS")

    frozen_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    freeze = formal._freeze_manifest(  # noqa: SLF001
        settings,
        dataset,
        policy,
        provider="qwen",
        qwen_gate=qwen_gate,
        environment_readiness=environment,
        runtime_preflight=runtime,
        frozen_at=frozen_at,
    )
    if freeze["accuracyRepairContract"]["revision"] != formal.BENCHMARK_CONTRACT_REVISION:
        raise RuntimeError("v4 revision identity drifted during freeze")
    dataset_after = formal._dataset_freeze(dataset, policy)  # noqa: SLF001
    history_after = {
        "v2Official": _tree_digest(V2_OFFICIAL_ROOT),
        "v3Residual": _tree_digest(V3_RESIDUAL_ROOT),
    }
    preservation = {
        "schemaVersion": "stage21-v4-history-preservation/v1",
        "status": "PASS" if history_before == history_after else "FAIL",
        "before": history_before,
        "after": history_after,
    }
    identity_checks = {
        "revision": freeze["accuracyRepairContract"]["revision"]
        == "stage21-formal105-accuracy-repair-v4",
        "datasetStableDuringAudit": dataset_before == dataset_after,
        "provider": freeze["modelProvider"].get("provider") == "Qwen",
        "model": freeze["modelProvider"].get("model") == "qwen3.8-max",
        "qwenAcceptance": qwen_gate.get("status") == "PASS",
        "runtime": runtime.get("status") == "PASS",
        "pathBudget": path_preflight["overBudgetCount"] == 0,
        "residual13": residual["status"] == "PASS",
        "antiOverfit": anti_overfit["status"] == "PASS",
        "historicalArtifacts": preservation["status"] == "PASS",
        "full105NotRun": not planned_official_root.exists(),
    }
    final_status = "PASS" if all(identity_checks.values()) else "BLOCKED"
    preflight = {
        "schemaVersion": "stage21-v4-final-preflight/v1",
        "status": final_status,
        "checks": identity_checks,
        "plannedOfficialRoot": str(planned_official_root),
        "knownSystemicBlockers": [],
        "providerCalls": 0,
        "javaExecutions": 0,
        "full105Status": "NOT_RUN",
    }
    if final_status != "PASS":
        raise RuntimeError("v4 final preflight is blocked")

    output_root.mkdir(parents=True, exist_ok=False)
    _write_json(output_root / "freeze-manifest.json", freeze)
    _write_json(output_root / "anti-overfit-audit.json", anti_overfit)
    _write_json(output_root / "residual-13-regression.json", residual)
    _write_json(output_root / "runtime-preflight.json", runtime)
    _write_json(output_root / "path-preflight.json", path_preflight)
    _write_json(output_root / "historical-artifact-preservation.json", preservation)
    _write_json(output_root / "final-preflight.json", preflight)
    summary = {
        "schemaVersion": "stage21-v4-final-freeze-summary/v1",
        "status": "PASS",
        "benchmarkRevision": formal.BENCHMARK_CONTRACT_REVISION,
        "freezeStatus": freeze["freezeStatus"],
        "provider": freeze["modelProvider"],
        "antiOverfitAudit": anti_overfit["status"],
        "taskSpecificRuleGroupsAudited": anti_overfit["taskSpecificRules"][
            "ruleGroupCount"
        ],
        "taskSpecificIdentityBindingsAudited": anti_overfit["taskSpecificRules"][
            "identityBindingCount"
        ],
        "outcomeSpecificShortcuts": anti_overfit["outcomeSpecificShortcuts"]["count"],
        "gtModelOutputLeakage": anti_overfit["gtModelOutputLeakage"]["findingCount"],
        "qwen38ProviderAcceptance": qwen_gate["status"],
        "residual13Regression": residual["status"],
        "runtimePreflight": runtime["status"],
        "pathPreflight": "PASS",
        "historicalArtifactsPreserved": preservation["status"],
        "knownSystemicBlockers": [],
        "formal105Status": "NOT_RUN",
        "readyForNextOfficial105": True,
    }
    _write_json(output_root / "v4-final-freeze-summary.json", summary)
    leakage = formal._scan_artifact_secrets(  # noqa: SLF001
        output_root,
        formal._known_secret_values(settings),  # noqa: SLF001
    )
    if leakage:
        raise RuntimeError(
            "v4 freeze artifact contains a known secret in: "
            + ", ".join(str(path) for path in leakage)
        )
    print(json.dumps({**summary, "artifactRoot": str(output_root)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
