"""Small human-labeled calibration boundary for one Judge configuration."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Annotated

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictFloat,
    StrictInt,
    StrictStr,
)

from app.tracing import canonical_json_hash

from .judge import Judge, JudgeConfiguration, JudgeRequest, JudgeResult

NonEmptyString = Annotated[StrictStr, Field(min_length=1)]
CalibrationScore = Annotated[StrictFloat, Field(ge=0, le=1)]
NonNegativeFloat = Annotated[StrictFloat, Field(ge=0)]
NonNegativeInt = Annotated[StrictInt, Field(ge=0)]


class _CalibrationModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        populate_by_name=False,
        strict=True,
        frozen=True,
        validate_default=True,
    )


class CalibrationFixture(_CalibrationModel):
    """One immutable human/known score under the request's versioned rubric."""

    fixture_id: NonEmptyString
    human_label_source: NonEmptyString
    human_label_version: NonEmptyString
    expected_human_score: CalibrationScore
    tolerance: CalibrationScore
    request: JudgeRequest


class CalibrationCaseResult(_CalibrationModel):
    """Preserves both labels so disagreement cannot overwrite the human score."""

    fixture_id: NonEmptyString
    human_label_source: NonEmptyString
    human_label_version: NonEmptyString
    expected_human_score: CalibrationScore
    tolerance: CalibrationScore
    judge_result: JudgeResult
    absolute_error: NonNegativeFloat
    agrees: StrictBool


class JudgeCalibrationResult(_CalibrationModel):
    calibration_id: NonEmptyString
    configuration: JudgeConfiguration
    case_results: tuple[CalibrationCaseResult, ...] = Field(min_length=1)
    agreement_count: NonNegativeInt
    disagreement_count: NonNegativeInt
    agreement_rate: CalibrationScore


def _result_matches_fixture(result: JudgeResult, fixture: CalibrationFixture) -> bool:
    request = fixture.request
    return (
        result.judge_case_id == request.judge_case_id
        and result.trace_id == request.trace_id
        and result.agent_run_id == request.agent_run_id
        and result.configuration == request.configuration
        and result.dimension is request.configuration.rubric.dimension
    )


async def calibrate_judge(
    judge: Judge,
    fixtures: Sequence[CalibrationFixture],
) -> JudgeCalibrationResult:
    """Compare one fixed Judge configuration with immutable human/known scores."""

    if not fixtures:
        raise ValueError("calibration requires at least one fixture")
    configuration = fixtures[0].request.configuration
    if any(fixture.request.configuration != configuration for fixture in fixtures):
        raise ValueError("calibration fixtures must use one Judge configuration")
    fixture_ids = [fixture.fixture_id for fixture in fixtures]
    if len(fixture_ids) != len(set(fixture_ids)):
        raise ValueError("calibration fixture_id values must be unique")

    cases: list[CalibrationCaseResult] = []
    for fixture in fixtures:
        result = await judge.judge(fixture.request)
        if not _result_matches_fixture(result, fixture):
            raise ValueError("JudgeResult metadata does not match calibration fixture")
        absolute_error = abs(result.score - fixture.expected_human_score)
        cases.append(
            CalibrationCaseResult(
                fixture_id=fixture.fixture_id,
                human_label_source=fixture.human_label_source,
                human_label_version=fixture.human_label_version,
                expected_human_score=fixture.expected_human_score,
                tolerance=fixture.tolerance,
                judge_result=result,
                absolute_error=absolute_error,
                agrees=absolute_error <= fixture.tolerance,
            )
        )

    agreement_count = sum(case.agrees for case in cases)
    material = {
        "configuration": configuration.model_dump(mode="json"),
        "case_results": [case.model_dump(mode="json") for case in cases],
    }
    return JudgeCalibrationResult(
        calibration_id=f"judge_calibration:{canonical_json_hash(material)[:24]}",
        configuration=configuration,
        case_results=tuple(cases),
        agreement_count=agreement_count,
        disagreement_count=len(cases) - agreement_count,
        agreement_rate=agreement_count / len(cases),
    )


__all__ = [
    "CalibrationCaseResult",
    "CalibrationFixture",
    "JudgeCalibrationResult",
    "calibrate_judge",
]
