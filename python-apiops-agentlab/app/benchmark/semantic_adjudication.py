"""Opt-in Stage 21 semantic adjudication over the existing Stage 19 Judge.

This module is evaluation-only.  It runs after Agent execution and accepts only
projected candidate facts plus an explicit evaluation-side reference.  It never
reads or changes workflow state, Tool state, Runner state, or Agent context.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictStr, model_validator

from app.evaluator import (
    EvaluationCase,
    EvaluationFacts,
    EvaluationResult,
    Judge,
    JudgeCalibrationResult,
    JudgeConfiguration,
    JudgeDimension,
    JudgeRequest,
    JudgeResult,
    JudgeSubject,
    MetricName,
    MetricStatus,
)
from app.tracing import safe_summary

from .models import TaskType
from .success import TaskSuccessCondition, TaskSuccessStatus

NonEmptyString = Annotated[StrictStr, Field(min_length=1)]
BoundedReason = Annotated[StrictStr, Field(min_length=1, max_length=1024)]

_ROOT_CAUSE_FACT_NAMES = ("root_cause_hypotheses", "rootCauseHypotheses")
_DIAGNOSIS_TASK_TYPES = frozenset({TaskType.FAILURE_DIAGNOSIS, TaskType.E2E_APIOPS})


class _SemanticModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        populate_by_name=True,
        strict=True,
        frozen=True,
        validate_default=True,
    )

    def model_dump(self, **kwargs: object) -> dict[str, object]:
        kwargs.setdefault("by_alias", True)
        return super().model_dump(**kwargs)


class SemanticDecision(StrEnum):
    SEMANTIC_MATCH = "SEMANTIC_MATCH"
    SEMANTIC_MISMATCH = "SEMANTIC_MISMATCH"
    UNRESOLVED = "UNRESOLVED"
    NOT_ELIGIBLE = "NOT_ELIGIBLE"


class RootCauseSemanticReference(_SemanticModel):
    """A versioned reference that is allowed to exist only on the eval side."""

    reference_id: NonEmptyString = Field(alias="referenceId")
    version: NonEmptyString
    benchmark_task_id: NonEmptyString = Field(alias="benchmarkTaskId")
    ground_truth_id: NonEmptyString = Field(alias="groundTruthId")
    ground_truth_version: NonEmptyString = Field(alias="groundTruthVersion")
    statements: tuple[NonEmptyString, ...] = Field(min_length=1)
    evidence_references: tuple[NonEmptyString, ...] = Field(
        default=(), alias="evidenceReferences"
    )

    @model_validator(mode="after")
    def references_must_be_unique(self) -> RootCauseSemanticReference:
        if len(self.statements) != len(set(self.statements)):
            raise ValueError("root-cause reference statements must be unique")
        if len(self.evidence_references) != len(set(self.evidence_references)):
            raise ValueError("root-cause reference evidence must be unique")
        return self


class RootCauseSemanticCandidate(_SemanticModel):
    """Only the candidate statements and their already-observed evidence IDs."""

    statements: tuple[NonEmptyString, ...] = Field(min_length=1)
    evidence_references: tuple[NonEmptyString, ...] = Field(
        default=(), alias="evidenceReferences"
    )
    source: NonEmptyString

    @model_validator(mode="after")
    def references_must_be_unique(self) -> RootCauseSemanticCandidate:
        if len(self.statements) != len(set(self.statements)):
            raise ValueError("root-cause candidate statements must be unique")
        if len(self.evidence_references) != len(set(self.evidence_references)):
            raise ValueError("root-cause candidate evidence must be unique")
        return self


class SemanticAdjudicationResult(_SemanticModel):
    """Auditable Stage 21 interpretation of one Stage 19 Judge opinion."""

    dimension: JudgeDimension
    eligible: StrictBool
    decision: SemanticDecision
    reason: BoundedReason
    judge_result: JudgeResult | None = Field(default=None, alias="judgeResult")
    rubric_version: NonEmptyString | None = Field(default=None, alias="rubricVersion")
    deterministic_basis: tuple[NonEmptyString, ...] = Field(
        default=(), alias="deterministicBasis"
    )
    candidate_source: NonEmptyString | None = Field(default=None, alias="candidateSource")
    reference_source: NonEmptyString | None = Field(default=None, alias="referenceSource")
    used_for_final_outcome: StrictBool = Field(default=False, alias="usedForFinalOutcome")

    @model_validator(mode="after")
    def result_fields_must_agree(self) -> SemanticAdjudicationResult:
        if self.decision in {
            SemanticDecision.SEMANTIC_MATCH,
            SemanticDecision.SEMANTIC_MISMATCH,
        } and (not self.eligible or self.judge_result is None):
            raise ValueError("a semantic decision requires an eligible JudgeResult")
        if self.judge_result is not None:
            if self.judge_result.dimension is not self.dimension:
                raise ValueError("semantic result dimension must match JudgeResult")
            if self.rubric_version != self.judge_result.configuration.rubric.version:
                raise ValueError("semantic result rubric version must match JudgeResult")
        if self.used_for_final_outcome and self.decision not in {
            SemanticDecision.SEMANTIC_MATCH,
            SemanticDecision.SEMANTIC_MISMATCH,
        }:
            raise ValueError("only a resolved semantic decision can affect final outcome")
        return self


def _unique(values: Sequence[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(values))


def extract_root_cause_candidate(
    facts: EvaluationFacts,
) -> RootCauseSemanticCandidate | None:
    """Read only the canonical Task 1 projection; malformed facts stay absent."""

    values = [fact.value for fact in facts.structured_facts if fact.name in _ROOT_CAUSE_FACT_NAMES]
    if not values or any(value != values[0] for value in values[1:]):
        return None
    raw_hypotheses = values[0]
    if not isinstance(raw_hypotheses, list) or not raw_hypotheses:
        return None

    statements: list[str] = []
    evidence: list[str] = []
    for raw_hypothesis in raw_hypotheses:
        if not isinstance(raw_hypothesis, Mapping):
            return None
        statement = raw_hypothesis.get("statement")
        raw_references = raw_hypothesis.get("evidenceRefs")
        if not isinstance(statement, str) or not statement.strip():
            return None
        if not isinstance(raw_references, list) or not raw_references:
            return None
        statements.append(statement.strip())
        for raw_reference in raw_references:
            if not isinstance(raw_reference, Mapping):
                return None
            item_id = raw_reference.get("itemId")
            if not isinstance(item_id, str) or not item_id.strip():
                return None
            evidence.append(item_id.strip())

    try:
        candidate = RootCauseSemanticCandidate(
            statements=_unique(statements),
            evidenceReferences=_unique(evidence),
            source="EvaluationFacts.structured_facts[root_cause_hypotheses]",
        )
    except ValueError:
        return None
    observed_evidence = set(facts.evidence_ids or ())
    if not set(candidate.evidence_references).issubset(observed_evidence):
        return None
    return candidate


def build_root_cause_judge_request(
    case: EvaluationCase,
    candidate: RootCauseSemanticCandidate,
    reference: RootCauseSemanticReference,
    configuration: JudgeConfiguration,
) -> JudgeRequest:
    """Build the bounded evaluation-only request sent to the reused Judge."""

    candidate_summary, _ = safe_summary("\n".join(candidate.statements), max_chars=4096)
    reference_summary, _ = safe_summary("\n".join(reference.statements), max_chars=4096)
    return JudgeRequest(
        judge_case_id=(
            f"semantic:{case.case_id}:root-cause:{reference.reference_id}:{reference.version}"
        ),
        trace_id=case.trace_id,
        agent_run_id=case.agent_run_id,
        subject=JudgeSubject(
            candidate_summary=candidate_summary,
            reference_summary=reference_summary,
            evidence_references=_unique(
                (*candidate.evidence_references, *reference.evidence_references)
            ),
        ),
        configuration=configuration,
    )


def _result_matches_request(result: JudgeResult, request: JudgeRequest) -> bool:
    return (
        result.judge_case_id == request.judge_case_id
        and result.trace_id == request.trace_id
        and result.agent_run_id == request.agent_run_id
        and result.configuration == request.configuration
        and result.dimension is request.configuration.rubric.dimension
    )


class SemanticAdjudicator:
    """Fail-closed allowlist gate and thin adapter over Stage 19 Judge."""

    def __init__(
        self,
        judge: Judge | None = None,
        *,
        configuration: JudgeConfiguration | None = None,
        calibration: JudgeCalibrationResult | None = None,
    ) -> None:
        if judge is not None and not isinstance(judge, Judge):
            raise TypeError("judge must implement the Stage 19 Judge protocol")
        self._judge = judge
        self._configuration = configuration
        self._calibration = calibration

    async def adjudicate(
        self,
        *,
        task_id: str,
        task_type: TaskType,
        case: EvaluationCase,
        evaluation_result: EvaluationResult,
        deterministic_status: TaskSuccessStatus | str = TaskSuccessStatus.UNKNOWN,
        deterministic_conditions: Sequence[TaskSuccessCondition] | None = None,
        reference: RootCauseSemanticReference | None = None,
        dimension: JudgeDimension = JudgeDimension.DIAGNOSIS_QUALITY,
    ) -> SemanticAdjudicationResult:
        """Apply the eligibility gate, then call Judge at most once."""

        try:
            status = TaskSuccessStatus(deterministic_status)
        except (TypeError, ValueError):
            return self._not_eligible(
                dimension,
                "invalid deterministic outcome status",
                basis=("deterministic_status=INVALID",),
            )
        basis = (f"deterministic_status={status.value}",)

        if status in {TaskSuccessStatus.PASS, TaskSuccessStatus.FAIL}:
            return self._not_eligible(
                dimension,
                "deterministic outcome is already decisive; Judge was not called",
                basis=basis,
            )
        if dimension is not JudgeDimension.DIAGNOSIS_QUALITY:
            return self._not_eligible(
                dimension,
                "semantic dimension is not in the Stage 21 allowlist",
                basis=basis,
            )
        if task_type not in _DIAGNOSIS_TASK_TYPES:
            return self._not_eligible(
                dimension,
                "task type has no allowlisted diagnosis root-cause semantic question",
                basis=basis,
            )
        if not self._evaluation_identity_matches(case, evaluation_result):
            return self._unresolved(
                dimension,
                "EvaluationCase and EvaluationResult identities do not match",
                basis=basis,
            )
        if not self._only_root_cause_ambiguity(evaluation_result, deterministic_conditions):
            return self._unresolved(
                dimension,
                "deterministic uncertainty is not limited to root-cause semantics",
                basis=basis,
            )

        candidate = extract_root_cause_candidate(case.facts)
        if candidate is None:
            return self._unresolved(
                dimension,
                "candidate root-cause semantic artifact is missing or malformed",
                basis=basis,
            )
        if reference is None:
            return self._unresolved(
                dimension,
                "authoritative root-cause semantic reference is missing",
                basis=basis,
                candidate_source=candidate.source,
                reference_source="GroundTruth semantic reference: unavailable",
            )
        if not self._reference_matches_case(task_id, case, reference):
            return self._unresolved(
                dimension,
                "task or GroundTruth semantic reference identity is invalid",
                basis=basis,
                candidate_source=candidate.source,
                reference_source=f"{reference.reference_id}@{reference.version}",
            )
        if self._judge is None or self._configuration is None:
            return self._unresolved(
                dimension,
                "Stage 19 Judge configuration is unavailable",
                basis=basis,
                candidate_source=candidate.source,
                reference_source=f"{reference.reference_id}@{reference.version}",
            )
        if not self._calibration_matches_configuration(
            self._calibration,
            self._configuration,
        ):
            return self._unresolved(
                dimension,
                "Stage 19 Judge calibration is unavailable or mismatched",
                basis=basis,
                candidate_source=candidate.source,
                reference_source=f"{reference.reference_id}@{reference.version}",
                rubric_version=self._configuration.rubric.version,
            )
        if self._configuration.rubric.dimension is not dimension:
            return self._not_eligible(
                dimension,
                "Judge rubric dimension is not the allowlisted diagnosis dimension",
                basis=basis,
                candidate_source=candidate.source,
                reference_source=f"{reference.reference_id}@{reference.version}",
                rubric_version=self._configuration.rubric.version,
            )

        request = build_root_cause_judge_request(
            case,
            candidate,
            reference,
            self._configuration,
        )
        try:
            result = await self._judge.judge(request)
        except Exception:
            return self._unresolved(
                dimension,
                "Stage 19 Judge failed; semantic decision remains unresolved",
                basis=basis,
                candidate_source=candidate.source,
                reference_source=f"{reference.reference_id}@{reference.version}",
                rubric_version=self._configuration.rubric.version,
            )
        if not isinstance(result, JudgeResult) or not _result_matches_request(result, request):
            return self._unresolved(
                dimension,
                "Stage 19 Judge returned malformed or mismatched metadata",
                basis=basis,
                candidate_source=candidate.source,
                reference_source=f"{reference.reference_id}@{reference.version}",
                rubric_version=self._configuration.rubric.version,
                judge_result=result if isinstance(result, JudgeResult) else None,
            )

        if result.score == 1.0:
            decision = SemanticDecision.SEMANTIC_MATCH
            reason = "Stage 19 Judge returned the exact calibrated match endpoint"
        elif result.score == 0.0:
            decision = SemanticDecision.SEMANTIC_MISMATCH
            reason = "Stage 19 Judge returned the exact calibrated mismatch endpoint"
        else:
            decision = SemanticDecision.UNRESOLVED
            reason = (
                "Judge score has no formal binary interpretation; semantic result is unresolved"
            )
        return SemanticAdjudicationResult(
            dimension=dimension,
            eligible=True,
            decision=decision,
            reason=reason,
            judgeResult=result,
            rubricVersion=self._configuration.rubric.version,
            deterministicBasis=basis,
            candidateSource=candidate.source,
            referenceSource=f"{reference.reference_id}@{reference.version}",
        )

    @staticmethod
    def _evaluation_identity_matches(
        case: EvaluationCase,
        evaluation_result: EvaluationResult,
    ) -> bool:
        return (
            case.case_id == evaluation_result.case_id
            and case.trace_id == evaluation_result.trace_id
            and case.agent_run_id == evaluation_result.agent_run_id
            and case.ground_truth_id == evaluation_result.ground_truth_id
            and case.ground_truth_version == evaluation_result.ground_truth_version
        )

    @staticmethod
    def _reference_matches_case(
        task_id: str,
        case: EvaluationCase,
        reference: RootCauseSemanticReference,
    ) -> bool:
        return (
            reference.benchmark_task_id == task_id
            and reference.ground_truth_id == case.ground_truth_id
            and reference.ground_truth_version == case.ground_truth_version
        )

    @staticmethod
    def _only_root_cause_ambiguity(
        evaluation_result: EvaluationResult,
        deterministic_conditions: Sequence[TaskSuccessCondition] | None,
    ) -> bool:
        if deterministic_conditions is not None and any(
            condition.status not in {TaskSuccessStatus.PASS, TaskSuccessStatus.NOT_APPLICABLE}
            and condition.metric is not MetricName.DIAGNOSIS_ACCURACY
            for condition in deterministic_conditions
        ):
            return False

        by_metric = {sample.metric: sample for sample in evaluation_result.metrics}
        diagnosis = by_metric.get(MetricName.DIAGNOSIS_ACCURACY)
        if diagnosis is None or diagnosis.status not in {
            MetricStatus.UNKNOWN,
            MetricStatus.NOT_APPLICABLE,
        }:
            return False

        protected_metrics = {
            MetricName.VALID_JSON,
            MetricName.SCHEMA_VALID,
            MetricName.CONTRACT_ACCEPTED,
            MetricName.EXACT_MATCH,
            MetricName.TOOL_PRECISION,
            MetricName.TOOL_RECALL,
            MetricName.TOOL_EXACT_SET_MATCH,
            MetricName.PARAMETER_ACCURACY,
            MetricName.EVIDENCE_HIT,
            MetricName.SAFETY_ACCURACY,
        }
        return all(
            sample.status is MetricStatus.NOT_APPLICABLE
            or (
                sample.status is MetricStatus.VALUE
                and sample.value == 1
            )
            for sample in evaluation_result.metrics
            if sample.metric in protected_metrics
            and sample.metric is not MetricName.DIAGNOSIS_ACCURACY
        )

    @staticmethod
    def _calibration_matches_configuration(
        calibration: JudgeCalibrationResult | None,
        configuration: JudgeConfiguration,
    ) -> bool:
        return (
            calibration is not None
            and bool(calibration.case_results)
            and calibration.configuration == configuration
            and all(
                case.judge_result.configuration == configuration
                and case.judge_result.dimension is configuration.rubric.dimension
                for case in calibration.case_results
            )
        )

    @staticmethod
    def _not_eligible(
        dimension: JudgeDimension,
        reason: str,
        *,
        basis: tuple[str, ...] = (),
        candidate_source: str | None = None,
        reference_source: str | None = None,
        rubric_version: str | None = None,
    ) -> SemanticAdjudicationResult:
        return SemanticAdjudicationResult(
            dimension=dimension,
            eligible=False,
            decision=SemanticDecision.NOT_ELIGIBLE,
            reason=reason,
            rubricVersion=rubric_version,
            deterministicBasis=basis,
            candidateSource=candidate_source,
            referenceSource=reference_source,
        )

    @staticmethod
    def _unresolved(
        dimension: JudgeDimension,
        reason: str,
        *,
        basis: tuple[str, ...] = (),
        candidate_source: str | None = None,
        reference_source: str | None = None,
        rubric_version: str | None = None,
        judge_result: JudgeResult | None = None,
    ) -> SemanticAdjudicationResult:
        return SemanticAdjudicationResult(
            dimension=dimension,
            eligible=judge_result is not None,
            decision=SemanticDecision.UNRESOLVED,
            reason=reason,
            judgeResult=judge_result,
            rubricVersion=rubric_version,
            deterministicBasis=basis,
            candidateSource=candidate_source,
            referenceSource=reference_source,
        )


__all__ = [
    "RootCauseSemanticCandidate",
    "RootCauseSemanticReference",
    "SemanticAdjudicationResult",
    "SemanticAdjudicator",
    "SemanticDecision",
    "build_root_cause_judge_request",
    "extract_root_cause_candidate",
]
