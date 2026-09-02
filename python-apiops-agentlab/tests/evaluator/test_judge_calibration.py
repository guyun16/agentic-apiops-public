from __future__ import annotations

import pytest

from app.evaluator import (
    CalibrationFixture,
    FakeDeterministicJudge,
    JudgeConfiguration,
    JudgeDimension,
    JudgeRequest,
    JudgeResult,
    JudgeRubric,
    JudgeSubject,
    calibrate_judge,
)
from app.tracing import ModelIdentity, PromptIdentity


def configuration(*, prompt_version: str = "v1") -> JudgeConfiguration:
    return JudgeConfiguration(
        rubric=JudgeRubric(
            rubric_id="evidence-use-quality",
            version="v2",
            dimension=JudgeDimension.REASONING_EVIDENCE_USE_QUALITY,
            criteria=(
                "The explanation uses the cited evidence to support its conclusion.",
                "The explanation distinguishes evidence from unsupported inference.",
            ),
        ),
        prompt=PromptIdentity(name="llm-judge", version=prompt_version),
        model_identity=ModelIdentity(
            provider="fake-provider",
            model="deterministic-judge",
            version="fixture-v1",
        ),
    )


def request(case_id: str, config: JudgeConfiguration) -> JudgeRequest:
    return JudgeRequest(
        judge_case_id=case_id,
        trace_id=f"trace-{case_id}",
        agent_run_id=f"run-{case_id}",
        subject=JudgeSubject(
            candidate_summary="The diagnosis cites the timeout evidence before its conclusion.",
            reference_summary="A supported explanation must cite timeout evidence.",
            evidence_references=(f"evidence-{case_id}",),
        ),
        configuration=config,
    )


def result(current: JudgeRequest, score: float) -> JudgeResult:
    return JudgeResult(
        judge_result_id=f"result-{current.judge_case_id}",
        judge_case_id=current.judge_case_id,
        trace_id=current.trace_id,
        agent_run_id=current.agent_run_id,
        dimension=current.configuration.rubric.dimension,
        score=score,
        reason="Preset deterministic calibration result.",
        configuration=current.configuration,
    )


def fixtures() -> tuple[tuple[CalibrationFixture, ...], tuple[JudgeResult, ...]]:
    config = configuration()
    aligned_request = request("aligned", config)
    disagreement_request = request("disagreement", config)
    calibration_fixtures = (
        CalibrationFixture(
            fixture_id="fixture-aligned",
            human_label_source="reviewer-set-a",
            human_label_version="2026-08-23",
            expected_human_score=0.8,
            tolerance=0.1,
            request=aligned_request,
        ),
        CalibrationFixture(
            fixture_id="fixture-disagreement",
            human_label_source="reviewer-set-a",
            human_label_version="2026-08-23",
            expected_human_score=0.2,
            tolerance=0.1,
            request=disagreement_request,
        ),
    )
    judge_results = (
        result(aligned_request, 0.85),
        result(disagreement_request, 0.9),
    )
    return calibration_fixtures, judge_results


@pytest.mark.anyio
async def test_calibration_records_agreement_and_disagreement_without_overwrite() -> None:
    calibration_fixtures, judge_results = fixtures()

    calibration = await calibrate_judge(
        FakeDeterministicJudge(judge_results),
        calibration_fixtures,
    )
    aligned, disagreement = calibration.case_results

    assert aligned.agrees is True
    assert aligned.expected_human_score == 0.8
    assert aligned.judge_result.score == 0.85
    assert disagreement.agrees is False
    assert disagreement.expected_human_score == 0.2
    assert disagreement.judge_result.score == 0.9
    assert disagreement.absolute_error == pytest.approx(0.7)
    assert calibration.agreement_count == 1
    assert calibration.disagreement_count == 1
    assert calibration.agreement_rate == 0.5


@pytest.mark.anyio
async def test_calibration_preserves_full_judge_configuration_identity() -> None:
    calibration_fixtures, judge_results = fixtures()

    calibration = await calibrate_judge(
        FakeDeterministicJudge(judge_results),
        calibration_fixtures,
    )

    assert calibration.configuration.rubric.rubric_id == "evidence-use-quality"
    assert calibration.configuration.rubric.version == "v2"
    assert calibration.configuration.prompt.version == "v1"
    assert calibration.configuration.model_identity.model == "deterministic-judge"
    assert calibration.configuration.model_identity.version == "fixture-v1"


@pytest.mark.anyio
async def test_calibration_is_deterministic_for_fixed_fixtures_and_fake_results() -> None:
    calibration_fixtures, judge_results = fixtures()

    first = await calibrate_judge(
        FakeDeterministicJudge(judge_results),
        calibration_fixtures,
    )
    second = await calibrate_judge(
        FakeDeterministicJudge(judge_results),
        calibration_fixtures,
    )

    assert first == second


@pytest.mark.anyio
async def test_calibration_rejects_mixed_judge_configurations() -> None:
    calibration_fixtures, judge_results = fixtures()
    mixed_request = request("mixed", configuration(prompt_version="v2"))
    mixed_fixture = CalibrationFixture(
        fixture_id="fixture-mixed",
        human_label_source="reviewer-set-a",
        human_label_version="2026-08-23",
        expected_human_score=0.5,
        tolerance=0.1,
        request=mixed_request,
    )

    with pytest.raises(ValueError, match="one Judge configuration"):
        await calibrate_judge(
            FakeDeterministicJudge(judge_results + (result(mixed_request, 0.5),)),
            calibration_fixtures + (mixed_fixture,),
        )
