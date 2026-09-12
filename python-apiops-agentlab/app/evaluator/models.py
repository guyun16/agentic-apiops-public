"""Strict internal models for deterministic Stage 19 evaluation."""

from __future__ import annotations

import math
from enum import StrEnum
from typing import Annotated, Literal, TypeAlias, get_args

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictFloat,
    StrictInt,
    StrictStr,
    field_validator,
    model_validator,
)

from app.schemas.diagnosis_report import FailureType
from app.schemas.testcase_dsl import JsonValue

NonEmptyString = Annotated[StrictStr, Field(min_length=1)]
NonNegativeFloat = Annotated[StrictFloat, Field(ge=0)]
NonNegativeInt = Annotated[StrictInt, Field(ge=0)]
MetricValue: TypeAlias = StrictInt | StrictFloat


class _EvaluationModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        populate_by_name=False,
        strict=True,
        frozen=True,
        validate_default=True,
    )


class MetricStatus(StrEnum):
    VALUE = "VALUE"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    UNKNOWN = "UNKNOWN"
    ERROR = "ERROR"


class MetricName(StrEnum):
    VALID_JSON = "valid_json"
    SCHEMA_VALID = "schema_valid"
    CONTRACT_ACCEPTED = "contract_accepted"
    EXACT_MATCH = "exact_match"
    TOOL_PRECISION = "tool_precision"
    TOOL_RECALL = "tool_recall"
    TOOL_EXACT_SET_MATCH = "tool_exact_set_match"
    PARAMETER_ACCURACY = "parameter_accuracy"
    EVIDENCE_HIT = "evidence_hit"
    DIAGNOSIS_ACCURACY = "diagnosis_accuracy"
    DIAGNOSIS_CONTRACT = "diagnosis_contract"
    SAFETY_ACCURACY = "safety_accuracy"
    WALL_CLOCK_LATENCY_MS = "wall_clock_latency_ms"
    MODEL_LATENCY_MS = "model_latency_ms"
    TOOL_LATENCY_MS = "tool_latency_ms"
    HUMAN_WAIT_MS = "human_wait_ms"
    ACTIVE_EXECUTION_MS = "active_execution_ms"
    PROMPT_TOKENS = "prompt_tokens"
    COMPLETION_TOKENS = "completion_tokens"
    TOTAL_TOKENS = "total_tokens"
    COST = "cost"


class SafetyOutcome(StrEnum):
    SAFE = "SAFE"
    SAFETY_VIOLATION = "SAFETY_VIOLATION"
    FORBIDDEN_INTENT_DENIED = "FORBIDDEN_INTENT_DENIED"
    APPROVAL_BYPASS_BLOCKED = "APPROVAL_BYPASS_BLOCKED"
    JAVA_DENIED = "JAVA_DENIED"
    HUMAN_REJECTED = "HUMAN_REJECTED"


class ParameterMatchPolicy(StrEnum):
    EXACT = "EXACT"
    SUBSET = "SUBSET"


class ExpectedToolArguments(_EvaluationModel):
    """Expected arguments plus evaluation-only comparison policy.

    Fields absent from ``optional_fields`` are required. The policy does not
    authorize or repair a Tool call; it only describes comparison semantics.
    """

    tool_name: NonEmptyString
    arguments: dict[StrictStr, JsonValue]
    match_policy: ParameterMatchPolicy = ParameterMatchPolicy.EXACT
    optional_fields: tuple[NonEmptyString, ...] = ()
    case_insensitive_fields: tuple[NonEmptyString, ...] = ()
    trim_fields: tuple[NonEmptyString, ...] = ()
    order_insensitive_fields: tuple[NonEmptyString, ...] = ()

    @model_validator(mode="after")
    def comparison_fields_must_exist_and_be_unique(self) -> ExpectedToolArguments:
        policies = (
            self.optional_fields,
            self.case_insensitive_fields,
            self.trim_fields,
            self.order_insensitive_fields,
        )
        for fields in policies:
            if len(fields) != len(set(fields)):
                raise ValueError("comparison policy fields must be unique")
            unknown = set(fields) - set(self.arguments)
            if unknown:
                raise ValueError(f"comparison policy references unknown fields: {sorted(unknown)}")
        return self


class StructuredFact(_EvaluationModel):
    name: NonEmptyString
    value: JsonValue


class DiagnosisContentReview(_EvaluationModel):
    """Evaluation-owned review of one exact candidate and its exact evidence.

    These reference verdicts are never model-visible and never inferred from
    confidence, array length, keywords, or a candidate-authored self assessment.
    """

    candidate_digest: Annotated[StrictStr, Field(pattern=r"^[a-f0-9]{64}$")]
    candidate_scope: Literal["complete", "persisted_fields"] = "complete"
    evidence_digest: Annotated[StrictStr, Field(pattern=r"^[a-f0-9]{64}$")]
    reference: NonEmptyString
    rationale: NonEmptyString
    checks: dict[
        Literal[
            "observed_facts", "hypothesis_grounding", "uncertainty",
            "citation_support", "limitations_and_checks",
        ],
        Literal["PASS", "FAIL", "UNKNOWN"],
    ]

    @model_validator(mode="after")
    def all_dimensions_required(self) -> DiagnosisContentReview:
        if set(self.checks) != {
            "observed_facts", "hypothesis_grounding", "uncertainty",
            "citation_support", "limitations_and_checks",
        }:
            raise ValueError("content review requires every diagnosis contract dimension")
        if self.candidate_scope == "persisted_fields" and set(self.checks.values()) == {"PASS"}:
            raise ValueError("partial output content review cannot establish full-report PASS")
        return self


class GroundTruth(_EvaluationModel):
    """Versioned evaluation input owned outside the evaluated Agent run."""

    ground_truth_id: NonEmptyString
    version: NonEmptyString
    expected_tools: tuple[NonEmptyString, ...] = ()
    expected_tool_arguments: tuple[ExpectedToolArguments, ...] = ()
    expected_evidence_ids: tuple[NonEmptyString, ...] | None = None
    expected_diagnosis: NonEmptyString | None = None
    acceptable_diagnosis_alternatives: tuple[NonEmptyString, ...] = ()
    expected_safety_outcome: SafetyOutcome | None = None
    expected_facts: tuple[StructuredFact, ...] = ()
    diagnosis_contract: Literal["insufficient-evidence-v1"] | None = None
    diagnosis_content_reviews: tuple[DiagnosisContentReview, ...] = ()

    @model_validator(mode="after")
    def expectations_must_be_unambiguous(self) -> GroundTruth:
        if self.diagnosis_content_reviews and self.diagnosis_contract is None:
            raise ValueError("diagnosis content reviews require a versioned contract")
        review_keys = [
            (review.candidate_scope, review.candidate_digest, review.evidence_digest)
            for review in self.diagnosis_content_reviews
        ]
        if len(review_keys) != len(set(review_keys)):
            raise ValueError("conflicting or duplicate diagnosis content reviews")
        if self.diagnosis_contract and any(
            fact.name in {"rootCauseHypotheses", "root_cause_hypotheses"}
            for fact in self.expected_facts
        ):
            raise ValueError(
                "insufficient-evidence contract cannot also require literal hypotheses"
            )
        if len(self.expected_tools) != len(set(self.expected_tools)):
            raise ValueError("expected_tools must be unique")
        argument_tools = [item.tool_name for item in self.expected_tool_arguments]
        if len(argument_tools) != len(set(argument_tools)):
            raise ValueError("expected_tool_arguments must contain at most one entry per tool")
        unknown_tools = set(argument_tools) - set(self.expected_tools)
        if unknown_tools:
            names = ", ".join(sorted(unknown_tools))
            raise ValueError(f"expected arguments reference tools outside expected_tools: {names}")
        if self.expected_evidence_ids is not None:
            if not self.expected_evidence_ids:
                raise ValueError("use None, not an empty tuple, when evidence is not applicable")
            if len(self.expected_evidence_ids) != len(set(self.expected_evidence_ids)):
                raise ValueError("expected_evidence_ids must be unique")
        if self.acceptable_diagnosis_alternatives and self.expected_diagnosis is None:
            raise ValueError("diagnosis alternatives require expected_diagnosis")
        diagnoses = self.acceptable_diagnosis_alternatives
        if len(diagnoses) != len(set(diagnoses)):
            raise ValueError("acceptable diagnosis alternatives must be unique")
        supported_diagnoses = frozenset(get_args(FailureType))
        unreachable_diagnoses = {
            item
            for item in (self.expected_diagnosis, *diagnoses)
            if item is not None and item not in supported_diagnoses
        }
        if unreachable_diagnoses:
            raise ValueError(
                "diagnosis expectations are not expressible by DiagnosisReport.failureType: "
                + ", ".join(sorted(unreachable_diagnoses))
            )
        fact_names = [fact.name for fact in self.expected_facts]
        if len(fact_names) != len(set(fact_names)):
            raise ValueError("expected_facts names must be unique")
        return self


class ValidityFacts(_EvaluationModel):
    """Authority-supplied facts for validity layers absent from Trace."""

    valid_json: StrictBool | None = None
    schema_valid: StrictBool | None = None
    contract_accepted: StrictBool | None = None


class ObservedToolArguments(_EvaluationModel):
    tool_name: NonEmptyString
    arguments: dict[StrictStr, JsonValue]
    tool_intent_id: NonEmptyString | None = None


class EvaluationFacts(_EvaluationModel):
    """Trusted evaluation inputs that are references/facts, not copied Trace."""

    validity: ValidityFacts = Field(default_factory=ValidityFacts)
    tool_arguments: tuple[ObservedToolArguments, ...] = ()
    evidence_ids: tuple[NonEmptyString, ...] | None = None
    diagnosis: NonEmptyString | None = None
    safety_outcome: SafetyOutcome | None = None
    structured_facts: tuple[StructuredFact, ...] = ()

    @model_validator(mode="after")
    def observed_facts_must_be_unique(self) -> EvaluationFacts:
        tool_names = [item.tool_name for item in self.tool_arguments]
        if len(tool_names) != len(set(tool_names)):
            raise ValueError("tool_arguments must contain at most one entry per tool")
        if self.evidence_ids is not None and len(self.evidence_ids) != len(set(self.evidence_ids)):
            raise ValueError("evidence_ids must be unique")
        fact_names = [fact.name for fact in self.structured_facts]
        if len(fact_names) != len(set(fact_names)):
            raise ValueError("structured_facts names must be unique")
        return self


class ModelPricing(_EvaluationModel):
    """Injectable, versioned pricing; no prices are hard-coded by Evaluator."""

    provider: NonEmptyString
    model: NonEmptyString
    model_version: NonEmptyString
    prompt_per_million: NonNegativeFloat
    completion_per_million: NonNegativeFloat
    currency: NonEmptyString = "USD"
    version: NonEmptyString
    source: NonEmptyString


class EvaluationCase(_EvaluationModel):
    """Correlates one AgentRun, Ground Truth, and required external facts."""

    case_id: NonEmptyString
    trace_id: NonEmptyString
    agent_run_id: NonEmptyString
    ground_truth_id: NonEmptyString
    ground_truth_version: NonEmptyString
    facts: EvaluationFacts = Field(default_factory=EvaluationFacts)
    applicable_metrics: tuple[MetricName, ...] | None = None
    pricing: tuple[ModelPricing, ...] = ()

    @model_validator(mode="after")
    def configuration_must_be_unique(self) -> EvaluationCase:
        if self.applicable_metrics is not None and len(self.applicable_metrics) != len(
            set(self.applicable_metrics)
        ):
            raise ValueError("applicable_metrics must be unique")
        pricing_keys = [
            (price.provider, price.model, price.model_version) for price in self.pricing
        ]
        if len(pricing_keys) != len(set(pricing_keys)):
            raise ValueError("pricing must contain at most one entry per provider/model")
        return self


class MetricResult(_EvaluationModel):
    """One metric value whose absence semantics cannot collapse to numeric zero."""

    metric: MetricName
    status: MetricStatus
    value: MetricValue | None = None
    unit: NonEmptyString | None = None
    reason: NonEmptyString | None = None
    details: tuple[NonEmptyString, ...] = ()

    @field_validator("value")
    @classmethod
    def value_must_be_finite(cls, value: int | float | None) -> int | float | None:
        if isinstance(value, float) and not math.isfinite(value):
            raise ValueError("metric value must be finite")
        return value

    @model_validator(mode="after")
    def status_and_value_must_agree(self) -> MetricResult:
        if self.status is MetricStatus.VALUE and self.value is None:
            raise ValueError("VALUE metric requires a numeric value")
        if self.status is not MetricStatus.VALUE and self.value is not None:
            raise ValueError("non-VALUE metric must not carry a numeric value")
        if self.status is not MetricStatus.VALUE and self.unit is not None:
            raise ValueError("non-VALUE metric must not carry a unit")
        if self.status is not MetricStatus.VALUE and self.reason is None:
            raise ValueError("non-VALUE metric requires a reason")
        return self

    @classmethod
    def measured(
        cls,
        metric: MetricName,
        value: int | float,
        *,
        unit: str | None = None,
        reason: str | None = None,
        details: tuple[str, ...] = (),
    ) -> MetricResult:
        return cls(
            metric=metric,
            status=MetricStatus.VALUE,
            value=value,
            unit=unit,
            reason=reason,
            details=details,
        )

    @classmethod
    def unavailable(
        cls,
        metric: MetricName,
        status: MetricStatus,
        reason: str,
    ) -> MetricResult:
        if status is MetricStatus.VALUE:
            raise ValueError("use measured() for VALUE metrics")
        return cls(metric=metric, status=status, reason=reason)


class EvaluationResult(_EvaluationModel):
    evaluation_id: NonEmptyString
    case_id: NonEmptyString
    trace_id: NonEmptyString
    agent_run_id: NonEmptyString
    ground_truth_id: NonEmptyString
    ground_truth_version: NonEmptyString
    evaluator_version: NonEmptyString
    metrics: tuple[MetricResult, ...]

    @model_validator(mode="after")
    def metric_names_must_be_unique(self) -> EvaluationResult:
        names = [result.metric for result in self.metrics]
        if len(names) != len(set(names)):
            raise ValueError("EvaluationResult metric names must be unique")
        return self


class AggregatedMetric(_EvaluationModel):
    metric: MetricName
    total_count: NonNegativeInt
    applicable_count: NonNegativeInt
    value_count: NonNegativeInt
    not_applicable_count: NonNegativeInt
    unknown_count: NonNegativeInt
    error_count: NonNegativeInt
    unit: NonEmptyString | None = None
    mean: StrictFloat | None = None
    rate: StrictFloat | None = None


class AggregatedMetrics(_EvaluationModel):
    evaluator_version: NonEmptyString | None = None
    case_count: NonNegativeInt
    metrics: tuple[AggregatedMetric, ...]


__all__ = [
    "AggregatedMetric",
    "AggregatedMetrics",
    "EvaluationCase",
    "EvaluationFacts",
    "EvaluationResult",
    "ExpectedToolArguments",
    "GroundTruth",
    "MetricName",
    "MetricResult",
    "MetricStatus",
    "ModelPricing",
    "ObservedToolArguments",
    "ParameterMatchPolicy",
    "SafetyOutcome",
    "StructuredFact",
    "ValidityFacts",
]
