"""Offline boundary tests with fixed clients; never calls a provider or Java."""

from __future__ import annotations

import asyncio
import copy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.agents.diagnosis_contract import observe_diagnosis_contract
from app.benchmark.diagnosis_retention import DiagnosisRetention, RetainingLLM
from app.evaluator import EvaluationCase, GroundTruth, MetricName, RuleBasedEvaluator
from app.evaluator.diagnosis_review_ingress import DIMENSIONS, load_content_review
from app.rag.context import ContextItem, ContextPackBuilder, ContextPolicy, ContextSource
from app.schemas.diagnosis_report import DiagnosisReport
from app.tracing.models import PromptIdentity
from app.tracing.recorder import TraceRecorder
from app.tracing.redaction import canonical_json_hash
from app.tracing.workflow import InstrumentedLLM, trace_step_scope

FIXTURES = Path(__file__).parent / "fixtures/revisions/insufficient-evidence-v1"


def fixture():
    scenario = json.loads((FIXTURES / "fixed-candidate-matrix.json").read_text(encoding="utf-8"))[
        "scenarios"
    ][0]
    candidate = scenario["candidates"][1]["candidate"]
    evidence = scenario["evidence"]
    observation = observe_diagnosis_contract(candidate, evidence)
    retained = {
        "taskId": "offline-boundary",
        "diagnosisReport": candidate,
        "boundedEvidence": evidence,
        "originalCandidateDigest": observation["candidateDigest"],
        "originalEvidenceDigest": observation["evidenceDigest"],
        "retainedCandidateDigest": canonical_json_hash(candidate),
        "retainedEvidenceDigest": canonical_json_hash(evidence),
        "redactionChangedCandidate": False,
    }
    review = {
        "method": "CODEX_REVIEW",
        "reviewer": "Codex",
        "outputSealDigest": "a" * 64,
        "taskId": retained["taskId"],
        "candidateDigest": retained["originalCandidateDigest"],
        "evidenceDigest": retained["originalEvidenceDigest"],
        "retainedCandidateDigest": retained["retainedCandidateDigest"],
        "retainedEvidenceDigest": retained["retainedEvidenceDigest"],
        "reference": "offline ingress fixture only",
        "rationale": "Boundary test reference",
        "dimensions": {
            name: {
                "verdict": "PASS",
                "reason": "Fixed ingress test evidence",
                "evidence": ["diagnosisReport#/summary", "boundedEvidence#/0"],
            }
            for name in DIMENSIONS
        },
    }
    return retained, review, observation


@pytest.mark.parametrize("mutation", ["candidate", "evidence", "seal", "reviewer", "dimension"])
def test_review_rejects_changed_candidate_evidence_or_authority(mutation):
    retained, review, _ = fixture()
    assert load_content_review(review, retained, seal_digest="a" * 64)
    if mutation == "candidate":
        retained["diagnosisReport"]["summary"] += " New assertion"
    elif mutation == "evidence":
        retained["boundedEvidence"][0]["content"] += " changed"
    elif mutation == "seal":
        review["outputSealDigest"] = "b" * 64
    elif mutation == "reviewer":
        review["method"] = "DETERMINISTIC_PROOF"
    else:
        review["dimensions"]["uncertainty"]["reason"] = " "
    with pytest.raises(ValueError):
        load_content_review(review, retained, seal_digest="a" * 64)


def test_external_ingress_does_not_reuse_gt_matrix_reviews_and_keeps_known_fail():
    retained, review, observation = fixture()
    bound = load_content_review(review, retained, seal_digest="a" * 64)
    truth = GroundTruth(
        ground_truth_id="gt:ingress",
        version="v1",
        diagnosis_contract="insufficient-evidence-v1",
        diagnosis_content_reviews=(bound,),
    )
    case = EvaluationCase.model_validate_json(
        json.dumps(
            {
                "case_id": "case:ingress",
                "trace_id": "trace:ingress",
                "agent_run_id": "agent:ingress",
                "ground_truth_id": truth.ground_truth_id,
                "ground_truth_version": truth.version,
                "facts": {
                    "structured_facts": [
                        {"name": "diagnosis_contract_observation", "value": observation}
                    ]
                },
                "applicable_metrics": ["diagnosis_contract"],
            }
        )
    )

    def metric(reviews):
        result = RuleBasedEvaluator().evaluate(case, truth, (), diagnosis_content_reviews=reviews)
        return next(item for item in result.metrics if item.metric is MetricName.DIAGNOSIS_CONTRACT)

    assert metric(()).status.value == "UNKNOWN"
    assert metric((bound,)).value == 1
    bad_review = copy.deepcopy(review)
    bad_review["dimensions"]["hypothesis_grounding"]["verdict"] = "FAIL"
    rejected = load_content_review(bad_review, retained, seal_digest="a" * 64)
    assert metric((rejected,)).value == 0
    observation["structuralIssues"] = ["HIGH with insufficient evidence"]
    changed = case.model_dump(mode="json")
    changed["facts"]["structured_facts"][0]["value"] = observation
    case = EvaluationCase.model_validate_json(json.dumps(changed))
    assert metric((bound,)).value == 0


def test_complete_model_boundary_retains_long_output_and_original_trace_hash(tmp_path):
    class Client:
        provider, model = "Qwen", "qwen3.8-max"

        async def complete(self, prompt):
            self.prompt = prompt
            return json.dumps(
                {
                    "summary": "x" * 1800,
                    "limitations": ["full limitations"],
                    "recommendedChecks": ["full checks"],
                }
            )

    client = Client()
    sink = DiagnosisRetention(tmp_path, ("private-test-credential",))
    recorder = TraceRecorder()
    prompt = 'Known facts and {"password":"private-test-credential"}'
    with trace_step_scope(
        recorder,
        trace_id="trace:retention",
        agent_run_id="agent:retention",
        agent_step_id="step:retention",
        prompt=PromptIdentity(name="diagnosis", version="v2"),
    ):
        output = asyncio.run(InstrumentedLLM(RetainingLLM(client, sink)).complete(prompt))
    assert client.prompt == prompt
    inputs = json.loads(next((tmp_path / "calls").glob("*-input.json")).read_text())
    outputs = json.loads(next((tmp_path / "calls").glob("*-output.json")).read_text())
    assert inputs["originalInputDigest"] == canonical_json_hash(prompt)
    assert inputs["retainedInputDigest"] != inputs["originalInputDigest"]
    assert "private-test-credential" not in json.dumps(inputs)
    assert len(json.loads(outputs["modelOutputRedacted"])["summary"]) == 1800
    assert outputs["originalOutputDigest"] == canonical_json_hash(output)


def test_retention_failure_is_latched_and_existing_file_cannot_be_overwritten(tmp_path):
    sink = DiagnosisRetention(tmp_path)
    sink.persist("test.json", {"first": True})
    with pytest.raises(RuntimeError, match="persistence failed"):
        sink.persist("test.json", {"second": True})
    assert sink.failure
    assert json.loads((tmp_path / "test.json").read_text()) == {"first": True}


def test_retention_bound_rejects_instead_of_truncating(tmp_path):
    with pytest.raises(ValueError, match="bound exceeded"):
        DiagnosisRetention(tmp_path).safe("x" * 2_000_001)


def test_final_report_requires_evidence_from_actual_model_input(tmp_path):
    from app.agents.diagnosis_contract import context_payload

    retained, _, _ = fixture()
    candidate = DiagnosisReport.model_validate(retained["diagnosisReport"])
    pack = ContextPackBuilder(
        ContextPolicy(source_precedence=tuple(ContextSource)),
        project_scope=41,
    ).build(
        (
            ContextItem(
                source_type=ContextSource.EXECUTION_FACT,
                source_id="test-report:fixture",
                content="Known I/O error; no HTTP response",
                project_scope=41,
            ),
        )
    )
    sink = DiagnosisRetention(tmp_path)
    recorder = TraceRecorder()

    class Client:
        provider, model = "Qwen", "qwen3.8-max"

        async def complete(self, prompt):
            return candidate.model_dump_json()

    prompt = json.dumps(context_payload(pack), ensure_ascii=False, sort_keys=True)
    with trace_step_scope(
        recorder,
        trace_id="trace:retention",
        agent_run_id="agent:retention",
        agent_step_id="step:retention",
        prompt=PromptIdentity(name="diagnosis", version="v2"),
    ):
        asyncio.run(InstrumentedLLM(RetainingLLM(Client(), sink)).complete(prompt))
    sink.observe(
        SimpleNamespace(benchmark_task_id="task:retention"), candidate, pack, recorder.typed_records
    )
    report = json.loads(next((tmp_path / "reports").glob("*.json")).read_text())
    assert report["diagnosisReport"] == candidate.model_dump(mode="json")
    assert report["originalEvidenceDigest"] == canonical_json_hash(context_payload(pack))
    assert report["evidenceVisibleInModelCallIds"]
    sink.original_prompts.clear()
    with pytest.raises(RuntimeError, match="diagnosis retention failed"):
        sink.observe(
            SimpleNamespace(benchmark_task_id="task:other"), candidate, pack, recorder.typed_records
        )
