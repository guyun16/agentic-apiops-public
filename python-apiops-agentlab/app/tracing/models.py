"""Strict internal trace facts for the Python AgentLab boundary.

These models are intentionally internal.  They describe facts that a future
workflow instrumentation layer may observe; they do not wire themselves into
the existing Stage 15-18 workflows or define a shared cross-language schema.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated, Literal, TypeAlias

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

from app.guardrails.preflight import PreflightDecision
from app.guardrails.violations import EvidenceSource, ViolationCode
from app.schemas.runner import RunStatus
from app.schemas.tool_result import ToolResultStatus
from app.tools.risk import ToolRisk
from app.workflows.approval import ApprovalAction
from app.workflows.tool_planning import EvidenceSufficiency, ToolRequirement

MAX_SAFE_SUMMARY_CHARS = 1024

NonEmptyString = Annotated[StrictStr, Field(min_length=1)]
PositiveInt = Annotated[StrictInt, Field(ge=1)]
NonNegativeInt = Annotated[StrictInt, Field(ge=0)]
NonNegativeFloat = Annotated[StrictFloat, Field(ge=0)]
IdentityValue: TypeAlias = StrictStr | StrictInt


class _TraceModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        populate_by_name=False,
        strict=True,
        frozen=True,
        validate_default=True,
    )


class TraceStatus(StrEnum):
    """Small lifecycle status set; failure detail remains a separate field."""

    RUNNING = "RUNNING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    REJECTED = "REJECTED"
    DENIED = "DENIED"
    INTERRUPTED = "INTERRUPTED"


class TraceEvent(StrEnum):
    """Event shape carried by one typed fact."""

    START = "START"
    TERMINAL = "TERMINAL"
    INTENT = "INTENT"
    DECISION = "DECISION"
    RESULT = "RESULT"
    REQUEST = "REQUEST"
    FACT = "FACT"
    INTERRUPT = "INTERRUPT"
    RESUME = "RESUME"


class IdentityAuthority(StrEnum):
    """Authority labels used on parent and external references."""

    PYTHON = "PYTHON"
    JAVA = "JAVA"
    WORKFLOW = "WORKFLOW"
    RAG = "RAG"
    MEMORY = "MEMORY"
    CORRELATION = "CORRELATION"


class ParentIdentity(_TraceModel):
    """Typed nesting/ownership reference; physical JSONL order is not enough."""

    authority: IdentityAuthority
    kind: NonEmptyString
    identity: NonEmptyString


class ExternalReference(_TraceModel):
    """Reference to a fact owned by another authority; never a generated fallback."""

    authority: IdentityAuthority
    kind: NonEmptyString
    value: NonEmptyString


class FailureDetail(_TraceModel):
    """Failure facts kept separate from the lifecycle status enum."""

    failure_category: NonEmptyString
    failure_code: NonEmptyString | None = None
    message: Annotated[StrictStr, Field(max_length=MAX_SAFE_SUMMARY_CHARS)]
    error_type: NonEmptyString | None = None
    retryable: StrictBool | None = None

    @field_validator("message")
    @classmethod
    def message_must_be_single_line_summary(cls, value: str) -> str:
        if "\x00" in value:
            raise ValueError("failure message must not contain NUL")
        return value


class PayloadDigest(_TraceModel):
    """Bounded summary plus SHA-256; raw payload is deliberately absent."""

    sha256: StrictStr = Field(pattern=r"^[0-9a-f]{64}$")
    summary: Annotated[StrictStr, Field(max_length=MAX_SAFE_SUMMARY_CHARS)]
    truncated: StrictBool = False

    @classmethod
    def from_value(
        cls,
        value: object,
        *,
        max_chars: int = MAX_SAFE_SUMMARY_CHARS,
    ) -> PayloadDigest:
        """Build a redacted digest without adding raw data to this model."""

        from .redaction import digest_payload

        return digest_payload(value, max_chars=max_chars)


class ProviderUsageMetadata(_TraceModel):
    """Known provider usage facts; absent provider fields stay ``None``."""

    provider_request_id: NonEmptyString | None = None
    finish_reason: NonEmptyString | None = None
    cached_prompt_tokens: NonNegativeInt | None = None
    reasoning_tokens: NonNegativeInt | None = None


class TokenUsage(_TraceModel):
    """Provider-reported token counts; missing values are never defaulted to zero."""

    prompt_tokens: NonNegativeInt | None = None
    completion_tokens: NonNegativeInt | None = None
    total_tokens: NonNegativeInt | None = None
    provider_metadata: ProviderUsageMetadata | None = None


class Latency(_TraceModel):
    """Measured timing facts.  Any absent measurement remains absent."""

    started_at: datetime | None = None
    finished_at: datetime | None = None
    duration_ms: NonNegativeFloat | None = None

    @model_validator(mode="after")
    def timing_must_be_ordered(self) -> Latency:
        if self.started_at is not None and self.started_at.tzinfo is None:
            raise ValueError("started_at must be timezone-aware")
        if self.finished_at is not None and self.finished_at.tzinfo is None:
            raise ValueError("finished_at must be timezone-aware")
        if (
            self.started_at is not None
            and self.finished_at is not None
            and self.finished_at < self.started_at
        ):
            raise ValueError("finished_at must not precede started_at")
        return self


class ModelIdentity(_TraceModel):
    """Provider/model identity needed by a future cost calculator."""

    provider: NonEmptyString
    model: NonEmptyString
    deployment: NonEmptyString | None = None
    version: NonEmptyString | None = None


class PromptIdentity(_TraceModel):
    """Versioned prompt/template identity without storing the prompt itself."""

    name: NonEmptyString
    version: NonEmptyString


class TraceLimits(_TraceModel):
    """Default bounded-storage policy for one best-effort recorder."""

    max_summary_chars: PositiveInt = Field(
        default=MAX_SAFE_SUMMARY_CHARS,
        le=MAX_SAFE_SUMMARY_CHARS,
    )
    max_record_bytes: PositiveInt = 16 * 1024
    max_run_bytes: PositiveInt = 1024 * 1024
    max_run_records: PositiveInt = 1000


class TraceRecordBase(_TraceModel):
    """Common identity, ordering, lifecycle, and parent fields."""

    record_type: NonEmptyString
    event: TraceEvent
    trace_id: NonEmptyString
    agent_run_id: NonEmptyString
    agent_step_id: NonEmptyString | None = None
    sequence: PositiveInt | None = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    parent_identity: ParentIdentity | None = None
    workflow_id: NonEmptyString | None = None
    thread_id: NonEmptyString | None = None
    project_id: IdentityValue | None = None
    status: TraceStatus
    failure: FailureDetail | None = None

    @field_validator("timestamp")
    @classmethod
    def timestamp_must_be_timezone_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("timestamp must be timezone-aware")
        return value

    @model_validator(mode="after")
    def lifecycle_failure_consistency(self) -> TraceRecordBase:
        if self.status in {TraceStatus.RUNNING, TraceStatus.SUCCESS} and self.failure is not None:
            raise ValueError("RUNNING and SUCCESS records must not carry failure detail")
        if (
            self.status in {TraceStatus.FAILED, TraceStatus.REJECTED, TraceStatus.DENIED}
            and self.failure is None
        ):
            raise ValueError("failed, rejected, and denied records require failure detail")
        return self


def _validate_lifecycle_event(
    event: TraceEvent,
    status: TraceStatus,
    *,
    allow_resume: bool = True,
) -> None:
    if event is TraceEvent.START and status is not TraceStatus.RUNNING:
        raise ValueError("START records must have RUNNING status")
    if event is TraceEvent.TERMINAL and status in {
        TraceStatus.RUNNING,
        TraceStatus.INTERRUPTED,
    }:
        raise ValueError("TERMINAL records must have a terminal status")
    if event is TraceEvent.INTERRUPT and status is not TraceStatus.INTERRUPTED:
        raise ValueError("INTERRUPT records must have INTERRUPTED status")
    if allow_resume and event is TraceEvent.RESUME and status is not TraceStatus.RUNNING:
        raise ValueError("RESUME records must have RUNNING status")


class AgentRun(TraceRecordBase):
    """One lifecycle event for one complete Python Agent Workflow execution."""

    record_type: Literal["agent_run"] = "agent_run"
    event: Literal[
        TraceEvent.START,
        TraceEvent.TERMINAL,
        TraceEvent.INTERRUPT,
        TraceEvent.RESUME,
    ] = TraceEvent.START
    agent_step_id: None = None

    @model_validator(mode="after")
    def validate_lifecycle(self) -> AgentRun:
        _validate_lifecycle_event(self.event, self.status)
        return self


class AgentStep(TraceRecordBase):
    """One semantically meaningful Python workflow step."""

    record_type: Literal["agent_step"] = "agent_step"
    event: Literal[
        TraceEvent.START,
        TraceEvent.TERMINAL,
        TraceEvent.INTERRUPT,
        TraceEvent.RESUME,
    ] = TraceEvent.START
    agent_step_id: NonEmptyString
    step_type: NonEmptyString

    @model_validator(mode="after")
    def validate_lifecycle(self) -> AgentStep:
        _validate_lifecycle_event(self.event, self.status)
        return self


class ModelCall(TraceRecordBase):
    """One observed Python LLM call; identity is instrumentation-owned."""

    record_type: Literal["model_call"] = "model_call"
    event: Literal[TraceEvent.START, TraceEvent.TERMINAL] = TraceEvent.START
    model_call_id: NonEmptyString
    model_identity: ModelIdentity
    prompt: PromptIdentity
    model_input: PayloadDigest
    model_output: PayloadDigest | None = None
    token_usage: TokenUsage | None = None
    latency: Latency | None = None

    @model_validator(mode="after")
    def validate_lifecycle(self) -> ModelCall:
        _validate_lifecycle_event(self.event, self.status, allow_resume=False)
        return self


class ToolIntentRecord(TraceRecordBase):
    """Trace read-model for the existing Stage 18 ``intent_id``."""

    record_type: Literal["tool_intent"] = "tool_intent"
    event: Literal[TraceEvent.INTENT, TraceEvent.DECISION] = TraceEvent.INTENT
    tool_intent_id: NonEmptyString = Field(
        description="Read-model name for the existing Stage 18 intent_id; not a new ID."
    )
    tool_name: NonEmptyString
    arguments_digest: PayloadDigest
    risk: ToolRisk | None = None
    python_decision: PreflightDecision | None = None

    @property
    def intent_id(self) -> str:
        """Compatibility name exposing the same Stage 18 identity."""

        return self.tool_intent_id


class ToolPlanningRecord(TraceRecordBase):
    """Auditable deterministic requirement decision before ToolIntent routing."""

    record_type: Literal["tool_planning"] = "tool_planning"
    event: Literal[TraceEvent.DECISION] = TraceEvent.DECISION
    requirement: ToolRequirement
    selected_tool: NonEmptyString | None = None
    reason: Annotated[StrictStr, Field(min_length=1, max_length=MAX_SAFE_SUMMARY_CHARS)]
    evidence_sufficiency: EvidenceSufficiency
    authority_source: NonEmptyString
    allowed: StrictBool
    capability_available: StrictBool | None = None

    @model_validator(mode="after")
    def validate_planning_lifecycle(self) -> ToolPlanningRecord:
        if self.requirement in {
            ToolRequirement.REQUIRED,
            ToolRequirement.OPTIONAL,
            ToolRequirement.NOT_REQUIRED,
        }:
            if self.status is not TraceStatus.SUCCESS:
                raise ValueError("routable planning decisions must have SUCCESS status")
        elif self.requirement is ToolRequirement.DENY:
            if self.status is not TraceStatus.DENIED:
                raise ValueError("DENY planning decisions must have DENIED status")
        elif self.status is not TraceStatus.FAILED:
            raise ValueError("UNRESOLVED planning decisions must have FAILED status")
        return self


class ToolResultRecord(TraceRecordBase):
    """Python observation of a Java ToolResult without storing its full payload."""

    record_type: Literal["tool_result"] = "tool_result"
    event: Literal[TraceEvent.RESULT] = TraceEvent.RESULT
    tool_intent_id: NonEmptyString | None = Field(
        default=None,
        description="Existing Stage 18 intent_id; this is not a new Tool identity.",
    )
    tool_name: NonEmptyString
    java_tool_call_id: NonEmptyString | None = Field(
        default=None,
        description="Java Gateway-owned toolCallId; Python never generates this value.",
    )
    tool_result_status: ToolResultStatus | None = Field(
        default=None,
        description="Exact Java ToolResult status; ``status`` remains the trace lifecycle status.",
    )
    java_error_code: NonEmptyString | None = Field(
        default=None,
        description="Bounded Java ToolResult error code, when the authority returned one.",
    )
    has_data: StrictBool | None = Field(
        default=None,
        description="Whether Java ToolResult.data was present; the payload itself is not stored.",
    )
    result_summary: Annotated[StrictStr, Field(max_length=MAX_SAFE_SUMMARY_CHARS)] | None = None
    sanitized: StrictBool
    truncated: StrictBool

    @property
    def tool_call_id(self) -> str | None:
        """Return the Java-owned external reference under the contract name."""

        return self.java_tool_call_id


class EvidenceReference(_TraceModel):
    """Citation identity only; evidence content is not a trace payload."""

    source_type: NonEmptyString
    source_id: NonEmptyString
    project_id: IdentityValue | None = None
    document_id: NonEmptyString | None = None
    chunk_id: NonEmptyString | None = None
    location: NonEmptyString | None = None


class RetrievalReference(_TraceModel):
    """RAG, runner, memory, and citation references owned elsewhere."""

    rag_query_id: NonEmptyString | None = None
    run_id: IdentityValue | None = None
    report_id: NonEmptyString | None = None
    memory_id: NonEmptyString | None = None
    evidence_references: tuple[EvidenceReference, ...] = ()


class RetrievalFact(TraceRecordBase):
    """Observed retrieval fact; it may retain Java ``ragQueryId`` as a reference."""

    record_type: Literal["retrieval"] = "retrieval"
    event: Literal[TraceEvent.FACT] = TraceEvent.FACT
    retrieval_kind: NonEmptyString
    reference: RetrievalReference
    query_digest: PayloadDigest | None = None
    result_count: NonNegativeInt | None = None


class JavaRunReferenceFact(TraceRecordBase):
    """Python observation of Java-owned Runner identities, never report payload."""

    record_type: Literal["java_run_reference"] = "java_run_reference"
    event: Literal[TraceEvent.FACT] = TraceEvent.FACT
    reference_stage: Literal["SUBMIT_ACCEPTED", "TERMINAL_OBSERVED", "REPORT_READ"]
    java_batch_id: NonEmptyString
    java_task_id: PositiveInt
    java_run_id: PositiveInt
    java_status: RunStatus | None = None


class ApprovalFact(TraceRecordBase):
    """Existing Stage 18 approval correlation; deliberately no ``approval_id``."""

    record_type: Literal["approval"] = "approval"
    event: Literal[TraceEvent.REQUEST, TraceEvent.DECISION] = TraceEvent.REQUEST
    workflow_id: NonEmptyString
    intent_id: NonEmptyString
    tool_name: NonEmptyString
    arguments_fingerprint: StrictStr = Field(pattern=r"^[0-9a-f]{64}$")
    decision: ApprovalAction | None = None
    edited_arguments_fingerprint: StrictStr | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )

    @model_validator(mode="after")
    def validate_approval_event(self) -> ApprovalFact:
        if self.event is TraceEvent.REQUEST:
            if self.status is not TraceStatus.INTERRUPTED:
                raise ValueError("approval REQUEST must be INTERRUPTED")
            if self.decision is not None or self.edited_arguments_fingerprint is not None:
                raise ValueError("approval REQUEST must not contain a decision")
        if self.event is TraceEvent.DECISION:
            if self.decision is None:
                raise ValueError("approval DECISION requires a decision")
            if self.decision is ApprovalAction.EDIT and self.edited_arguments_fingerprint is None:
                raise ValueError("approval EDIT requires edited argument fingerprint")
            if self.decision is not ApprovalAction.EDIT and self.edited_arguments_fingerprint:
                raise ValueError("edited argument fingerprint is only valid for EDIT")
            if self.decision is ApprovalAction.REJECT and self.status is not TraceStatus.REJECTED:
                raise ValueError("approval REJECT must have REJECTED status")
            if (
                self.decision in {ApprovalAction.APPROVE, ApprovalAction.EDIT}
                and self.status is not TraceStatus.RUNNING
            ):
                raise ValueError("approval APPROVE or EDIT must return to RUNNING")
        return self


class InterruptFact(TraceRecordBase):
    """A pause fact, normally paired with an approval request."""

    record_type: Literal["interrupt"] = "interrupt"
    event: Literal[TraceEvent.INTERRUPT] = TraceEvent.INTERRUPT
    workflow_id: NonEmptyString
    intent_id: NonEmptyString | None = None
    reason: Annotated[StrictStr, Field(max_length=MAX_SAFE_SUMMARY_CHARS)]


class ResumeFact(TraceRecordBase):
    """Resume fact; it keeps the same AgentRun identity and returns to RUNNING."""

    record_type: Literal["resume"] = "resume"
    event: Literal[TraceEvent.RESUME] = TraceEvent.RESUME
    workflow_id: NonEmptyString
    intent_id: NonEmptyString | None = None
    resumed_from_sequence: PositiveInt | None = None


class SafetyViolationFact(TraceRecordBase):
    """Redaction-safe guardrail fact with no raw evidence or credentials."""

    record_type: Literal["safety_violation"] = "safety_violation"
    event: Literal[TraceEvent.FACT] = TraceEvent.FACT
    code: ViolationCode
    source: EvidenceSource
    tool_name: NonEmptyString
    summary: Annotated[StrictStr, Field(max_length=MAX_SAFE_SUMMARY_CHARS)] | None = None
    evidence_reference: ExternalReference | None = None


TraceRecord: TypeAlias = Annotated[
    AgentRun
    | AgentStep
    | ModelCall
    | ToolIntentRecord
    | ToolPlanningRecord
    | ToolResultRecord
    | RetrievalFact
    | JavaRunReferenceFact
    | ApprovalFact
    | InterruptFact
    | ResumeFact
    | SafetyViolationFact,
    Field(discriminator="record_type"),
]

TRACE_RECORD_TYPES = (
    AgentRun,
    AgentStep,
    ModelCall,
    ToolIntentRecord,
    ToolPlanningRecord,
    ToolResultRecord,
    RetrievalFact,
    JavaRunReferenceFact,
    ApprovalFact,
    InterruptFact,
    ResumeFact,
    SafetyViolationFact,
)

# Read-model aliases keep the vocabulary close to the facts being observed.
ApprovalRecord = ApprovalFact
JavaToolResultRecord = ToolResultRecord
RetrievalRecord = RetrievalFact
SafetyViolationRecord = SafetyViolationFact


__all__ = [
    "AgentRun",
    "AgentStep",
    "ApprovalFact",
    "ApprovalRecord",
    "EvidenceReference",
    "ExternalReference",
    "FailureDetail",
    "IdentityAuthority",
    "InterruptFact",
    "JavaRunReferenceFact",
    "JavaToolResultRecord",
    "Latency",
    "MAX_SAFE_SUMMARY_CHARS",
    "ModelCall",
    "ModelIdentity",
    "ParentIdentity",
    "PayloadDigest",
    "PreflightDecision",
    "PromptIdentity",
    "ProviderUsageMetadata",
    "ResumeFact",
    "RetrievalFact",
    "RetrievalRecord",
    "RetrievalReference",
    "SafetyViolationFact",
    "SafetyViolationRecord",
    "TRACE_RECORD_TYPES",
    "TraceEvent",
    "TraceLimits",
    "TraceRecord",
    "TraceRecordBase",
    "TraceStatus",
    "TokenUsage",
    "ToolIntentRecord",
    "ToolPlanningRecord",
    "ToolResultRecord",
]
