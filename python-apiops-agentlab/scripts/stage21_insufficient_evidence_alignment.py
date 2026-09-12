"""Offline contract matrix and historical-fact evaluation; never executes an Agent.

The content references are evaluation-only, not an automatic prose classifier.
This script writes a separate revision directory, never an official run directory.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from pydantic import ValidationError

from app.agents.diagnosis import DiagnosisInference, DiagnosisInferenceError
from app.agents.diagnosis_contract import observe_diagnosis_contract
from app.benchmark.dataset import load_dataset
from app.benchmark.outcome_v2 import (
    OutcomeMetricObservation,
    OutcomeMode,
    OutcomePolicy,
    _status_for_observations,
)
from app.evaluator.evaluator import RuleBasedEvaluator
from app.evaluator.models import EvaluationCase, EvaluationFacts, GroundTruth, MetricName
from app.rag.context import (
    ContextItem,
    ContextPackBuilder,
    ContextPolicy,
    ContextProvenance,
    ContextSource,
)
from app.schemas.diagnosis_report import DiagnosisReport
from app.schemas.runner import TestReport

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = (
    ROOT / "python-apiops-agentlab/tests/benchmark/fixtures/revisions/insufficient-evidence-v1"
)
AUDIT = ROOT / "artifacts/stage21/v5-remaining-diagnosis-failure-audit-20260905"
DEFAULT_OUTPUT = ROOT / "artifacts/stage21/insufficient-evidence-contract-v1-20260905/results"
EXPECTED = [
    {"name": "sufficient_evidence", "value": False},
    {"name": "diagnosis_outcome", "value": "INSUFFICIENT_EVIDENCE"},
    {"name": "sufficientEvidence", "value": False},
    {"name": "limitations_required", "value": True},
]


def read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def evaluate(facts: dict, ground: dict) -> dict:
    truth = GroundTruth.model_validate_json(json.dumps(ground))
    case = EvaluationCase.model_validate_json(
        json.dumps(
            {
                "case_id": "offline-contract-case",
                "trace_id": "trace:offline-evaluation",
                "agent_run_id": "agent:offline-evaluation",
                "ground_truth_id": truth.ground_truth_id,
                "ground_truth_version": truth.version,
                "facts": facts,
                "applicable_metrics": ["diagnosis_contract", "exact_match"],
            }
        )
    )
    result = RuleBasedEvaluator().evaluate(case, truth, ())
    observations = tuple(
        OutcomeMetricObservation(
            metric=m.metric,
            status=m.status,
            value=m.value,
            expectedValue=1,
            reason=m.reason,
        )
        for m in result.metrics
        if m.metric in {MetricName.DIAGNOSIS_CONTRACT, MetricName.EXACT_MATCH}
    )
    return {
        "outcome": _status_for_observations(observations, OutcomeMode.ALL).value,
        "metrics": [m.model_dump(mode="json") for m in observations],
        "evaluation": result.model_dump(mode="json"),
    }


def matrix_result(scenario: dict, row: dict) -> dict:
    candidate = row["candidate"]
    evidence = scenario["evidence"]
    pack = ContextPackBuilder(
        ContextPolicy(source_precedence=tuple(ContextSource)),
        project_scope=scenario["report"]["projectId"],
    ).build(
        tuple(
            ContextItem(
                source_type=ContextSource(item["sourceType"]),
                source_id=item["itemId"],
                project_scope=scenario["report"]["projectId"],
                content=item["content"],
                truncated=item["truncated"],
                provenance=tuple(ContextProvenance(**p) for p in item["provenance"]),
            )
            for item in evidence
        )
    )
    accepted, error = True, None
    try:
        DiagnosisInference._validate_report_candidate(
            DiagnosisReport.model_validate(candidate),
            report=TestReport.model_validate(scenario["report"]),
            context_pack=pack,
            trace_id=scenario.get("validatorIdentity", {}).get("traceId", "trace:offline-matrix"),
            agent_run_id=scenario.get("validatorIdentity", {}).get(
                "agentRunId", "agent:offline-matrix"
            ),
        )
    except (ValidationError, DiagnosisInferenceError) as exc:
        accepted, error = False, str(exc)
    observation = observe_diagnosis_contract(
        candidate, evidence, complete_original=row.get("completeOriginal", True)
    )
    # Derived from the actual fixed candidate, never copied from its expected verdict.
    structured = [
        {"name": "sufficient_evidence", "value": candidate.get("sufficientEvidence")},
        {"name": "sufficientEvidence", "value": candidate.get("sufficientEvidence")},
        {
            "name": "diagnosis_outcome",
            "value": "INSUFFICIENT_EVIDENCE"
            if candidate.get("sufficientEvidence") is False
            else "ROOT_CAUSE_CLAIMED",
        },
        {"name": "limitations_required", "value": bool(candidate.get("limitations"))},
        {"name": "diagnosis_contract_observation", "value": observation},
    ]
    ground = {
        "ground_truth_id": "gt:offline-contract-matrix",
        "version": "v1",
        "diagnosis_contract": "insufficient-evidence-v1",
        "expected_facts": EXPECTED,
        "diagnosis_content_reviews": [row["contentReview"]] if row["contentReview"] else [],
    }
    if "groundTruthFile" in scenario:
        ground = read(FIXTURES / scenario["groundTruthFile"])
    scored = evaluate({"structured_facts": structured}, ground)
    return {
        "scenario": scenario["name"],
        "candidate": row["name"],
        "validatorAccepted": accepted,
        "validatorError": error,
        "observation": observation,
        "expectedOutcome": row["expectedOutcome"],
        "expectedValidatorAccepted": row["expectedValidatorAccepted"],
        **scored,
    }


def run(output: Path) -> dict:
    output = output.resolve()
    if not output.is_relative_to(
        (ROOT / "artifacts/stage21/insufficient-evidence-contract-v1-20260905").resolve()
    ):
        raise ValueError("offline results must stay inside this independent revision directory")
    matrix = read(FIXTURES / "fixed-candidate-matrix.json")
    results = [matrix_result(s, row) for s in matrix["scenarios"] for row in s["candidates"]]
    assert all(r["outcome"] == r["expectedOutcome"] for r in results)
    assert all(r["validatorAccepted"] == r["expectedValidatorAccepted"] for r in results)
    assert all(
        any(
            r["outcome"] == "PASS" and r["validatorAccepted"]
            for r in results
            if r["scenario"] == s["name"]
        )
        for s in matrix["scenarios"]
    )
    dataset = load_dataset(FIXTURES / "dataset-manifest.json")
    policy = OutcomePolicy.model_validate_json((FIXTURES / "outcome-policy.json").read_text())
    assert all(
        set(t.outcome_metrics) == {MetricName.DIAGNOSIS_CONTRACT, MetricName.EXACT_MATCH}
        and t.outcome_mode is OutcomeMode.ALL
        for t in policy.tasks
    )
    grounds = {g.ground_truth_id: g for g in dataset.ground_truths}
    witnesses = read(FIXTURES / "original-input-contract-witnesses.json")
    witness_results = [
        matrix_result(s, row) for s in witnesses["scenarios"] for row in s["candidates"]
    ]
    assert len(witness_results) == 16
    assert all(r["validatorAccepted"] and r["outcome"] == "PASS" for r in witness_results)
    regressions = []
    for i in range(1, 9):
        old = read(AUDIT / f"evidence/{i:02d}.json")
        recovered = old["inputRecovery"]
        assert recovered["status"] == "EXACT_DIGEST_MATCH"
        assert recovered["computedDigest"] == recovered["observedDigest"]
        # The actualDiagnosis export is PARTIAL. Do not fill summary, checks,
        # limitations, identities or any missing field with invented text.
        observation = observe_diagnosis_contract(
            old["actualDiagnosis"],
            recovered["boundedContextItems"],
            complete_original=False,
        )
        facts = EvaluationFacts.model_validate_json(json.dumps(old["normalizedEvaluationFacts"]))
        payload = facts.model_dump(mode="json")
        payload["structured_facts"].append(
            {"name": "diagnosis_contract_observation", "value": observation}
        )
        ground = grounds[old["groundTruth"]["ground_truth_id"]].model_dump(mode="json")
        regressions.append(
            {
                "taskId": old["taskId"],
                "officialV5Outcome": "FAIL",
                "sourceAuditEvidence": str(AUDIT / f"evidence/{i:02d}.json"),
                "originalInputDigest": recovered["computedDigest"],
                "observation": observation,
                "persistedContentReview": ground["diagnosis_content_reviews"],
                "originalOutputReconstructed": False,
                **evaluate(payload, ground),
            }
        )
    output.mkdir(parents=True, exist_ok=True)
    summary = {
        "revision": "stage21-insufficient-evidence-contract-v1",
        "officialScoresModified": False,
        "matrixCounts": dict(Counter(r["outcome"] for r in results)),
        "matrixSize": len(results),
        "matrixExpectedMatched": True,
        "inputFamiliesWithJointlyLegalCandidate": len(matrix["scenarios"]),
        "contractUnsatisfiableFamilies": [],
        "versionedGroundTruthsWithJointlyLegalWitnesses": len(witnesses["scenarios"]),
        "newlyAuthoredGtWitnessCount": len(witness_results),
        "historicalRegressionCounts": dict(Counter(r["outcome"] for r in regressions)),
        "modelCalls": 0,
        "embeddingCalls": 0,
        "javaCalls": 0,
        "workflowReplays": 0,
        "rawHistoricalOutputInvented": False,
        "inputRecoveryEnumerationRepeated": False,
    }
    for name, data in (
        ("matrix-results.json", results),
        ("gt-witness-results.json", witness_results),
        ("eight-regression.json", regressions),
        ("summary.json", summary),
    ):
        (output / name).write_text(
            json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    print(json.dumps(run(parser.parse_args().output), ensure_ascii=False))
