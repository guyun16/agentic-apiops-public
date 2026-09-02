"""Minimal typed state contract for the Python AgentLab workflow boundary."""

from __future__ import annotations

from enum import StrEnum
from typing import NotRequired, TypedDict

from app.agents.testcase_generator import Candidate
from app.rag.context import ContextPack
from app.schemas.openapi_metadata import OpenApiMetadataDetail
from app.workflows.candidate_validation import CandidateValidationResult
from app.workflows.generation_context import GenerationContext


class WorkflowPhase(StrEnum):
    INITIAL = "INITIAL"
    PREPARED = "PREPARED"
    FINISHED = "FINISHED"
    REJECTED = "REJECTED"


class WorkflowRoute(StrEnum):
    READY = "READY"
    BLOCKED = "BLOCKED"


class TestCaseGenerationStatus(StrEnum):
    __test__ = False

    ACCEPTED = "ACCEPTED"
    VALIDATION_FAILURE = "VALIDATION_FAILURE"
    GENERATION_FAILURE = "GENERATION_FAILURE"
    REPAIR_EXHAUSTED = "REPAIR_EXHAUSTED"


class ContextEnrichmentStatus(StrEnum):
    """Workflow-local context outcome, separate from candidate generation."""

    READY = "READY"
    DEGRADED = "DEGRADED"
    FAILED = "FAILED"


class APIOpsAgentState(TypedDict):
    """Minimal Python workflow state; not a shared cross-system Contract."""

    trace_id: str | None
    agent_run_id: NotRequired[str]
    phase: WorkflowPhase
    route: WorkflowRoute | None
    error: str | None
    attempt_count: int
    max_attempts: int
    project_id: int
    api_id: str
    generation_intent: str
    api_metadata: OpenApiMetadataDetail | None
    generation_context: GenerationContext | None
    context_pack: ContextPack | None
    context_status: ContextEnrichmentStatus | None
    context_error: str | None
    candidate: Candidate | None
    validation_result: CandidateValidationResult | None
    repair_attempts: int
    max_repair_attempts: int
    generation_status: TestCaseGenerationStatus | None
