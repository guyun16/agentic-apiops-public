"""Minimal typed state boundary for future Python workflow orchestration."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .state import APIOpsAgentState, TestCaseGenerationStatus, WorkflowPhase, WorkflowRoute
    from .tool_planning import (
        EvidenceSufficiency,
        ToolPlanningDecision,
        ToolPlanningError,
        ToolRequirement,
        assess_evidence_sufficiency,
        build_rag_tool_intent,
        build_tool_decision,
        build_tool_intent,
        decide_tool_requirement,
    )

__all__ = [
    "APIOpsAgentState",
    "DiagnosisWorkflowState",
    "GeneratedTestCaseNotValidatedError",
    "PreparedRunnerExecutionResult",
    "MAX_TOOL_CALLS",
    "RunnerReadbackPolicy",
    "Stage20ExecutionError",
    "Stage20ExecutionResult",
    "Stage20ExecutionWorkflow",
    "TestCaseGenerationStatus",
    "WorkflowPhase",
    "WorkflowRoute",
    "build_diagnosis_workflow",
    "EvidenceSufficiency",
    "ToolPlanningDecision",
    "ToolPlanningError",
    "ToolRequirement",
    "assess_evidence_sufficiency",
    "build_rag_tool_intent",
    "build_tool_decision",
    "build_tool_intent",
    "decide_tool_requirement",
    "diagnosis_initial_state",
    "test_report_context_item",
]
_STATE_EXPORTS = {
    "APIOpsAgentState",
    "TestCaseGenerationStatus",
    "WorkflowPhase",
    "WorkflowRoute",
}
_STAGE20_EXPORTS = {
    "GeneratedTestCaseNotValidatedError",
    "PreparedRunnerExecutionResult",
    "RunnerReadbackPolicy",
    "Stage20ExecutionError",
    "Stage20ExecutionResult",
    "Stage20ExecutionWorkflow",
}
_DIAGNOSIS_EXPORTS = {
    "DiagnosisWorkflowState",
    "MAX_TOOL_CALLS",
    "build_diagnosis_workflow",
    "diagnosis_initial_state",
    "test_report_context_item",
}
_PLANNING_EXPORTS = {
    "EvidenceSufficiency",
    "ToolPlanningDecision",
    "ToolPlanningError",
    "ToolRequirement",
    "assess_evidence_sufficiency",
    "build_rag_tool_intent",
    "build_tool_decision",
    "build_tool_intent",
    "decide_tool_requirement",
}


def __getattr__(name: str):
    if name in _STATE_EXPORTS:
        from . import state

        return getattr(state, name)
    if name in _STAGE20_EXPORTS:
        from . import stage20_execution

        return getattr(stage20_execution, name)
    if name in _DIAGNOSIS_EXPORTS:
        from . import diagnosis_workflow

        return getattr(diagnosis_workflow, name)
    if name in _PLANNING_EXPORTS:
        from . import tool_planning

        return getattr(tool_planning, name)
    raise AttributeError(name)
