from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from app.clients.llm import LLMClient
from app.evaluator import (
    EvaluationCase,
    FakeDeterministicJudge,
    GroundTruth,
    Judge,
    JudgeConfiguration,
    JudgeDimension,
    JudgeRequest,
    JudgeResult,
    JudgeRubric,
    JudgeSubject,
    LLMJudge,
    RuleBasedEvaluator,
    ValidityFacts,
)
from app.guardrails import EvidenceSource, SafetyViolation, ViolationCode
from app.schemas.diagnosis_report import DiagnosisReport
from app.schemas.tool_result import ToolResult
from app.tracing import ModelIdentity, PromptIdentity
from app.workflows.candidate_validation import CandidateValidationResult, ValidationIssue


def configuration() -> JudgeConfiguration:
    return JudgeConfiguration(
        rubric=JudgeRubric(
            rubric_id="diagnosis-semantic-quality",
            version="v1",
            dimension=JudgeDimension.DIAGNOSIS_QUALITY,
            criteria=(
                "The diagnosis addresses the supplied reference root cause.",
                "The explanation does not claim unsupported execution facts.",
            ),
        ),
        prompt=PromptIdentity(name="llm-judge", version="v1"),
        model_identity=ModelIdentity(
            provider="fake-provider",
            model="deterministic-judge",
            version="fixture-v1",
        ),
    )


def request(case_id: str = "judge-case-1") -> JudgeRequest:
    return JudgeRequest(
        judge_case_id=case_id,
        trace_id="trace-1",
        agent_run_id="run-1",
        subject=JudgeSubject(
            candidate_summary="The upstream schema changed the required order identifier.",
            reference_summary="The request failed after an upstream schema change.",
            evidence_references=("evidence-1",),
        ),
        configuration=configuration(),
    )


def result(
    case_id: str = "judge-case-1",
    *,
    score: float = 0.9,
    reason: str = "The diagnosis is relevant and supported by the supplied evidence reference.",
) -> JudgeResult:
    current = request(case_id)
    return JudgeResult(
        judge_result_id=f"judge-result-{case_id}",
        judge_case_id=case_id,
        trace_id=current.trace_id,
        agent_run_id=current.agent_run_id,
        dimension=current.configuration.rubric.dimension,
        score=score,
        reason=reason,
        configuration=current.configuration,
    )


def test_judge_result_preserves_score_reason_and_configuration_identity() -> None:
    judged = result()

    assert judged.score == 0.9
    assert judged.reason.startswith("The diagnosis")
    assert judged.configuration.rubric.rubric_id == "diagnosis-semantic-quality"
    assert judged.configuration.rubric.version == "v1"
    assert judged.configuration.prompt.version == "v1"
    assert judged.configuration.model_identity.model == "deterministic-judge"
    assert judged.configuration.model_identity.version == "fixture-v1"
    with pytest.raises(ValidationError):
        judged.score = 0.1  # type: ignore[misc]


@pytest.mark.anyio
async def test_fake_judge_is_protocol_compatible_repeatable_and_network_free() -> None:
    expected = result()
    fake = FakeDeterministicJudge((expected,))
    current = request()

    assert isinstance(fake, Judge)
    assert await fake.judge(current) is expected
    assert await fake.judge(current) is expected
    assert fake.calls == [current, current]


@pytest.mark.anyio
async def test_llm_judge_is_a_thin_adapter_over_existing_llm_protocol() -> None:
    class DeterministicLLM:
        def __init__(self) -> None:
            self.prompts: list[str] = []

        async def complete(self, prompt: str) -> str:
            self.prompts.append(prompt)
            return '{"score":0.75,"reason":"The diagnosis is mostly supported."}'

    llm = DeterministicLLM()
    assert isinstance(llm, LLMClient)
    judge = LLMJudge(llm)

    first = await judge.judge(request())
    second = await judge.judge(request())
    prompt = json.loads(llm.prompts[0])

    assert first == second
    assert first.score == 0.75
    assert prompt["rubric"]["rubric_id"] == "diagnosis-semantic-quality"
    assert prompt["rubric"]["version"] == "v1"
    assert prompt["judge_prompt"]["version"] == "v1"
    assert len(llm.prompts) == 2


def test_judge_configuration_requires_versioned_model_identity() -> None:
    with pytest.raises(ValidationError, match="requires a version"):
        JudgeConfiguration(
            rubric=configuration().rubric,
            prompt=configuration().prompt,
            model_identity=ModelIdentity(provider="fake", model="judge"),
        )


def test_rule_based_evaluator_does_not_call_judge() -> None:
    fake = FakeDeterministicJudge((result(),))
    case = EvaluationCase(
        case_id="case-1",
        trace_id="trace-1",
        agent_run_id="run-1",
        ground_truth_id="gt-1",
        ground_truth_version="v1",
    )
    truth = GroundTruth(ground_truth_id="gt-1", version="v1")

    RuleBasedEvaluator().evaluate(case, truth, ())

    assert fake.calls == []


def authority_facts() -> tuple[
    ToolResult,
    DiagnosisReport,
    CandidateValidationResult,
    SafetyViolation,
]:
    tool = ToolResult.model_validate(
        {
            "schemaVersion": "0.1.0",
            "toolCallId": "java-call-denied",
            "status": "FORBIDDEN",
            "data": None,
            "error": {"code": "DENIED"},
            "sanitized": True,
            "traceId": "trace-1",
        }
    )
    diagnosis = DiagnosisReport.model_validate(
        {
            "schemaVersion": "0.1.0",
            "reportId": "report-timeout",
            "agentRunId": "run-1",
            "projectId": 1,
            "runId": 10,
            "failureType": "TIMEOUT",
            "summary": "Runner timed out.",
            "rootCauseHypotheses": [],
            "sufficientEvidence": False,
            "limitations": ["No terminal Runner result was returned."],
            "recommendedChecks": ["Inspect the Java Runner timeout evidence."],
            "traceId": "trace-1",
        }
    )
    validation = CandidateValidationResult(
        issues=(
            ValidationIssue(
                code="SHARED_SCHEMA_REQUIRED",
                path="/schemaVersion",
                layer="SCHEMA",
                message="Required property is missing.",
            ),
        )
    )
    violation = SafetyViolation(
        code=ViolationCode.PROMPT_INJECTION_DETECTED,
        source=EvidenceSource.TOOL_RESULT,
        trace_id="trace-1",
        agent_run_id="run-1",
        tool_name="rag.search",
    )
    return tool, diagnosis, validation, violation


@pytest.mark.anyio
async def test_high_judge_score_cannot_change_authoritative_execution_facts() -> None:
    tool, diagnosis, validation, violation = authority_facts()
    validity = ValidityFacts(schema_valid=False, contract_accepted=False)
    snapshots = (
        tool.model_dump(),
        diagnosis.model_dump(),
        validation.model_dump(),
        violation.model_dump(),
        validity.model_dump(),
    )

    judged = await FakeDeterministicJudge((result(score=1.0),)).judge(request())

    assert judged.score == 1.0
    assert tool.status == "FORBIDDEN"
    assert diagnosis.failure_type == "TIMEOUT"
    assert validation.valid is False
    assert validity.schema_valid is False
    assert validity.contract_accepted is False
    assert violation.code is ViolationCode.PROMPT_INJECTION_DETECTED
    assert snapshots == (
        tool.model_dump(),
        diagnosis.model_dump(),
        validation.model_dump(),
        violation.model_dump(),
        validity.model_dump(),
    )


@pytest.mark.anyio
async def test_judge_failure_does_not_modify_execution_facts() -> None:
    class FailingJudge:
        async def judge(self, current: JudgeRequest) -> JudgeResult:
            raise RuntimeError("judge unavailable")

    facts = authority_facts()
    before = tuple(fact.model_dump() for fact in facts)

    with pytest.raises(RuntimeError, match="judge unavailable"):
        await FailingJudge().judge(request())

    assert tuple(fact.model_dump() for fact in facts) == before
