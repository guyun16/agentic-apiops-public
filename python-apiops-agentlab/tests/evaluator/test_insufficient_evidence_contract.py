"""Fixed, reviewed candidates; no LLM, keyword semantics, or live execution."""

from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path

import pytest

from app.agents.diagnosis_contract import observe_diagnosis_contract
from app.evaluator.models import GroundTruth

SCRIPT = Path(__file__).resolve().parents[2] / "scripts/stage21_insufficient_evidence_alignment.py"
SPEC = importlib.util.spec_from_file_location("alignment", SCRIPT)
alignment = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(alignment)
MATRIX = alignment.read(alignment.FIXTURES / "fixed-candidate-matrix.json")
CASES = [(scenario, row) for scenario in MATRIX["scenarios"] for row in scenario["candidates"]]
GT_WITNESSES = alignment.read(alignment.FIXTURES / "original-input-contract-witnesses.json")


@pytest.mark.parametrize(
    ("scenario", "row"), CASES, ids=[f"{s['name']}/{r['name']}" for s, r in CASES]
)
def test_fixed_candidate_contract(scenario: dict, row: dict) -> None:
    result = alignment.matrix_result(scenario, row)
    assert result["outcome"] == row["expectedOutcome"]
    assert result["validatorAccepted"] == row["expectedValidatorAccepted"]


@pytest.mark.parametrize(
    ("scenario", "row"),
    [(s, r) for s in GT_WITNESSES["scenarios"] for r in s["candidates"]],
    ids=[f"{s['name']}/{r['name']}" for s in GT_WITNESSES["scenarios"] for r in s["candidates"]],
)
def test_each_new_gt_allows_grounded_empty_and_nonempty_witnesses(
    scenario: dict,
    row: dict,
) -> None:
    assert GT_WITNESSES["originalHistoricalResponsesModified"] is False
    result = alignment.matrix_result(scenario, row)
    assert result["validatorAccepted"]
    assert result["outcome"] == "PASS"


def test_every_input_has_joint_validator_and_scoring_witness() -> None:
    for scenario in MATRIX["scenarios"]:
        results = [alignment.matrix_result(scenario, r) for r in scenario["candidates"]]
        assert any(r["validatorAccepted"] and r["outcome"] == "PASS" for r in results)


@pytest.mark.parametrize("mutation", ["candidate", "evidence"])
def test_content_review_cannot_be_reused_after_input_or_output_change(mutation: str) -> None:
    scenario = copy.deepcopy(MATRIX["scenarios"][0])
    row = copy.deepcopy(scenario["candidates"][1])
    if mutation == "candidate":
        row["candidate"]["rootCauseHypotheses"][0]["statement"] += " A new unreviewed claim."
    else:
        scenario["evidence"][0]["content"] += " "
    assert alignment.matrix_result(scenario, row)["outcome"] == "UNKNOWN"


def test_low_confidence_and_existing_but_irrelevant_citation_do_not_pass() -> None:
    for scenario in MATRIX["scenarios"]:
        row = next(r for r in scenario["candidates"] if r["name"] == "irrelevant-citation")
        result = alignment.matrix_result(scenario, row)
        assert result["validatorAccepted"]
        assert result["outcome"] == "FAIL"


def test_known_error_remains_fail_with_other_missing_output_fields() -> None:
    scenario = MATRIX["scenarios"][0]
    row = copy.deepcopy(next(r for r in scenario["candidates"] if r["name"] == "high-insufficient"))
    row["candidate"].pop("recommendedChecks")
    assert alignment.matrix_result(scenario, row)["outcome"] == "FAIL"


def test_new_gt_cannot_reintroduce_empty_array_contradiction() -> None:
    with pytest.raises(ValueError, match="cannot also require literal hypotheses"):
        GroundTruth.model_validate_json(
            json.dumps(
                {
                    "ground_truth_id": "test",
                    "version": "v1",
                    "diagnosis_contract": "insufficient-evidence-v1",
                    "expected_facts": [{"name": "rootCauseHypotheses", "value": []}],
                }
            )
        )


def test_conflict_input_contains_opposing_records_not_only_a_label() -> None:
    scenario = next(s for s in MATRIX["scenarios"] if s["name"] == "actual-conflict")
    records = [
        json.loads(s["content"])
        for s in scenario["supportingContext"]
        if s["source_id"] in {"gateway:r-17", "service:r-17"}
    ]
    assert len(records) == 2
    assert {r["requestId"] for r in records} == {"r-17"}
    assert {r["upstreamStarted"] for r in records} == {True, False}


def test_complete_invalid_response_differs_from_a_truncated_export() -> None:
    for scenario in MATRIX["scenarios"]:
        rows = {r["name"]: r for r in scenario["candidates"]}
        assert rows["missing-output"]["candidate"] == rows["truncated-export"]["candidate"]
        assert alignment.matrix_result(scenario, rows["missing-output"])["outcome"] == "FAIL"
        assert alignment.matrix_result(scenario, rows["truncated-export"])["outcome"] == "UNKNOWN"


@pytest.mark.parametrize(
    "field,value", [("projectId", 999), ("runId", 999), ("reportId", "report:999")]
)
def test_changed_report_identity_is_a_known_violation(field: str, value: object) -> None:
    scenario = MATRIX["scenarios"][0]
    row = copy.deepcopy(scenario["candidates"][0])
    row["candidate"][field] = value
    result = alignment.matrix_result(scenario, row)
    assert not result["validatorAccepted"]
    assert result["outcome"] == "FAIL"


def test_candidate_self_review_is_not_accepted() -> None:
    scenario = MATRIX["scenarios"][0]
    row = copy.deepcopy(scenario["candidates"][0])
    row["candidate"]["diagnosis_content_reviews"] = [row["contentReview"]]
    result = alignment.matrix_result(scenario, row)
    assert not result["validatorAccepted"]
    assert result["outcome"] == "FAIL"


def test_partial_content_review_cannot_grant_pass() -> None:
    review = copy.deepcopy(MATRIX["scenarios"][0]["candidates"][0]["contentReview"])
    review["candidate_scope"] = "persisted_fields"
    with pytest.raises(ValueError, match="partial output content review"):
        GroundTruth.model_validate_json(
            json.dumps(
                {
                    "ground_truth_id": "test",
                    "version": "v1",
                    "diagnosis_contract": "insufficient-evidence-v1",
                    "diagnosis_content_reviews": [review],
                }
            )
        )


def test_persisted_known_content_error_still_fails_with_unavailable_full_report() -> None:
    scenario = MATRIX["scenarios"][0]
    row = copy.deepcopy(
        next(r for r in scenario["candidates"] if r["name"] == "unsupported-specific")
    )
    row["candidate"].pop("recommendedChecks")
    row["completeOriginal"] = False
    observation = observe_diagnosis_contract(
        row["candidate"], scenario["evidence"], complete_original=False
    )
    row["contentReview"]["candidate_scope"] = "persisted_fields"
    row["contentReview"]["candidate_digest"] = observation["persistedFieldsDigest"]
    row["contentReview"]["checks"]["limitations_and_checks"] = "UNKNOWN"
    assert alignment.matrix_result(scenario, row)["outcome"] == "FAIL"


def test_review_pass_cannot_override_a_deterministic_violation() -> None:
    scenario = MATRIX["scenarios"][0]
    row = copy.deepcopy(next(r for r in scenario["candidates"] if r["name"] == "high-insufficient"))
    row["contentReview"]["checks"] = dict.fromkeys(row["contentReview"]["checks"], "PASS")
    assert alignment.matrix_result(scenario, row)["outcome"] == "FAIL"


def test_new_revision_keeps_runtime_intent_and_inputs_separate_from_gt() -> None:
    for index in range(1, 9):
        old = alignment.read(alignment.AUDIT / f"evidence/{index:02d}.json")
        task = alignment.read(alignment.FIXTURES / f"tasks/{old['taskId']}.json")
        assert task["instruction"] == old["task"]["instruction"]
        assert task["initialState"] == old["task"]["initialState"]
        assert task["expectedOutput"] == old["task"]["expectedOutput"]
        assert "diagnosis_content_reviews" not in json.dumps(task)
        assert task["groundTruthRef"]["version"] != old["task"]["groundTruthRef"]["version"]


def test_new_metric_is_exported_and_aggregated_only_when_present(tmp_path: Path) -> None:
    from app.evaluator.metrics import MetricsCalculator
    from app.evaluator.models import EvaluationResult, MetricName
    from app.reports.reporting import export_evaluation_csv, read_evaluation_csv

    scenario = MATRIX["scenarios"][0]
    result = alignment.matrix_result(scenario, scenario["candidates"][0])
    evaluation = EvaluationResult.model_validate_json(json.dumps(result["evaluation"]))
    csv = export_evaluation_csv([evaluation], tmp_path / "new-contract.csv")
    assert read_evaluation_csv(csv).loc[0, "diagnosis_contract__value"] == 1
    aggregate = MetricsCalculator().calculate([evaluation])
    contract = next(m for m in aggregate.metrics if m.metric is MetricName.DIAGNOSIS_CONTRACT)
    assert contract.rate == 1
