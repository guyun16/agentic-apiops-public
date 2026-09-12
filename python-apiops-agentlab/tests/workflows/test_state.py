"""Deterministic tests for the minimal Python workflow state boundary."""

from __future__ import annotations

from typing import get_type_hints

from app.agents.testcase_generator import Candidate
from app.rag.context import ContextPack
from app.schemas.openapi_metadata import OpenApiMetadataDetail
from app.workflows.candidate_validation import CandidateValidationResult
from app.workflows.generation_context import GenerationContext
from app.workflows.state import (
    APIOpsAgentState,
    ContextEnrichmentStatus,
    TestCaseGenerationStatus,
    WorkflowPhase,
    WorkflowRoute,
)


def test_workflow_phase_public_values_are_stable() -> None:
    assert [phase.value for phase in WorkflowPhase] == [
        "INITIAL",
        "PREPARED",
        "FINISHED",
        "REJECTED",
    ]


def test_workflow_route_public_values_are_stable() -> None:
    assert [route.value for route in WorkflowRoute] == ["READY", "BLOCKED"]


def test_testcase_generation_status_public_values_are_stable() -> None:
    assert [status.value for status in TestCaseGenerationStatus] == [
        "ACCEPTED",
        "VALIDATION_FAILURE",
        "GENERATION_FAILURE",
        "REPAIR_EXHAUSTED",
        "INTENTIONAL_INVALIDITY_PRESERVED",
    ]


def test_context_enrichment_status_public_values_are_stable() -> None:
    assert [status.value for status in ContextEnrichmentStatus] == [
        "READY",
        "DEGRADED",
        "FAILED",
    ]


def test_agent_state_has_only_the_expected_fields_and_hints() -> None:
    expected_fields = {
        "trace_id",
        "agent_run_id",
        "phase",
        "route",
        "error",
        "attempt_count",
        "max_attempts",
        "project_id",
        "api_id",
        "generation_intent",
        "api_metadata",
        "generation_context",
        "context_pack",
        "context_status",
        "context_error",
        "candidate",
        "validation_result",
        "repair_attempts",
        "max_repair_attempts",
        "generation_status",
    }

    assert set(APIOpsAgentState.__annotations__) == expected_fields

    hints = get_type_hints(APIOpsAgentState)
    assert set(hints) == expected_fields
    assert hints["trace_id"] == str | None
    assert hints["agent_run_id"] is str
    assert hints["phase"] is WorkflowPhase
    assert hints["route"] == WorkflowRoute | None
    assert hints["error"] == str | None
    assert hints["attempt_count"] is int
    assert hints["max_attempts"] is int
    assert hints["project_id"] is int
    assert hints["api_id"] is str
    assert hints["generation_intent"] is str
    assert hints["api_metadata"] == OpenApiMetadataDetail | None
    assert hints["generation_context"] == GenerationContext | None
    assert hints["context_pack"] == ContextPack | None
    assert hints["context_status"] == ContextEnrichmentStatus | None
    assert hints["context_error"] == str | None
    assert hints["candidate"] == Candidate | None
    assert hints["validation_result"] == CandidateValidationResult | None
    assert hints["repair_attempts"] is int
    assert hints["max_repair_attempts"] is int
    assert hints["generation_status"] == TestCaseGenerationStatus | None


def test_initial_state_can_be_constructed() -> None:
    state: APIOpsAgentState = {
        "trace_id": "trace-001",
        "phase": WorkflowPhase.INITIAL,
        "route": None,
        "error": None,
        "attempt_count": 0,
        "max_attempts": 2,
        "project_id": 101,
        "api_id": "api-orders",
        "generation_intent": "HAPPY_PATH",
        "api_metadata": None,
        "generation_context": None,
        "context_pack": None,
        "context_status": None,
        "context_error": None,
        "candidate": None,
        "validation_result": None,
        "repair_attempts": 0,
        "max_repair_attempts": 1,
        "generation_status": None,
    }

    assert state["trace_id"] == "trace-001"
    assert state["phase"] is WorkflowPhase.INITIAL
    assert state["route"] is None
    assert state["error"] is None


def test_ready_prepared_state_can_be_expressed() -> None:
    state: APIOpsAgentState = {
        "trace_id": "trace-002",
        "phase": WorkflowPhase.PREPARED,
        "route": WorkflowRoute.READY,
        "error": None,
        "attempt_count": 0,
        "max_attempts": 2,
        "project_id": 101,
        "api_id": "api-orders",
        "generation_intent": "HAPPY_PATH",
        "api_metadata": None,
        "generation_context": None,
        "context_pack": None,
        "context_status": None,
        "context_error": None,
        "candidate": None,
        "validation_result": None,
        "repair_attempts": 0,
        "max_repair_attempts": 1,
        "generation_status": None,
    }

    assert state == {
        "trace_id": "trace-002",
        "phase": WorkflowPhase.PREPARED,
        "route": WorkflowRoute.READY,
        "error": None,
        "attempt_count": 0,
        "max_attempts": 2,
        "project_id": 101,
        "api_id": "api-orders",
        "generation_intent": "HAPPY_PATH",
        "api_metadata": None,
        "generation_context": None,
        "context_pack": None,
        "context_status": None,
        "context_error": None,
        "candidate": None,
        "validation_result": None,
        "repair_attempts": 0,
        "max_repair_attempts": 1,
        "generation_status": None,
    }


def test_blocked_rejected_state_can_carry_controlled_error() -> None:
    state: APIOpsAgentState = {
        "trace_id": "trace-003",
        "phase": WorkflowPhase.REJECTED,
        "route": WorkflowRoute.BLOCKED,
        "error": "workflow precondition rejected",
        "attempt_count": 0,
        "max_attempts": 2,
        "project_id": 101,
        "api_id": "api-orders",
        "generation_intent": "HAPPY_PATH",
        "api_metadata": None,
        "generation_context": None,
        "context_pack": None,
        "context_status": None,
        "context_error": None,
        "candidate": None,
        "validation_result": None,
        "repair_attempts": 0,
        "max_repair_attempts": 1,
        "generation_status": None,
    }

    assert state["phase"] is WorkflowPhase.REJECTED
    assert state["route"] is WorkflowRoute.BLOCKED
    assert state["error"] == "workflow precondition rejected"
