"""SQLite-backed runtime facts and aggregation for the Evaluation read model."""

from __future__ import annotations

import os
import sqlite3
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from statistics import fmean
from threading import RLock
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.core.settings import get_settings
from app.evaluator import (
    EvaluationCase,
    EvaluationResult,
    GroundTruth,
    JudgeResult,
    MetricStatus,
    RuleBasedEvaluator,
)
from app.tracing import (
    AgentRun,
    ApprovalFact,
    ModelCall,
    SafetyViolationFact,
    ToolIntentRecord,
    ToolResultRecord,
    TraceEvent,
    TraceRecord,
    TraceStatus,
)

RuntimeExecutionType = Literal["DIAGNOSIS", "TESTCASE_GENERATION"]
RuntimeRunStatus = Literal[
    "RUNNING",
    "COMPLETED",
    "FAILED",
    "APPROVAL_REQUIRED",
    "REJECTED",
]

_TERMINAL_STATUSES = frozenset({"COMPLETED", "FAILED", "REJECTED"})
_BOOLEAN_METRICS = frozenset({"executionSuccess", "validJson", "schemaValid", "contractAccepted"})
_SUMMARY_METRICS = (
    "executionSuccess",
    "validJson",
    "schemaValid",
    "contractAccepted",
    "wallClockLatencyMs",
    "modelLatencyMs",
    "promptTokens",
    "completionTokens",
    "totalTokens",
    "cost",
)


class _RuntimeModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        populate_by_name=False,
        strict=True,
    )


class RuntimeMetric(_RuntimeModel):
    status: MetricStatus
    value: float | None = None
    unit: str | None = None
    reason: str | None = None


class RuntimeMetricAggregate(_RuntimeModel):
    metric: str
    status: MetricStatus
    total_count: int = Field(alias="totalCount", ge=0)
    applicable_count: int = Field(alias="applicableCount", ge=0)
    value_count: int = Field(alias="valueCount", ge=0)
    not_applicable_count: int = Field(alias="notApplicableCount", ge=0)
    unknown_count: int = Field(alias="unknownCount", ge=0)
    error_count: int = Field(alias="errorCount", ge=0)
    unit: str | None = None
    mean: float | None = None
    rate: float | None = None
    reason: str | None = None


class RuntimeExecutionCounts(_RuntimeModel):
    total: int = Field(ge=0)
    success: int = Field(ge=0)
    failure: int = Field(ge=0)
    running: int = Field(ge=0)
    approval_required: int = Field(alias="approvalRequired", ge=0)
    rejected: int = Field(ge=0)
    unknown: int = Field(ge=0)


class RuntimeToolCounts(_RuntimeModel):
    attempted: int = Field(ge=0)
    success: int = Field(ge=0)
    failed: int = Field(ge=0)
    denied: int = Field(ge=0)
    timeout: int = Field(ge=0)
    unknown: int = Field(ge=0)
    not_applicable: int = Field(alias="notApplicable", ge=0)


class RuntimeSafetyCounts(_RuntimeModel):
    explicit_outcomes: dict[str, int] = Field(alias="explicitOutcomes")
    unknown: int = Field(ge=0)


class RuntimeRunSummary(_RuntimeModel):
    agent_run_id: str = Field(alias="agentRunId", min_length=1)
    trace_id: str = Field(alias="traceId", min_length=1)
    execution_type: RuntimeExecutionType = Field(alias="executionType")
    status: RuntimeRunStatus
    provider: str = Field(min_length=1)
    model: str = Field(min_length=1)
    project_id: int | None = Field(default=None, alias="projectId", ge=1)
    api_id: str | None = Field(default=None, alias="apiId", min_length=1)
    run_id: int | None = Field(default=None, alias="runId", ge=1)
    report_id: str | None = Field(default=None, alias="reportId", min_length=1)
    started_at: datetime = Field(alias="startedAt")
    finished_at: datetime | None = Field(default=None, alias="finishedAt")


class RuntimeRunDetail(RuntimeRunSummary):
    metrics: dict[str, RuntimeMetric]
    tool_counts: RuntimeToolCounts = Field(alias="toolCounts")
    safety_status: MetricStatus = Field(alias="safetyStatus")
    safety_outcome: str | None = Field(default=None, alias="safetyOutcome")
    safety_reason: str | None = Field(default=None, alias="safetyReason")
    trace_record_count: int = Field(alias="traceRecordCount", ge=0)
    failure_code: str | None = Field(default=None, alias="failureCode")
    failure_message: str | None = Field(default=None, alias="failureMessage")
    evaluation_result: EvaluationResult | None = Field(
        default=None,
        alias="evaluationResult",
    )
    judge_results: tuple[JudgeResult, ...] = Field(default=(), alias="judgeResults")


class RuntimeEvaluationSummary(_RuntimeModel):
    runtime: Literal["PYTHON_AGENTLAB"] = "PYTHON_AGENTLAB"
    run_count: int = Field(alias="runCount", ge=0)
    execution: RuntimeExecutionCounts
    metrics: dict[str, RuntimeMetricAggregate]
    tool: RuntimeToolCounts
    safety: RuntimeSafetyCounts


@dataclass(frozen=True, slots=True)
class RuntimeValidationFacts:
    """Facts already emitted by the TestCase generation validator."""

    valid_json: bool | None
    schema_valid: bool | None
    contract_accepted: bool | None


@dataclass(slots=True)
class _RuntimeRun:
    agent_run_id: str
    trace_id: str
    execution_type: RuntimeExecutionType
    provider: str
    model: str
    project_id: int | None
    api_id: str | None
    run_id: int | None
    report_id: str | None
    started_at: datetime
    validation_applicable: bool
    status: RuntimeRunStatus = "RUNNING"
    finished_at: datetime | None = None
    validation: RuntimeValidationFacts = field(
        default_factory=lambda: RuntimeValidationFacts(None, None, None)
    )
    trace_records: tuple[TraceRecord, ...] = ()
    failure_code: str | None = None
    failure_message: str | None = None


class _StoredRuntimeRun(_RuntimeModel):
    """Versioned durable state; Trace remains in the existing Trace sink."""

    schema_version: Literal["runtime-evaluation-v1"] = "runtime-evaluation-v1"
    agent_run_id: str
    trace_id: str
    execution_type: RuntimeExecutionType
    provider: str
    model: str
    project_id: int | None
    api_id: str | None
    run_id: int | None
    report_id: str | None
    started_at: datetime
    validation_applicable: bool
    status: RuntimeRunStatus
    finished_at: datetime | None
    valid_json: bool | None
    schema_valid: bool | None
    contract_accepted: bool | None
    failure_code: str | None
    failure_message: str | None
    detail: RuntimeRunDetail


_TABLE_NAME = "runtime_evaluation_run"
_SCHEMA = f"""
CREATE TABLE IF NOT EXISTS {_TABLE_NAME} (
    agent_run_id TEXT PRIMARY KEY,
    trace_id TEXT NOT NULL,
    project_id INTEGER,
    run_id INTEGER,
    evaluation_type TEXT NOT NULL,
    status TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_runtime_evaluation_project_created
    ON {_TABLE_NAME}(project_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_runtime_evaluation_trace
    ON {_TABLE_NAME}(trace_id);
"""


class RuntimeEvaluationStore:
    """Latest/current Console Evaluation projection for each Agent Run.

    This durable read model is keyed by ``agent_run_id``. It is not formal,
    multi-version Evaluation experiment history and does not replace the
    Stage 19 or Benchmark Evaluation artifacts.
    """

    def __init__(self, database_path: str | os.PathLike[str] = ":memory:") -> None:
        self.database_path = os.fspath(database_path)
        if not self.database_path:
            raise ValueError("database_path must not be empty")
        if self.database_path != ":memory:":
            Path(self.database_path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()
        self._trace_records: dict[str, tuple[TraceRecord, ...]] = {}
        self._connection = sqlite3.connect(self.database_path, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        with self._connection:
            self._connection.executescript(_SCHEMA)

    def begin(
        self,
        *,
        agent_run_id: str,
        trace_id: str,
        execution_type: RuntimeExecutionType,
        provider: str,
        model: str,
        project_id: int | None = None,
        api_id: str | None = None,
        run_id: int | None = None,
        report_id: str | None = None,
        validation_applicable: bool = False,
        started_at: datetime | None = None,
    ) -> None:
        run = _RuntimeRun(
            agent_run_id=agent_run_id,
            trace_id=trace_id,
            execution_type=execution_type,
            provider=provider,
            model=model,
            project_id=project_id,
            api_id=api_id,
            run_id=run_id,
            report_id=report_id,
            started_at=started_at or datetime.now(UTC),
            validation_applicable=validation_applicable,
        )
        with self._lock:
            self._save(self._stored(run, self._detail(run)))

    def update(
        self,
        *,
        agent_run_id: str,
        status: RuntimeRunStatus,
        trace_records: Sequence[TraceRecord] = (),
        validation: RuntimeValidationFacts | None = None,
        failure_code: str | None = None,
        failure_message: str | None = None,
        finished_at: datetime | None = None,
    ) -> None:
        with self._lock:
            stored = self._get(agent_run_id)
            if stored is None:
                return
            run = self._run(stored)
            run.status = status
            records = tuple(trace_records)
            run.trace_records = records
            self._trace_records[agent_run_id] = records
            if validation is not None:
                run.validation = validation
            if failure_code is not None:
                run.failure_code = failure_code
                run.failure_message = failure_message
            elif status == "COMPLETED":
                run.failure_code = None
                run.failure_message = None
            if status in _TERMINAL_STATUSES:
                run.finished_at = finished_at or datetime.now(UTC)
            else:
                run.finished_at = None
            detail = self._detail(
                run,
                evaluation_result=stored.detail.evaluation_result,
                judge_results=stored.detail.judge_results,
            )
            self._save(self._stored(run, detail))

    def evaluate_and_persist(
        self,
        *,
        case: EvaluationCase,
        ground_truth: GroundTruth,
        trace_records: Sequence[TraceRecord],
        judge_results: Sequence[JudgeResult] = (),
    ) -> EvaluationResult:
        """Run the Stage 19 evaluator only with an explicit, real Ground Truth."""

        with self._lock:
            stored = self._get(case.agent_run_id)
            if stored is None:
                raise KeyError(f"runtime run not found: {case.agent_run_id}")
            if (stored.trace_id, stored.agent_run_id) != (case.trace_id, case.agent_run_id):
                raise ValueError("EvaluationCase identity does not match runtime run")
            result = RuleBasedEvaluator().evaluate(case, ground_truth, trace_records)
            judges = tuple(judge_results)
            if any(
                item.trace_id != case.trace_id or item.agent_run_id != case.agent_run_id
                for item in judges
            ):
                raise ValueError("JudgeResult identity does not match runtime run")
            detail = stored.detail.model_copy(
                update={"evaluation_result": result, "judge_results": judges}
            )
            self._save(stored.model_copy(update={"detail": detail}))
            return result

    def list_runs(
        self,
        *,
        project_id: int | None = None,
        limit: int = 50,
    ) -> tuple[RuntimeRunSummary, ...]:
        with self._lock:
            stored = self._list(project_id=project_id, limit=limit)
        return tuple(self._summary(self._run(item)) for item in stored)

    def get_detail(self, agent_run_id: str) -> RuntimeRunDetail | None:
        with self._lock:
            stored = self._get(agent_run_id)
            return None if stored is None else stored.detail

    def get_project_id(self, agent_run_id: str) -> int | None:
        with self._lock:
            stored = self._get(agent_run_id)
            return None if stored is None else stored.project_id

    def list_trace_records(self, *, project_id: int) -> tuple[TraceRecord, ...]:
        """Return only observed records for one already-authorized project."""

        with self._lock:
            records = [
                record
                for agent_run_id, run_records in self._trace_records.items()
                if (stored := self._get(agent_run_id)) is not None
                and stored.project_id == project_id
                for record in run_records
            ]
        return tuple(sorted(records, key=_trace_record_sort_key))

    def get_trace_records(self, trace_id: str) -> tuple[TraceRecord, ...]:
        """Return one correlation's observed records without inventing a snapshot."""

        with self._lock:
            records = [
                record
                for agent_run_id, run_records in self._trace_records.items()
                if (stored := self._get(agent_run_id)) is not None and stored.trace_id == trace_id
                for record in run_records
                if record.trace_id == trace_id
            ]
        return tuple(sorted(records, key=_trace_record_sort_key))

    def get_trace_project_id(self, trace_id: str) -> int | None:
        """Resolve the single project owner needed for Java authorization."""

        with self._lock:
            project_ids = {
                stored.project_id
                for agent_run_id, records in self._trace_records.items()
                if (stored := self._get(agent_run_id)) is not None
                and stored.trace_id == trace_id
                and any(record.trace_id == trace_id for record in records)
            }
        return next(iter(project_ids)) if len(project_ids) == 1 else None

    def summary(self, *, project_id: int | None = None) -> RuntimeEvaluationSummary:
        with self._lock:
            details = [item.detail for item in self._list(project_id=project_id)]

        execution = RuntimeExecutionCounts(
            total=len(details),
            success=sum(item.status == "COMPLETED" for item in details),
            failure=sum(item.status in {"FAILED", "REJECTED"} for item in details),
            running=sum(item.status == "RUNNING" for item in details),
            approvalRequired=sum(item.status == "APPROVAL_REQUIRED" for item in details),
            rejected=sum(item.status == "REJECTED" for item in details),
            unknown=0,
        )
        tool = self._sum_tool_counts(item.tool_counts for item in details)
        explicit_outcomes = Counter(
            item.safety_outcome
            for item in details
            if item.safety_status is MetricStatus.VALUE and item.safety_outcome is not None
        )
        safety = RuntimeSafetyCounts(
            explicitOutcomes=dict(sorted(explicit_outcomes.items())),
            unknown=sum(item.safety_status is MetricStatus.UNKNOWN for item in details),
        )
        metrics = {
            name: self._aggregate_metric(name, [item.metrics[name] for item in details])
            for name in _SUMMARY_METRICS
        }
        return RuntimeEvaluationSummary(
            runCount=len(details),
            execution=execution,
            metrics=metrics,
            tool=tool,
            safety=safety,
        )

    def clear(self) -> None:
        """Reset this read model for tests and local development."""

        with self._lock:
            with self._connection:
                self._connection.execute(f"DELETE FROM {_TABLE_NAME}")
            self._trace_records.clear()

    def close(self) -> None:
        with self._lock:
            self._connection.close()

    def _get(self, agent_run_id: str) -> _StoredRuntimeRun | None:
        row = self._connection.execute(
            f"SELECT payload_json FROM {_TABLE_NAME} WHERE agent_run_id = ?",
            (agent_run_id,),
        ).fetchone()
        return None if row is None else _StoredRuntimeRun.model_validate_json(row["payload_json"])

    def _list(
        self,
        *,
        project_id: int | None = None,
        limit: int | None = None,
    ) -> tuple[_StoredRuntimeRun, ...]:
        where = "" if project_id is None else "WHERE project_id = ?"
        parameters: list[object] = [] if project_id is None else [project_id]
        suffix = "" if limit is None else " LIMIT ?"
        if limit is not None:
            parameters.append(limit)
        rows = self._connection.execute(
            f"SELECT payload_json FROM {_TABLE_NAME} {where} "
            f"ORDER BY created_at DESC, agent_run_id DESC{suffix}",
            parameters,
        ).fetchall()
        return tuple(_StoredRuntimeRun.model_validate_json(row["payload_json"]) for row in rows)

    def _save(self, stored: _StoredRuntimeRun) -> None:
        now = datetime.now(UTC).isoformat()
        existing = self._connection.execute(
            f"SELECT created_at FROM {_TABLE_NAME} WHERE agent_run_id = ?",
            (stored.agent_run_id,),
        ).fetchone()
        created_at = existing["created_at"] if existing is not None else now
        with self._connection:
            self._connection.execute(
                f"""
                INSERT INTO {_TABLE_NAME} (
                    agent_run_id, trace_id, project_id, run_id, evaluation_type,
                    status, payload_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(agent_run_id) DO UPDATE SET
                    trace_id = excluded.trace_id,
                    project_id = excluded.project_id,
                    run_id = excluded.run_id,
                    evaluation_type = excluded.evaluation_type,
                    status = excluded.status,
                    payload_json = excluded.payload_json,
                    updated_at = excluded.updated_at
                """,
                (
                    stored.agent_run_id,
                    stored.trace_id,
                    stored.project_id,
                    stored.run_id,
                    stored.execution_type,
                    stored.status,
                    stored.model_dump_json(by_alias=True),
                    created_at,
                    now,
                ),
            )

    @staticmethod
    def _run(stored: _StoredRuntimeRun) -> _RuntimeRun:
        return _RuntimeRun(
            agent_run_id=stored.agent_run_id,
            trace_id=stored.trace_id,
            execution_type=stored.execution_type,
            provider=stored.provider,
            model=stored.model,
            project_id=stored.project_id,
            api_id=stored.api_id,
            run_id=stored.run_id,
            report_id=stored.report_id,
            started_at=stored.started_at,
            validation_applicable=stored.validation_applicable,
            status=stored.status,
            finished_at=stored.finished_at,
            validation=RuntimeValidationFacts(
                stored.valid_json,
                stored.schema_valid,
                stored.contract_accepted,
            ),
            failure_code=stored.failure_code,
            failure_message=stored.failure_message,
        )

    @staticmethod
    def _stored(run: _RuntimeRun, detail: RuntimeRunDetail) -> _StoredRuntimeRun:
        return _StoredRuntimeRun(
            agent_run_id=run.agent_run_id,
            trace_id=run.trace_id,
            execution_type=run.execution_type,
            provider=run.provider,
            model=run.model,
            project_id=run.project_id,
            api_id=run.api_id,
            run_id=run.run_id,
            report_id=run.report_id,
            started_at=run.started_at,
            validation_applicable=run.validation_applicable,
            status=run.status,
            finished_at=run.finished_at,
            valid_json=run.validation.valid_json,
            schema_valid=run.validation.schema_valid,
            contract_accepted=run.validation.contract_accepted,
            failure_code=run.failure_code,
            failure_message=run.failure_message,
            detail=detail,
        )

    def _summary(self, run: _RuntimeRun) -> RuntimeRunSummary:
        return RuntimeRunSummary(
            agentRunId=run.agent_run_id,
            traceId=run.trace_id,
            executionType=run.execution_type,
            status=run.status,
            provider=run.provider,
            model=run.model,
            projectId=run.project_id,
            apiId=run.api_id,
            runId=run.run_id,
            reportId=run.report_id,
            startedAt=run.started_at,
            finishedAt=run.finished_at,
        )

    def _detail(
        self,
        run: _RuntimeRun,
        *,
        evaluation_result: EvaluationResult | None = None,
        judge_results: tuple[JudgeResult, ...] = (),
    ) -> RuntimeRunDetail:
        metrics = {
            "executionSuccess": self._execution_metric(run),
            "validJson": self._validation_metric(run, "valid_json"),
            "schemaValid": self._validation_metric(run, "schema_valid"),
            "contractAccepted": self._validation_metric(run, "contract_accepted"),
            "wallClockLatencyMs": self._wall_latency(run),
            "modelLatencyMs": self._model_latency(run.trace_records),
            "promptTokens": self._tokens(run.trace_records, "prompt_tokens"),
            "completionTokens": self._tokens(run.trace_records, "completion_tokens"),
            "totalTokens": self._tokens(run.trace_records, "total_tokens"),
            "cost": self._cost(run.trace_records),
        }
        safety_outcome = self._safety_outcome(run.trace_records)
        safety_status = MetricStatus.VALUE if safety_outcome is not None else MetricStatus.UNKNOWN
        safety_reason = (
            None if safety_outcome is not None else "no explicit safety outcome was recorded"
        )
        return RuntimeRunDetail(
            **self._summary(run).model_dump(by_alias=True),
            metrics=metrics,
            toolCounts=self._tool_counts(run.trace_records),
            safetyStatus=safety_status,
            safetyOutcome=safety_outcome,
            safetyReason=safety_reason,
            traceRecordCount=len(run.trace_records),
            failureCode=run.failure_code,
            failureMessage=run.failure_message,
            evaluationResult=evaluation_result,
            judgeResults=judge_results,
        )

    @staticmethod
    def _execution_metric(run: _RuntimeRun) -> RuntimeMetric:
        if run.status == "COMPLETED":
            return RuntimeMetric(status=MetricStatus.VALUE, value=1.0)
        if run.status in {"FAILED", "REJECTED"}:
            return RuntimeMetric(status=MetricStatus.VALUE, value=0.0)
        return RuntimeMetric(
            status=MetricStatus.UNKNOWN,
            reason="execution has not reached a terminal status",
        )

    @staticmethod
    def _validation_metric(run: _RuntimeRun, field_name: str) -> RuntimeMetric:
        if not run.validation_applicable:
            return RuntimeMetric(
                status=MetricStatus.NOT_APPLICABLE,
                reason="this runtime does not emit TestCase validation facts",
            )
        value = getattr(run.validation, field_name)
        if value is None:
            return RuntimeMetric(
                status=MetricStatus.UNKNOWN,
                reason="the existing validation workflow did not emit this fact",
            )
        return RuntimeMetric(status=MetricStatus.VALUE, value=float(value))

    @staticmethod
    def _wall_latency(run: _RuntimeRun) -> RuntimeMetric:
        starts = [
            item.timestamp
            for item in run.trace_records
            if isinstance(item, AgentRun) and item.event is TraceEvent.START
        ]
        terminals = [
            item.timestamp
            for item in run.trace_records
            if isinstance(item, AgentRun) and item.event is TraceEvent.TERMINAL
        ]
        if starts and terminals:
            duration = (terminals[-1] - starts[0]).total_seconds() * 1000
        elif run.finished_at is not None:
            duration = (run.finished_at - run.started_at).total_seconds() * 1000
        else:
            return RuntimeMetric(
                status=MetricStatus.UNKNOWN,
                reason="agent run has no terminal timestamp",
            )
        return RuntimeMetric(status=MetricStatus.VALUE, value=max(0.0, duration), unit="ms")

    @staticmethod
    def _model_latency(records: Sequence[TraceRecord]) -> RuntimeMetric:
        all_calls = [item for item in records if isinstance(item, ModelCall)]
        if not all_calls:
            return RuntimeMetric(
                status=MetricStatus.NOT_APPLICABLE,
                reason="agent run has no model call",
            )
        calls = [item for item in all_calls if item.event is TraceEvent.TERMINAL]
        if not calls or any(
            item.latency is None or item.latency.duration_ms is None for item in calls
        ):
            return RuntimeMetric(
                status=MetricStatus.UNKNOWN,
                reason="one or more model-call duration facts are unavailable",
            )
        return RuntimeMetric(
            status=MetricStatus.VALUE,
            value=sum(
                float(item.latency.duration_ms) for item in calls if item.latency is not None
            ),
            unit="ms",
        )

    @staticmethod
    def _tokens(records: Sequence[TraceRecord], field_name: str) -> RuntimeMetric:
        all_calls = [item for item in records if isinstance(item, ModelCall)]
        if not all_calls:
            return RuntimeMetric(
                status=MetricStatus.NOT_APPLICABLE,
                reason="agent run has no model call",
            )
        calls = [item for item in all_calls if item.event is TraceEvent.TERMINAL]
        values = [
            getattr(item.token_usage, field_name) for item in calls if item.token_usage is not None
        ]
        if not calls or len(values) != len(calls) or any(value is None for value in values):
            return RuntimeMetric(
                status=MetricStatus.UNKNOWN,
                reason="provider token usage is missing for one or more model calls",
            )
        return RuntimeMetric(
            status=MetricStatus.VALUE,
            value=float(sum(value for value in values if value is not None)),
            unit="tokens",
        )

    @staticmethod
    def _cost(records: Sequence[TraceRecord]) -> RuntimeMetric:
        all_calls = [item for item in records if isinstance(item, ModelCall)]
        if not all_calls:
            return RuntimeMetric(
                status=MetricStatus.NOT_APPLICABLE,
                reason="agent run has no model call",
            )
        return RuntimeMetric(
            status=MetricStatus.UNKNOWN,
            reason="versioned model pricing is not configured for runtime evaluation",
        )

    @classmethod
    def _tool_counts(cls, records: Sequence[TraceRecord]) -> RuntimeToolCounts:
        intents = {
            item.tool_intent_id: item
            for item in records
            if isinstance(item, ToolIntentRecord) and item.event is TraceEvent.INTENT
        }
        results = [item for item in records if isinstance(item, ToolResultRecord)]
        if not intents and not results:
            return RuntimeToolCounts(
                attempted=0,
                success=0,
                failed=0,
                denied=0,
                timeout=0,
                unknown=0,
                notApplicable=1,
            )

        counts = Counter(cls._tool_result_bucket(item) for item in results)
        result_intents = {
            item.tool_intent_id for item in results if item.tool_intent_id is not None
        }
        for intent_id, intent in intents.items():
            if intent_id in result_intents:
                continue
            counts[cls._unresolved_intent_bucket(intent, records)] += 1

        attempted = sum(
            counts[key] for key in ("success", "failed", "denied", "timeout", "unknown")
        )
        return RuntimeToolCounts(
            attempted=attempted,
            success=counts["success"],
            failed=counts["failed"],
            denied=counts["denied"],
            timeout=counts["timeout"],
            unknown=counts["unknown"],
            notApplicable=0,
        )

    @staticmethod
    def _tool_result_bucket(record: ToolResultRecord) -> str:
        status = record.tool_result_status
        if status == "SUCCESS":
            return "success"
        if status == "FORBIDDEN" or record.status is TraceStatus.DENIED:
            return "denied"
        if status == "TIMEOUT":
            return "timeout"
        if status in {"FAILED", "PARAM_INVALID", "RESULT_INVALID"}:
            return "failed"
        return "unknown"

    @staticmethod
    def _unresolved_intent_bucket(
        intent: ToolIntentRecord,
        records: Sequence[TraceRecord],
    ) -> str:
        decision = getattr(intent.python_decision, "value", intent.python_decision)
        if decision == "DENY":
            return "denied"
        approvals = [
            item
            for item in records
            if isinstance(item, ApprovalFact) and item.intent_id == intent.tool_intent_id
        ]
        if any(getattr(item.decision, "value", item.decision) == "REJECT" for item in approvals):
            return "denied"
        codes = {
            item.failure.failure_code
            for item in records
            if item.failure is not None and item.failure.failure_code is not None
        }
        if any("TIMEOUT" in code for code in codes):
            return "timeout"
        if any(code in {"JAVA_AUTHORIZATION_DENIED", "PYTHON_PREFLIGHT_DENIED"} for code in codes):
            return "denied"
        return "unknown"

    @staticmethod
    def _safety_outcome(records: Sequence[TraceRecord]) -> str | None:
        failure_codes = {
            item.failure.failure_code
            for item in records
            if item.failure is not None and item.failure.failure_code is not None
        }
        if "HUMAN_REJECTED" in failure_codes or any(
            isinstance(item, ApprovalFact)
            and getattr(item.decision, "value", item.decision) == "REJECT"
            for item in records
        ):
            return "HUMAN_REJECTED"
        if "JAVA_AUTHORIZATION_DENIED" in failure_codes or any(
            isinstance(item, ToolResultRecord) and item.status is TraceStatus.DENIED
            for item in records
        ):
            return "JAVA_DENIED"
        if failure_codes & {
            "APPROVAL_RESPONSE_INVALID",
            "STALE_APPROVAL",
            "WORKFLOW_IDENTITY_MISMATCH",
        }:
            return "APPROVAL_BYPASS_BLOCKED"
        if "PYTHON_PREFLIGHT_DENIED" in failure_codes or any(
            isinstance(item, ToolIntentRecord)
            and getattr(item.python_decision, "value", item.python_decision) == "DENY"
            for item in records
        ):
            return "FORBIDDEN_INTENT_DENIED"
        if any(isinstance(item, SafetyViolationFact) for item in records):
            return "SAFETY_VIOLATION"
        return None

    @classmethod
    def _aggregate_metric(
        cls,
        name: str,
        samples: Sequence[RuntimeMetric],
    ) -> RuntimeMetricAggregate:
        values = [float(item.value) for item in samples if item.status is MetricStatus.VALUE]
        not_applicable = sum(item.status is MetricStatus.NOT_APPLICABLE for item in samples)
        unknown = sum(item.status is MetricStatus.UNKNOWN for item in samples)
        errors = sum(item.status is MetricStatus.ERROR for item in samples)
        units = {item.unit for item in samples if item.status is MetricStatus.VALUE and item.unit}
        if len(units) > 1:
            return RuntimeMetricAggregate(
                metric=name,
                status=MetricStatus.ERROR,
                totalCount=len(samples),
                applicableCount=len(samples) - not_applicable,
                valueCount=len(values),
                notApplicableCount=not_applicable,
                unknownCount=unknown,
                errorCount=errors + 1,
                reason="runtime metric has mixed units",
            )
        mean = fmean(values) if values else None
        if values:
            status = MetricStatus.VALUE
        elif errors:
            status = MetricStatus.ERROR
        elif unknown:
            status = MetricStatus.UNKNOWN
        else:
            status = MetricStatus.NOT_APPLICABLE
        return RuntimeMetricAggregate(
            metric=name,
            status=status,
            totalCount=len(samples),
            applicableCount=len(samples) - not_applicable,
            valueCount=len(values),
            notApplicableCount=not_applicable,
            unknownCount=unknown,
            errorCount=errors,
            unit=next(iter(units)) if units else None,
            mean=mean,
            rate=mean if name in _BOOLEAN_METRICS else None,
            reason=("no VALUE samples" if not values else None),
        )

    @staticmethod
    def _sum_tool_counts(items: Sequence[RuntimeToolCounts]) -> RuntimeToolCounts:
        items = tuple(items)
        return RuntimeToolCounts(
            attempted=sum(item.attempted for item in items),
            success=sum(item.success for item in items),
            failed=sum(item.failed for item in items),
            denied=sum(item.denied for item in items),
            timeout=sum(item.timeout for item in items),
            unknown=sum(item.unknown for item in items),
            notApplicable=sum(item.not_applicable for item in items),
        )


runtime_evaluation_store = RuntimeEvaluationStore(get_settings().runtime_db_path)


def _trace_record_sort_key(record: TraceRecord) -> tuple[datetime, int]:
    return record.timestamp, record.sequence or 0


__all__ = [
    "RuntimeEvaluationStore",
    "RuntimeEvaluationSummary",
    "RuntimeMetric",
    "RuntimeMetricAggregate",
    "RuntimeRunDetail",
    "RuntimeRunStatus",
    "RuntimeRunSummary",
    "RuntimeSafetyCounts",
    "RuntimeToolCounts",
    "RuntimeValidationFacts",
    "runtime_evaluation_store",
]
