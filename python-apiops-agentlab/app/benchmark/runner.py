"""Small Stage 21.3 orchestration boundary over existing workflows and evaluation."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import time
from collections import Counter
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal, Protocol, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictFloat, StrictInt, StrictStr

from app.evaluator import (
    EvaluationCase,
    EvaluationFacts,
    EvaluationResult,
    GroundTruth,
    Judge,
    JudgeCalibrationResult,
    JudgeConfiguration,
    RuleBasedEvaluator,
    StructuredFact,
)
from app.schemas.testcase_dsl import JsonValue
from app.schemas.tool_result import ToolResultStatus
from app.tracing import (
    JavaRunReferenceFact,
    ModelCall,
    RetrievalFact,
    ToolResultRecord,
    TraceEvent,
    TraceRecord,
    TraceStatus,
    new_identity,
    safe_summary,
)
from app.tracing.redaction import redact_value

from .dataset import BenchmarkDataset, lint_dataset, load_dataset
from .golden import validate_initial_state_references
from .mapping import (
    BenchmarkMappingError,
    project_current_java_report,
    resolve_ground_truth,
    to_evaluation_case,
)
from .models import BenchmarkTask, DatasetSplit, TaskType
from .semantic_adjudication import (
    RootCauseSemanticReference,
    SemanticAdjudicationResult,
    SemanticAdjudicator,
)
from .success import TaskSuccessResult, evaluate_task_success

_IDENTITY_COMPONENT = re.compile(r"^[A-Za-z0-9_.-]+$")
MAX_PLANNED_ARTIFACT_PATH = 220
_PHYSICAL_DIGEST_HEX_LENGTH = 24


class BenchmarkTaskStatus(StrEnum):
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    TIMEOUT = "TIMEOUT"
    ABORTED = "ABORTED"


class BenchmarkExecutionMode(StrEnum):
    """Observed adapter mode; it does not change evaluation semantics."""

    DETERMINISTIC_FIXTURE = "DETERMINISTIC_FIXTURE"
    REAL_MODEL = "REAL_MODEL"
    UNKNOWN = "UNKNOWN"


class JavaExecutionStatus(StrEnum):
    """Benchmark-local status for a task's Java authority requirement."""

    NOT_APPLICABLE = "NOT_APPLICABLE"
    REQUIRED_BUT_UNAVAILABLE = "REQUIRED_BUT_UNAVAILABLE"
    EXECUTED = "EXECUTED"
    EXECUTION_FAILED = "EXECUTION_FAILED"


class BenchmarkLifecycleStatus(StrEnum):
    NOT_STARTED = "NOT_STARTED"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"


class BenchmarkFailureStage(StrEnum):
    SETUP = "SETUP"
    EXECUTION = "EXECUTION"
    EVALUATION = "EVALUATION"
    CLEANUP = "CLEANUP"


class BenchmarkFailureCategory(StrEnum):
    AGENT_FAILURE = "AGENT_FAILURE"
    INFRASTRUCTURE_FAILURE = "INFRASTRUCTURE_FAILURE"
    TIMEOUT = "TIMEOUT"
    SETUP_FAILURE = "SETUP_FAILURE"
    EVALUATION_FAILURE = "EVALUATION_FAILURE"
    CLEANUP_FAILURE = "CLEANUP_FAILURE"
    PROVIDER_FAILURE = "PROVIDER_FAILURE"
    CONTRACT_FAILURE = "CONTRACT_FAILURE"
    HUMAN_REJECTED = "HUMAN_REJECTED"


class BenchmarkTaskFailure(RuntimeError):
    """A workflow adapter failure with an optional partial runtime outcome."""

    def __init__(
        self,
        message: str,
        *,
        category: BenchmarkFailureCategory | str = BenchmarkFailureCategory.AGENT_FAILURE,
        code: str | None = None,
        partial_outcome: BenchmarkExecutionOutcome | None = None,
    ) -> None:
        super().__init__(message)
        self.category = (
            category.value if isinstance(category, BenchmarkFailureCategory) else category
        )
        self.code = code
        self.partial_outcome = partial_outcome


class ArtifactPathPreflightError(RuntimeError):
    """A planned artifact path cannot be safely persisted on this filesystem."""


class BenchmarkInfrastructureError(BenchmarkTaskFailure):
    """An explicitly classified infrastructure failure; never inferred broadly."""

    def __init__(
        self,
        message: str,
        *,
        code: str = "INFRASTRUCTURE_FAILURE",
        retryable: bool = False,
        partial_outcome: BenchmarkExecutionOutcome | None = None,
    ) -> None:
        super().__init__(
            message,
            category=BenchmarkFailureCategory.INFRASTRUCTURE_FAILURE,
            code=code,
            partial_outcome=partial_outcome,
        )
        self.retryable = retryable


class BenchmarkPrerequisiteError(RuntimeError):
    """A dataset or batch prerequisite failure that prevents meaningful execution."""


class BenchmarkDatasetNotReadyError(BenchmarkPrerequisiteError):
    """The formal Dataset Quality Gate did not permit a dataset run."""


@dataclass(frozen=True, slots=True)
class FixtureSetup:
    """Opaque setup handle plus references resolved for one task.

    The handle is passed only to the adapter cleanup path and is never persisted.
    Fixture contents and Ground Truth are intentionally not part of this object.
    """

    fixture_refs: tuple[str, ...] = ()
    handle: object | None = None


@dataclass(frozen=True, slots=True)
class BenchmarkExecutionOutcome:
    """Runtime facts returned by an adapter around an existing workflow boundary."""

    trace_id: str
    agent_run_id: str
    facts: EvaluationFacts = field(default_factory=EvaluationFacts)
    trace_records: tuple[TraceRecord, ...] = ()
    run_id: int | None = None
    report_id: str | None = None
    tool_call_ids: tuple[str, ...] = ()
    rag_query_ids: tuple[str, ...] = ()
    model_call_ids: tuple[str, ...] = ()
    authority_references: tuple[str, ...] = ()
    agent_retry_count: int = 0
    execution_mode: BenchmarkExecutionMode = BenchmarkExecutionMode.UNKNOWN
    java_execution_status: JavaExecutionStatus = JavaExecutionStatus.NOT_APPLICABLE
    tool_result_observations: tuple[ToolResultObservation, ...] = ()
    auth_profile: str | None = None
    principal_id: int | None = None
    principal_label: str | None = None

    def __post_init__(self) -> None:
        if not self.trace_id.strip() or not self.agent_run_id.strip():
            raise ValueError("execution outcome requires trace_id and agent_run_id")
        if self.agent_retry_count < 0:
            raise ValueError("agent_retry_count must not be negative")
        if self.auth_profile is not None and not self.auth_profile.strip():
            raise ValueError("auth_profile must be non-empty when provided")
        if self.principal_id is not None:
            if isinstance(self.principal_id, bool) or not isinstance(self.principal_id, int):
                raise ValueError("principal_id must be an integer when provided")
            if self.principal_id < 1:
                raise ValueError("principal_id must be positive when provided")
        if self.principal_label is not None and not self.principal_label.strip():
            raise ValueError("principal_label must be non-empty when provided")


class BenchmarkFixtureAdapter(Protocol):
    async def setup(self, task: BenchmarkTask) -> FixtureSetup:
        """Prepare only the task's initial state; do not provide Ground Truth."""

    async def cleanup(self, task: BenchmarkTask, setup: FixtureSetup | None) -> None:
        """Reset state even when setup, execution, or evaluation failed."""


class Stage20WorkflowAdapter(Protocol):
    async def execute(
        self,
        task: BenchmarkTask,
        setup: FixtureSetup,
        *,
        trace_id: str,
        agent_run_id: str,
    ) -> BenchmarkExecutionOutcome:
        """Invoke an existing Stage 20 workflow or E2E boundary and translate facts."""


class CallableStage20WorkflowAdapter:
    """Adapter for an existing async Stage 20 callable; it contains no workflow logic."""

    def __init__(self, callback: Callable[..., Any]) -> None:
        if not callable(callback):
            raise TypeError("callback must be callable")
        self._callback = callback

    async def execute(
        self,
        task: BenchmarkTask,
        setup: FixtureSetup,
        *,
        trace_id: str,
        agent_run_id: str,
    ) -> BenchmarkExecutionOutcome:
        outcome = self._callback(
            task,
            setup,
            trace_id=trace_id,
            agent_run_id=agent_run_id,
        )
        if hasattr(outcome, "__await__"):
            outcome = await outcome
        if not isinstance(outcome, BenchmarkExecutionOutcome):
            raise TypeError("Stage 20 adapter callback must return BenchmarkExecutionOutcome")
        return outcome


class StaticFixtureAdapter:
    """Resolve checked-in Python and symbolic Java references without side effects."""

    async def setup(self, task: BenchmarkTask) -> FixtureSetup:
        validate_initial_state_references(task)
        refs = tuple(
            getattr(entry, "ref", f"literal:{entry.key}") for entry in task.initial_state.entries
        )
        return FixtureSetup(fixture_refs=refs)

    async def cleanup(self, task: BenchmarkTask, setup: FixtureSetup | None) -> None:
        return None


class _RunnerModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        populate_by_name=True,
        strict=True,
        frozen=True,
        validate_default=True,
    )

    def model_dump(self, **kwargs: Any) -> dict[str, Any]:
        kwargs.setdefault("by_alias", True)
        return super().model_dump(**kwargs)


class ToolResultObservation(_RunnerModel):
    """Minimal Java ToolResult facts safe to persist in a benchmark artifact."""

    tool_call_id: StrictStr = Field(alias="toolCallId", min_length=1)
    tool_name: StrictStr = Field(alias="toolName", min_length=1)
    status: ToolResultStatus
    error_code: StrictStr | None = Field(default=None, alias="errorCode", min_length=1)
    has_data: StrictBool | None = Field(default=None, alias="hasData")
    rag_query_id: StrictStr | None = Field(default=None, alias="ragQueryId", min_length=1)
    result_count: StrictInt | None = Field(default=None, alias="resultCount", ge=0)
    mapping_status: Literal[
        "NOT_APPLICABLE",
        "SKIPPED_NON_SUCCESS",
        "SUCCESS",
        "VALIDATION_FAILED",
    ] = Field(alias="mappingStatus")
    mapping_error_code: StrictStr | None = Field(
        default=None,
        alias="mappingErrorCode",
        min_length=1,
    )


class FormalEvidenceSnapshot(_RunnerModel):
    """Redacted replay inputs retained from the existing runtime authorities."""

    redacted_candidate: JsonValue | None = Field(default=None, alias="redactedCandidate")
    normalized_evaluation_facts: dict[StrictStr, JsonValue] = Field(
        default_factory=dict,
        alias="normalizedEvaluationFacts",
    )
    diagnosis_outcome: dict[StrictStr, JsonValue] | None = Field(
        default=None,
        alias="diagnosisOutcome",
    )
    terminal_decision_facts: tuple[StructuredFact, ...] = Field(
        default=(),
        alias="terminalDecisionFacts",
    )
    tool_result_mappings: tuple[ToolResultObservation, ...] = Field(
        default=(),
        alias="toolResultMappings",
    )
    trace_evidence: tuple[dict[StrictStr, JsonValue], ...] = Field(
        default=(),
        alias="traceEvidence",
    )


class BenchmarkRunPolicy(_RunnerModel):
    """Bounded task/cleanup and explicitly allow-listed infrastructure retry policy."""

    task_timeout_seconds: StrictFloat = Field(default=60.0, gt=0, alias="taskTimeoutSeconds")
    cleanup_timeout_seconds: StrictFloat = Field(default=10.0, gt=0, alias="cleanupTimeoutSeconds")
    max_infrastructure_attempts: StrictInt = Field(
        default=1,
        ge=1,
        le=10,
        alias="maxInfrastructureAttempts",
    )
    retryable_infrastructure_codes: tuple[StrictStr, ...] = Field(
        default=(
            "TRANSIENT_CONNECTION_RESET",
            "SERVICE_UNAVAILABLE",
            "TRANSPORT_TRANSIENT",
        ),
        alias="retryableInfrastructureCodes",
    )
    abort_on_cleanup_failure: StrictBool = Field(default=False, alias="abortOnCleanupFailure")


class BenchmarkTaskResult(_RunnerModel):
    """Per-task envelope; deterministic metrics and semantic adjudication stay separate."""

    evaluation_run_id: str = Field(alias="evaluationRunId", min_length=1)
    benchmark_task_id: str = Field(alias="benchmarkTaskId", min_length=1)
    task_type: TaskType = Field(alias="taskType")
    status: BenchmarkTaskStatus
    failure_stage: BenchmarkFailureStage | None = Field(default=None, alias="failureStage")
    failure_category: str | None = Field(default=None, alias="failureCategory")
    failure_code: str | None = Field(default=None, alias="failureCode")
    infrastructure_attempts: StrictInt = Field(default=0, ge=0, alias="infrastructureAttempts")
    agent_retry_count: StrictInt = Field(default=0, ge=0, alias="agentRetryCount")
    execution_mode: BenchmarkExecutionMode = Field(
        default=BenchmarkExecutionMode.UNKNOWN,
        alias="executionMode",
    )
    java_execution_status: JavaExecutionStatus = Field(
        default=JavaExecutionStatus.NOT_APPLICABLE,
        alias="javaExecutionStatus",
    )
    auth_profile: StrictStr | None = Field(default=None, alias="authProfile")
    principal_id: StrictInt | None = Field(default=None, alias="principalId", ge=1)
    principal_label: StrictStr | None = Field(default=None, alias="principalLabel")
    agent_run_id: str = Field(alias="agentRunId", min_length=1)
    trace_id: str = Field(alias="traceId", min_length=1)
    run_id: StrictInt | None = Field(default=None, alias="runId")
    report_id: str | None = Field(default=None, alias="reportId")
    tool_call_ids: tuple[str, ...] = Field(default=(), alias="toolCallIds")
    rag_query_ids: tuple[str, ...] = Field(default=(), alias="ragQueryIds")
    tool_result_observations: tuple[ToolResultObservation, ...] = Field(
        default=(),
        alias="toolResultObservations",
    )
    model_call_ids: tuple[str, ...] = Field(default=(), alias="modelCallIds")
    model_call_count: StrictInt = Field(default=0, ge=0, alias="modelCallCount")
    model_latency_ms: StrictFloat | None = Field(default=None, ge=0, alias="modelLatencyMs")
    prompt_tokens: StrictInt | None = Field(default=None, ge=0, alias="promptTokens")
    completion_tokens: StrictInt | None = Field(default=None, ge=0, alias="completionTokens")
    total_tokens: StrictInt | None = Field(default=None, ge=0, alias="totalTokens")
    authority_references: tuple[str, ...] = Field(default=(), alias="authorityReferences")
    formal_evidence: FormalEvidenceSnapshot | None = Field(default=None, alias="formalEvidence")
    case_id: str = Field(alias="caseId", min_length=1)
    evaluation_id: str | None = Field(default=None, alias="evaluationId")
    evaluation_result: EvaluationResult | None = Field(default=None, alias="evaluationResult")
    task_success: TaskSuccessResult | None = Field(default=None, alias="taskSuccess")
    semantic_adjudication: SemanticAdjudicationResult | None = Field(
        default=None,
        alias="semanticAdjudication",
    )
    fixture_refs: tuple[str, ...] = Field(default=(), alias="fixtureRefs")
    setup_status: BenchmarkLifecycleStatus = Field(alias="setupStatus")
    cleanup_status: BenchmarkLifecycleStatus = Field(alias="cleanupStatus")
    duration_ms: StrictFloat = Field(ge=0, alias="durationMs")
    error_summary: str | None = Field(default=None, alias="errorSummary")
    cleanup_error_summary: str | None = Field(default=None, alias="cleanupErrorSummary")


def project_tool_result_observations(
    records: Sequence[TraceRecord],
    *,
    mapping_status: str | None = None,
    mapping_error_code: str | None = None,
) -> tuple[ToolResultObservation, ...]:
    """Project Java ToolResult authority facts without retaining its payload."""

    retrievals = tuple(
        record
        for record in records
        if isinstance(record, RetrievalFact) and record.retrieval_kind == "JAVA_RAG_TOOL_RESULT"
    )
    observations: list[ToolResultObservation] = []
    for record in records:
        if not isinstance(record, ToolResultRecord) or not record.java_tool_call_id:
            continue
        status: ToolResultStatus
        if record.tool_result_status is not None:
            status = record.tool_result_status
        elif record.status is TraceStatus.SUCCESS:
            status = "SUCCESS"
        elif record.status is TraceStatus.DENIED:
            status = "FORBIDDEN"
        else:
            status = "FAILED"
        error_code = record.java_error_code or (
            record.failure.failure_code if record.failure is not None else None
        )
        if record.tool_name != "rag.search":
            observations.append(
                ToolResultObservation(
                    tool_call_id=record.java_tool_call_id,
                    tool_name=record.tool_name,
                    status=status,
                    error_code=error_code,
                    has_data=record.has_data,
                    mapping_status="NOT_APPLICABLE",
                )
            )
            continue
        if status != "SUCCESS":
            observations.append(
                ToolResultObservation(
                    tool_call_id=record.java_tool_call_id,
                    tool_name=record.tool_name,
                    status=status,
                    error_code=error_code,
                    has_data=record.has_data,
                    mapping_status="SKIPPED_NON_SUCCESS",
                )
            )
            continue

        retrieval = next(
            (
                item
                for item in retrievals
                if item.trace_id == record.trace_id
                and item.agent_run_id == record.agent_run_id
                and (record.agent_step_id is None or item.agent_step_id == record.agent_step_id)
                and item.reference.rag_query_id
            ),
            None,
        )
        if retrieval is not None:
            observations.append(
                ToolResultObservation(
                    tool_call_id=record.java_tool_call_id,
                    tool_name=record.tool_name,
                    status=status,
                    error_code=error_code,
                    has_data=record.has_data,
                    rag_query_id=retrieval.reference.rag_query_id,
                    result_count=retrieval.result_count,
                    mapping_status="SUCCESS",
                )
            )
            continue
        observations.append(
            ToolResultObservation(
                tool_call_id=record.java_tool_call_id,
                tool_name=record.tool_name,
                status=status,
                error_code=error_code,
                has_data=record.has_data,
                mapping_status="VALIDATION_FAILED",
                mapping_error_code=(
                    mapping_error_code
                    if mapping_status == "VALIDATION_FAILED" and mapping_error_code
                    else "RAG_RESULT_NOT_MAPPED"
                ),
            )
        )
    return tuple(observations)


_TERMINAL_FACT_NAMES = frozenset(
    {
        "safety_outcome",
        "safety_terminal_decision",
        "safety_decision_authority",
        "agent_tool_decision",
        "java_defense_decision",
        "approval_decision",
        "approval_required",
        "human_decision",
        "agent_should_call",
        "prompt_injection_detected",
        "unknown_tool",
        "no_call_reason",
        "required_tool_miss",
        "required_tool_name",
        "required_java_deny_observed",
    }
)


def project_formal_evidence_snapshot(
    outcome: BenchmarkExecutionOutcome | None,
) -> FormalEvidenceSnapshot | None:
    """Project redacted candidate, normalized facts, and trace authority for replay."""

    if outcome is None:
        return None
    safe_facts = redact_value(outcome.facts.model_dump(mode="json"))
    if not isinstance(safe_facts, dict):  # pragma: no cover - model_dump is an object
        raise TypeError("normalized evaluation facts must serialize as an object")
    structured = {item.name: item.value for item in outcome.facts.structured_facts}
    candidate = redact_value(structured.get("candidate"))
    diagnosis_outcome: dict[str, JsonValue] | None = None
    if outcome.facts.diagnosis is not None or "diagnosis_outcome" in structured:
        diagnosis_outcome = {
            "failureType": outcome.facts.diagnosis,
            "outcome": structured.get("diagnosis_outcome"),
            "sufficientEvidence": structured.get("sufficient_evidence"),
            "rootCauseHypotheses": redact_value(
                structured.get("root_cause_hypotheses", [])
            ),
            "evidenceIds": list(outcome.facts.evidence_ids or ()),
        }
    terminal_facts = tuple(
        StructuredFact(name=item.name, value=redact_value(item.value))
        for item in outcome.facts.structured_facts
        if item.name in _TERMINAL_FACT_NAMES
    )
    trace_evidence: list[dict[str, JsonValue]] = []
    for record in outcome.trace_records:
        value = redact_value(record.model_dump(mode="json"))
        if isinstance(value, dict):
            trace_evidence.append(value)
    return FormalEvidenceSnapshot(
        redactedCandidate=candidate,
        normalizedEvaluationFacts=safe_facts,
        diagnosisOutcome=diagnosis_outcome,
        terminalDecisionFacts=terminal_facts,
        toolResultMappings=outcome.tool_result_observations,
        traceEvidence=tuple(trace_evidence),
    )


class BenchmarkRun(_RunnerModel):
    """Batch envelope using evaluationRunId as the future batch scope identity."""

    evaluation_run_id: str = Field(alias="evaluationRunId", min_length=1)
    dataset_id: str = Field(alias="datasetId", min_length=1)
    dataset_version: str = Field(alias="datasetVersion", min_length=1)
    task_schema_version: str = Field(alias="taskSchemaVersion", min_length=1)
    split: DatasetSplit | None = None
    selected_task_ids: tuple[str, ...] = Field(alias="selectedTaskIds", min_length=1)
    results: tuple[BenchmarkTaskResult, ...] = Field(min_length=1)
    started_at: datetime = Field(alias="startedAt")
    completed_at: datetime = Field(alias="completedAt")
    policy: BenchmarkRunPolicy
    aborted: StrictBool = False
    abort_reason: str | None = Field(default=None, alias="abortReason")


@dataclass(frozen=True, slots=True)
class BenchmarkProgress:
    evaluation_run_id: str
    current: int
    total: int
    benchmark_task_id: str
    status: BenchmarkTaskStatus


class BenchmarkResultStore(Protocol):
    def persist_task(self, result: BenchmarkTaskResult) -> Path:
        """Persist one result, including failures."""

    def persist_run(self, run: BenchmarkRun) -> Path:
        """Persist the outer run envelope without aggregating metrics."""


class JsonBenchmarkResultStore:
    """Small filesystem store for sanitized per-task JSON artifacts."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def persist_task(self, result: BenchmarkTaskResult) -> Path:
        path = self.task_path(result.evaluation_run_id, result.benchmark_task_id)
        self._write(path, result.model_dump(mode="json"))
        return path

    def persist_run(self, run: BenchmarkRun) -> Path:
        path = self.root / physical_run_directory_name(run.evaluation_run_id) / "run.json"
        self._write(path, run.model_dump(mode="json"))
        return path

    def task_path(self, evaluation_run_id: str, benchmark_task_id: str) -> Path:
        return (
            self.root
            / physical_run_directory_name(evaluation_run_id)
            / physical_task_result_filename(evaluation_run_id, benchmark_task_id)
        )

    @staticmethod
    def _write(path: Path, value: object) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )


EvaluationCallable: TypeAlias = Callable[
    [EvaluationCase, GroundTruth, Sequence[TraceRecord]],
    EvaluationResult,
]
ProgressCallback: TypeAlias = Callable[[BenchmarkProgress], None]


@dataclass(frozen=True, slots=True)
class _Failure:
    stage: BenchmarkFailureStage
    category: str
    code: str | None
    message: str


def _safe_component(value: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError("result-store identity contains an unsafe path component")
    safe = value.replace(":", "_")
    if safe in {".", ".."} or not _IDENTITY_COMPONENT.fullmatch(safe):
        raise ValueError("result-store identity contains an unsafe path component")
    return safe


def _physical_digest(*values: str) -> str:
    digest = hashlib.sha256()
    for value in values:
        _safe_component(value)
        digest.update(value.encode("utf-8"))
        digest.update(b"\0")
    return digest.hexdigest()[:_PHYSICAL_DIGEST_HEX_LENGTH]


def physical_run_directory_name(evaluation_run_id: str) -> str:
    """Return a short stable directory name for a full run identity."""

    return f"run-{_physical_digest(evaluation_run_id)}"


def physical_task_result_filename(evaluation_run_id: str, benchmark_task_id: str) -> str:
    """Return a short stable filename while keeping identity in the JSON envelope."""

    return f"task-{_physical_digest(evaluation_run_id, benchmark_task_id)}.json"


def preflight_artifact_paths(
    paths: Iterable[tuple[str, Path]],
    *,
    path_budget: int = MAX_PLANNED_ARTIFACT_PATH,
) -> dict[str, object]:
    """Validate the complete planned artifact set before execution side effects."""

    if path_budget <= 0:
        raise ValueError("path_budget must be positive")
    planned = tuple((label, Path(path).resolve()) for label, path in paths)
    if not planned:
        raise ArtifactPathPreflightError("artifact path preflight requires at least one path")

    entries = tuple(
        {
            "label": label,
            "path": str(path),
            "length": len(str(path)),
        }
        for label, path in planned
    )
    duplicate_paths = sorted(
        path
        for path, count in Counter(str(path) for _, path in planned).items()
        if count > 1
    )
    if duplicate_paths:
        raise ArtifactPathPreflightError(
            "artifact path preflight found duplicate physical paths: "
            + ", ".join(duplicate_paths)
        )

    over_budget = tuple(entry for entry in entries if entry["length"] > path_budget)
    if over_budget:
        longest = max(over_budget, key=lambda entry: entry["length"])
        raise ArtifactPathPreflightError(
            "artifact path preflight failed: "
            f"{len(over_budget)} path(s) exceed budget {path_budget}; "
            f"longest={longest['length']} path={longest['path']}"
        )

    for _, path in planned:
        parent = path.parent
        while not parent.exists() and parent != parent.parent:
            parent = parent.parent
        if not parent.is_dir() or not os.access(parent, os.W_OK):
            raise ArtifactPathPreflightError(
                f"artifact path preflight found an unwritable parent: {parent}"
            )

    longest = max(entries, key=lambda entry: entry["length"])
    return {
        "pathBudget": path_budget,
        "pathCount": len(entries),
        "paths": list(entries),
        "maxPathLength": longest["length"],
        "maxPath": longest["path"],
        "overBudgetCount": 0,
    }


def _error_summary(error: BaseException) -> str:
    summary, _ = safe_summary(str(error) or type(error).__name__)
    summary = summary.replace("\r", " ").replace("\n", " ")
    return f"{type(error).__name__}: {summary}"[:1024]


def _fixture_refs(task: BenchmarkTask) -> tuple[str, ...]:
    return tuple(
        getattr(entry, "ref", f"literal:{entry.key}") for entry in task.initial_state.entries
    )


def _runtime_references(
    outcome: BenchmarkExecutionOutcome | None,
) -> tuple[int | None, str | None, tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    if outcome is None:
        return None, None, (), (), ()
    run_id = outcome.run_id
    report_id = outcome.report_id
    tool_call_ids = list(outcome.tool_call_ids)
    rag_query_ids = list(outcome.rag_query_ids)
    authority_refs = list(outcome.authority_references)
    for record in outcome.trace_records:
        if isinstance(record, JavaRunReferenceFact):
            run_id = record.java_run_id
        elif isinstance(record, ToolResultRecord) and record.java_tool_call_id:
            if record.java_tool_call_id not in tool_call_ids:
                tool_call_ids.append(record.java_tool_call_id)
        elif isinstance(record, RetrievalFact):
            reference = record.reference
            if reference.rag_query_id and reference.rag_query_id not in rag_query_ids:
                rag_query_ids.append(reference.rag_query_id)
            # A controlled initial TestReport is recorded by the diagnosis
            # workflow as a retrieval fact, but its ``fixture:`` identity is
            # not Java authority.  Only promote non-fixture references.
            if (
                reference.report_id
                and not reference.report_id.startswith("fixture:")
                and report_id is None
            ):
                report_id = reference.report_id
                if (
                    reference.run_id is not None
                    and run_id is None
                    and isinstance(reference.run_id, int)
                ):
                    run_id = reference.run_id
    return run_id, report_id, tuple(tool_call_ids), tuple(rag_query_ids), tuple(authority_refs)


def _model_runtime_facts(
    records: Sequence[TraceRecord],
) -> tuple[int, float | None, int | None, int | None, int | None]:
    """Project existing terminal ModelCall facts without inventing usage."""

    calls_by_id: dict[str, ModelCall] = {}
    terminal_calls: dict[str, ModelCall] = {}
    for record in records:
        if not isinstance(record, ModelCall):
            continue
        calls_by_id.setdefault(record.model_call_id, record)
        if record.event is TraceEvent.TERMINAL:
            terminal_calls[record.model_call_id] = record

    if not calls_by_id:
        return 0, None, None, None, None
    if not terminal_calls:
        return len(calls_by_id), None, None, None, None

    durations = [
        call.latency.duration_ms
        for call in terminal_calls.values()
        if call.latency is not None and call.latency.duration_ms is not None
    ]
    model_latency_ms = sum(durations) if len(durations) == len(terminal_calls) else None

    prompt_values = [
        call.token_usage.prompt_tokens
        for call in terminal_calls.values()
        if call.token_usage is not None and call.token_usage.prompt_tokens is not None
    ]
    completion_values = [
        call.token_usage.completion_tokens
        for call in terminal_calls.values()
        if call.token_usage is not None and call.token_usage.completion_tokens is not None
    ]
    total_values = [
        call.token_usage.total_tokens
        for call in terminal_calls.values()
        if call.token_usage is not None and call.token_usage.total_tokens is not None
    ]
    return (
        len(calls_by_id),
        model_latency_ms,
        sum(prompt_values) if len(prompt_values) == len(terminal_calls) else None,
        sum(completion_values) if len(completion_values) == len(terminal_calls) else None,
        sum(total_values) if len(total_values) == len(terminal_calls) else None,
    )


def select_dataset_tasks(
    dataset: BenchmarkDataset,
    *,
    split: DatasetSplit | str | None = None,
    category: TaskType | str | None = None,
    task_ids: Iterable[str] = (),
    golden_only: bool = False,
) -> tuple[tuple[BenchmarkTask, GroundTruth], ...]:
    """Select manifest-ordered tasks without changing the Dataset or its split."""

    effective_split = DatasetSplit(split) if isinstance(split, str) else split
    effective_category = TaskType(category) if isinstance(category, str) else category
    requested_ids = set(task_ids)
    tasks_by_id = {task.benchmark_task_id: task for task in dataset.tasks}
    truths_by_key = {
        (truth.ground_truth_id, truth.version): truth for truth in dataset.ground_truths
    }
    selected: list[tuple[BenchmarkTask, GroundTruth]] = []
    for entry in dataset.manifest.tasks:
        task = tasks_by_id.get(entry.benchmark_task_id)
        if task is None:
            raise BenchmarkPrerequisiteError(
                f"manifest task is missing from loaded dataset: {entry.benchmark_task_id}"
            )
        if effective_split is not None and entry.split is not effective_split:
            continue
        if effective_category is not None and task.task_type is not effective_category:
            continue
        if requested_ids and task.benchmark_task_id not in requested_ids:
            continue
        if golden_only and not task.benchmark_task_id.startswith("bench_task_golden_"):
            continue
        truth_key = (entry.ground_truth_ref.ground_truth_id, entry.ground_truth_ref.version)
        truth = truths_by_key.get(truth_key)
        if truth is None:
            raise BenchmarkPrerequisiteError(
                f"selected task GroundTruth is not resolvable: {task.benchmark_task_id}"
            )
        selected.append((task, truth))
    if requested_ids:
        selected_ids = {task.benchmark_task_id for task, _ in selected}
        missing = requested_ids - selected_ids
        if missing:
            raise BenchmarkPrerequisiteError(
                f"requested task IDs were not selected: {sorted(missing)}"
            )
    if not selected:
        raise BenchmarkPrerequisiteError("task selection is empty")
    return tuple(selected)


class BenchmarkRunner:
    """Load/execute/evaluate/persist/cleanup orchestration, not an Agent runtime."""

    def __init__(
        self,
        workflow_adapter: Stage20WorkflowAdapter,
        *,
        fixture_adapter: BenchmarkFixtureAdapter | None = None,
        evaluator: EvaluationCallable | None = None,
        judge: Judge | None = None,
        judge_configuration: JudgeConfiguration | None = None,
        judge_calibration: JudgeCalibrationResult | None = None,
        semantic_references: Mapping[str, RootCauseSemanticReference] | None = None,
        result_store: BenchmarkResultStore | None = None,
        policy: BenchmarkRunPolicy | None = None,
        identity_factory: Callable[[str], str] = new_identity,
    ) -> None:
        if not hasattr(workflow_adapter, "execute"):
            raise TypeError("workflow_adapter must expose async execute")
        if not callable(identity_factory):
            raise TypeError("identity_factory must be callable")
        self._workflow_adapter = workflow_adapter
        self._fixture_adapter = fixture_adapter or StaticFixtureAdapter()
        self._evaluator = evaluator or RuleBasedEvaluator().evaluate
        self._semantic_adjudicator = SemanticAdjudicator(
            judge,
            configuration=judge_configuration,
            calibration=judge_calibration,
        )
        self._semantic_references = dict(semantic_references or {})
        self._semantic_enabled = any(
            value is not None
            for value in (judge, judge_configuration, judge_calibration)
        ) or bool(self._semantic_references)
        self._result_store = result_store
        self._policy = policy or BenchmarkRunPolicy()
        self._identity_factory = identity_factory

    async def run_task(
        self,
        task: BenchmarkTask,
        ground_truth: GroundTruth,
        *,
        evaluation_run_id: str | None = None,
        result_store: BenchmarkResultStore | None = None,
    ) -> BenchmarkTaskResult:
        """Run one resolved task and always return/persist a task-level result."""

        resolve_ground_truth(task, (ground_truth,))
        effective_evaluation_run_id = evaluation_run_id or self._identity_factory("evaluation_run")
        _safe_component(effective_evaluation_run_id)
        fallback_trace_id = self._identity_factory("trace")
        fallback_agent_run_id = self._identity_factory("agent_run")
        case_id = f"case:{effective_evaluation_run_id}:{task.benchmark_task_id}"
        started = time.perf_counter()
        setup: FixtureSetup | None = None
        outcome: BenchmarkExecutionOutcome | None = None
        evaluation_result: EvaluationResult | None = None
        task_success: TaskSuccessResult | None = None
        semantic_adjudication: SemanticAdjudicationResult | None = None
        current_stage = BenchmarkFailureStage.SETUP
        setup_status = BenchmarkLifecycleStatus.NOT_STARTED
        cleanup_status = BenchmarkLifecycleStatus.NOT_STARTED
        primary_failure: _Failure | None = None
        cleanup_failure: _Failure | None = None
        infrastructure_attempts = 0

        try:
            async with asyncio.timeout(self._policy.task_timeout_seconds):
                setup = await self._fixture_adapter.setup(task)
                setup_status = BenchmarkLifecycleStatus.SUCCESS
                current_stage = BenchmarkFailureStage.EXECUTION
                outcome, infrastructure_attempts = await self._execute_with_retry(
                    task,
                    setup,
                    trace_id=fallback_trace_id,
                    agent_run_id=fallback_agent_run_id,
                )
                current_stage = BenchmarkFailureStage.EVALUATION
                run_id, report_id, tool_call_ids, rag_query_ids, authority_refs = (
                    _runtime_references(outcome)
                )
                evaluation_ground_truth = project_current_java_report(
                    ground_truth,
                    report_id=report_id,
                )
                case = to_evaluation_case(
                    task,
                    evaluation_ground_truth,
                    case_id=case_id,
                    trace_id=outcome.trace_id,
                    agent_run_id=outcome.agent_run_id,
                    facts=outcome.facts,
                )
                evaluation_result = self._evaluator(
                    case,
                    evaluation_ground_truth,
                    outcome.trace_records,
                )
                if not isinstance(evaluation_result, EvaluationResult):
                    raise TypeError("Stage 19 evaluator did not return EvaluationResult")
                task_success = evaluate_task_success(
                    task,
                    evaluation_ground_truth,
                    evaluation_result,
                )
                if self._semantic_enabled:
                    semantic_adjudication = await self._semantic_adjudicator.adjudicate(
                        task_id=task.benchmark_task_id,
                        task_type=task.task_type,
                        case=case,
                        evaluation_result=evaluation_result,
                        deterministic_status=task_success.status,
                        deterministic_conditions=task_success.conditions,
                        reference=self._semantic_references.get(task.benchmark_task_id),
                    )
        except TimeoutError as exc:
            if current_stage is BenchmarkFailureStage.SETUP:
                setup_status = BenchmarkLifecycleStatus.FAILED
            primary_failure = _Failure(
                current_stage,
                BenchmarkFailureCategory.TIMEOUT.value,
                "BENCHMARK_TASK_TIMEOUT",
                _error_summary(exc),
            )
        except BenchmarkTaskFailure as exc:
            if current_stage is BenchmarkFailureStage.SETUP:
                setup_status = BenchmarkLifecycleStatus.FAILED
            outcome = exc.partial_outcome or outcome
            primary_failure = _Failure(current_stage, exc.category, exc.code, _error_summary(exc))
            infrastructure_attempts = max(
                infrastructure_attempts,
                int(getattr(exc, "_benchmark_attempts", 1)),
            )
        except BenchmarkMappingError as exc:
            if current_stage is BenchmarkFailureStage.SETUP:
                setup_status = BenchmarkLifecycleStatus.FAILED
            primary_failure = _Failure(
                BenchmarkFailureStage.EVALUATION,
                BenchmarkFailureCategory.EVALUATION_FAILURE.value,
                "EVALUATION_MAPPING_FAILED",
                _error_summary(exc),
            )
        except Exception as exc:  # noqa: BLE001 - task failures become persisted facts
            if current_stage is BenchmarkFailureStage.SETUP:
                setup_status = BenchmarkLifecycleStatus.FAILED
            default_category = {
                BenchmarkFailureStage.SETUP: BenchmarkFailureCategory.SETUP_FAILURE,
                BenchmarkFailureStage.EXECUTION: BenchmarkFailureCategory.AGENT_FAILURE,
                BenchmarkFailureStage.EVALUATION: BenchmarkFailureCategory.EVALUATION_FAILURE,
                BenchmarkFailureStage.CLEANUP: BenchmarkFailureCategory.CLEANUP_FAILURE,
            }[current_stage]
            primary_failure = _Failure(
                current_stage,
                default_category.value,
                None,
                _error_summary(exc),
            )
            infrastructure_attempts = max(
                infrastructure_attempts,
                int(getattr(exc, "_benchmark_attempts", 1)),
            )
        finally:
            current_stage = BenchmarkFailureStage.CLEANUP
            try:
                await asyncio.wait_for(
                    self._fixture_adapter.cleanup(task, setup),
                    timeout=self._policy.cleanup_timeout_seconds,
                )
                cleanup_status = BenchmarkLifecycleStatus.SUCCESS
            except Exception as exc:  # noqa: BLE001 - cleanup failure must be visible
                cleanup_status = BenchmarkLifecycleStatus.FAILED
                cleanup_failure = _Failure(
                    BenchmarkFailureStage.CLEANUP,
                    BenchmarkFailureCategory.CLEANUP_FAILURE.value,
                    "CLEANUP_FAILED",
                    _error_summary(exc),
                )

        if cleanup_failure is not None and primary_failure is None:
            primary_failure = cleanup_failure
        run_id, report_id, tool_call_ids, rag_query_ids, authority_refs = _runtime_references(
            outcome
        )
        tool_result_observations = project_tool_result_observations(
            outcome.trace_records if outcome is not None else (),
        )
        if outcome is not None and outcome.tool_result_observations:
            tool_result_observations = outcome.tool_result_observations
        model_call_ids_list: list[str] = []
        for record in outcome.trace_records if outcome is not None else ():
            if isinstance(record, ModelCall) and record.model_call_id not in model_call_ids_list:
                model_call_ids_list.append(record.model_call_id)
        model_call_ids = tuple(model_call_ids_list)
        (
            model_call_count,
            model_latency_ms,
            prompt_tokens,
            completion_tokens,
            total_tokens,
        ) = _model_runtime_facts(outcome.trace_records if outcome is not None else ())
        effective_trace_id = outcome.trace_id if outcome is not None else fallback_trace_id
        effective_agent_run_id = (
            outcome.agent_run_id if outcome is not None else fallback_agent_run_id
        )
        status = (
            BenchmarkTaskStatus.SUCCESS
            if primary_failure is None and evaluation_result is not None
            else BenchmarkTaskStatus.TIMEOUT
            if primary_failure is not None
            and primary_failure.category == BenchmarkFailureCategory.TIMEOUT.value
            else BenchmarkTaskStatus.FAILED
        )
        result = BenchmarkTaskResult(
            evaluation_run_id=effective_evaluation_run_id,
            benchmark_task_id=task.benchmark_task_id,
            task_type=task.task_type,
            status=status,
            failure_stage=primary_failure.stage if primary_failure else None,
            failure_category=primary_failure.category if primary_failure else None,
            failure_code=primary_failure.code if primary_failure else None,
            infrastructure_attempts=infrastructure_attempts,
            agent_retry_count=outcome.agent_retry_count if outcome else 0,
            execution_mode=(
                outcome.execution_mode if outcome is not None else BenchmarkExecutionMode.UNKNOWN
            ),
            java_execution_status=(
                outcome.java_execution_status
                if outcome is not None
                else JavaExecutionStatus.NOT_APPLICABLE
            ),
            auth_profile=outcome.auth_profile if outcome is not None else None,
            principal_id=outcome.principal_id if outcome is not None else None,
            principal_label=outcome.principal_label if outcome is not None else None,
            agent_run_id=effective_agent_run_id,
            trace_id=effective_trace_id,
            run_id=run_id,
            report_id=report_id,
            tool_call_ids=tool_call_ids,
            rag_query_ids=rag_query_ids,
            tool_result_observations=tool_result_observations,
            model_call_ids=model_call_ids,
            model_call_count=model_call_count,
            model_latency_ms=model_latency_ms,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            authority_references=authority_refs,
            formal_evidence=project_formal_evidence_snapshot(outcome),
            case_id=case_id,
            evaluation_id=evaluation_result.evaluation_id if evaluation_result else None,
            evaluation_result=evaluation_result,
            task_success=task_success
            or TaskSuccessResult.unknown(
                "task success could not be evaluated because execution or evaluation "
                "did not complete"
            ),
            semantic_adjudication=semantic_adjudication,
            fixture_refs=setup.fixture_refs if setup else _fixture_refs(task),
            setup_status=setup_status,
            cleanup_status=cleanup_status,
            duration_ms=float(round((time.perf_counter() - started) * 1000, 3)),
            error_summary=primary_failure.message if primary_failure else None,
            cleanup_error_summary=cleanup_failure.message if cleanup_failure else None,
        )
        store = result_store or self._result_store
        if store is not None:
            store.persist_task(result)
        return result

    async def run_batch(
        self,
        tasks_or_dataset: BenchmarkDataset | Sequence[BenchmarkTask],
        ground_truths: Iterable[GroundTruth] | None = None,
        *,
        evaluation_run_id: str | None = None,
        split: DatasetSplit | str | None = None,
        category: TaskType | str | None = None,
        task_ids: Iterable[str] = (),
        golden_only: bool = False,
        dataset_id: str | None = None,
        dataset_version: str | None = None,
        task_schema_version: str | None = None,
        on_progress: ProgressCallback | None = None,
        result_store: BenchmarkResultStore | None = None,
    ) -> BenchmarkRun:
        """Execute a stable task collection; ordinary task failures continue."""

        if isinstance(tasks_or_dataset, BenchmarkDataset):
            pairs = select_dataset_tasks(
                tasks_or_dataset,
                split=split,
                category=category,
                task_ids=task_ids,
                golden_only=golden_only,
            )
            effective_dataset_id = tasks_or_dataset.manifest.dataset_id
            effective_dataset_version = tasks_or_dataset.manifest.dataset_version
            effective_schema_version = tasks_or_dataset.manifest.task_schema_version
        else:
            tasks = tuple(tasks_or_dataset)
            truths = tuple(ground_truths or ())
            if split is not None or category is not None or golden_only:
                raise BenchmarkPrerequisiteError(
                    "split/category/golden selection requires a loaded BenchmarkDataset"
                )
            truth_by_key = {(truth.ground_truth_id, truth.version): truth for truth in truths}
            pairs = []
            requested_ids = set(task_ids)
            for task in tasks:
                if requested_ids and task.benchmark_task_id not in requested_ids:
                    continue
                truth = truth_by_key.get(
                    (task.ground_truth_ref.ground_truth_id, task.ground_truth_ref.version)
                )
                if truth is None:
                    raise BenchmarkPrerequisiteError(
                        f"task GroundTruth is not resolvable: {task.benchmark_task_id}"
                    )
                pairs.append((task, truth))
            if requested_ids and requested_ids != {task.benchmark_task_id for task, _ in pairs}:
                raise BenchmarkPrerequisiteError("requested task IDs were not selected")
            if not pairs:
                raise BenchmarkPrerequisiteError("task collection is empty")
            effective_dataset_id = dataset_id or "ad-hoc"
            effective_dataset_version = dataset_version or "unversioned"
            effective_schema_version = task_schema_version or pairs[0][0].schema_version

        effective_evaluation_run_id = evaluation_run_id or self._identity_factory("evaluation_run")
        _safe_component(effective_evaluation_run_id)
        started_at = datetime.now(UTC)
        store = result_store or self._result_store
        results: list[BenchmarkTaskResult] = []
        aborted = False
        abort_reason: str | None = None
        total = len(pairs)
        for index, (task, truth) in enumerate(pairs, start=1):
            result = await self.run_task(
                task,
                truth,
                evaluation_run_id=effective_evaluation_run_id,
                result_store=store,
            )
            results.append(result)
            if on_progress is not None:
                try:
                    on_progress(
                        BenchmarkProgress(
                            evaluation_run_id=effective_evaluation_run_id,
                            current=index,
                            total=total,
                            benchmark_task_id=task.benchmark_task_id,
                            status=result.status,
                        )
                    )
                except Exception:  # noqa: BLE001 - progress is observational only
                    pass
            if (
                result.cleanup_status is BenchmarkLifecycleStatus.FAILED
                and self._policy.abort_on_cleanup_failure
            ):
                aborted = True
                abort_reason = f"cleanup failure for {task.benchmark_task_id}"
                break

        completed_at = datetime.now(UTC)
        run = BenchmarkRun(
            evaluation_run_id=effective_evaluation_run_id,
            dataset_id=effective_dataset_id,
            dataset_version=effective_dataset_version,
            task_schema_version=effective_schema_version,
            split=DatasetSplit(split) if isinstance(split, str) else split,
            selected_task_ids=tuple(task.benchmark_task_id for task, _ in pairs[: len(results)]),
            results=tuple(results),
            started_at=started_at,
            completed_at=completed_at,
            policy=self._policy,
            aborted=aborted,
            abort_reason=abort_reason,
        )
        if store is not None:
            store.persist_run(run)
        return run

    async def run_dataset(
        self,
        manifest_path: Path | None = None,
        **kwargs: Any,
    ) -> BenchmarkRun:
        """Load and fail closed on the formal Dataset Quality Gate before running."""

        report = lint_dataset(manifest_path)
        if not report.dataset_ready:
            error_count = sum(issue.severity == "ERROR" for issue in report.issues)
            warning_count = sum(issue.severity == "WARNING" for issue in report.issues)
            raise BenchmarkDatasetNotReadyError(
                f"dataset is not ready: errors={error_count}, warnings={warning_count}"
            )
        return await self.run_batch(load_dataset(manifest_path), **kwargs)

    async def _execute_with_retry(
        self,
        task: BenchmarkTask,
        setup: FixtureSetup,
        *,
        trace_id: str,
        agent_run_id: str,
    ) -> tuple[BenchmarkExecutionOutcome, int]:
        attempts = 0
        while attempts < self._policy.max_infrastructure_attempts:
            attempts += 1
            try:
                outcome = await self._workflow_adapter.execute(
                    task,
                    setup,
                    trace_id=trace_id,
                    agent_run_id=agent_run_id,
                )
                if not isinstance(outcome, BenchmarkExecutionOutcome):
                    raise TypeError("workflow adapter must return BenchmarkExecutionOutcome")
                return outcome, attempts
            except BenchmarkInfrastructureError as exc:
                setattr(exc, "_benchmark_attempts", attempts)
                retry_allowed = (
                    exc.retryable
                    and exc.code in self._policy.retryable_infrastructure_codes
                    and attempts < self._policy.max_infrastructure_attempts
                )
                if not retry_allowed:
                    raise
            except Exception as exc:  # noqa: BLE001 - do not retry Agent failures
                setattr(exc, "_benchmark_attempts", attempts)
                raise
        raise AssertionError(f"retry loop exhausted without a result for {task.benchmark_task_id}")


__all__ = [
    "ArtifactPathPreflightError",
    "BenchmarkDatasetNotReadyError",
    "BenchmarkExecutionOutcome",
    "BenchmarkExecutionMode",
    "BenchmarkFailureCategory",
    "BenchmarkFailureStage",
    "BenchmarkFixtureAdapter",
    "BenchmarkInfrastructureError",
    "JavaExecutionStatus",
    "BenchmarkLifecycleStatus",
    "BenchmarkPrerequisiteError",
    "BenchmarkProgress",
    "BenchmarkResultStore",
    "BenchmarkRun",
    "BenchmarkRunPolicy",
    "BenchmarkRunner",
    "BenchmarkTaskFailure",
    "BenchmarkTaskResult",
    "BenchmarkTaskStatus",
    "CallableStage20WorkflowAdapter",
    "FixtureSetup",
    "FormalEvidenceSnapshot",
    "JsonBenchmarkResultStore",
    "MAX_PLANNED_ARTIFACT_PATH",
    "Stage20WorkflowAdapter",
    "StaticFixtureAdapter",
    "ToolResultObservation",
    "physical_run_directory_name",
    "physical_task_result_filename",
    "preflight_artifact_paths",
    "project_tool_result_observations",
    "project_formal_evidence_snapshot",
    "select_dataset_tasks",
]
