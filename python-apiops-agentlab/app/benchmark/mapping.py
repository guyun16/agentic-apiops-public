"""Stage 21 mapping into the existing Stage 19 evaluation boundary."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Any

from app.evaluator import (
    EvaluationCase,
    EvaluationFacts,
    ExpectedToolArguments,
    GroundTruth,
    ModelPricing,
)

from .models import BenchmarkTask, ExpectedToolCallSpec


class BenchmarkMappingError(ValueError):
    """The task, Ground Truth, or runtime identity cannot be mapped safely."""


class GroundTruthNotFoundError(BenchmarkMappingError):
    """No GroundTruth with the task's referenced ID exists."""


class GroundTruthVersionMismatchError(BenchmarkMappingError):
    """The referenced GroundTruth ID exists, but not at the requested version."""


class GroundTruthIdentityMismatchError(BenchmarkMappingError):
    """A supplied GroundTruth does not match the task reference."""


CURRENT_JAVA_REPORT = "CURRENT_JAVA_REPORT"


def project_current_java_report(
    ground_truth: GroundTruth,
    *,
    report_id: str | None,
) -> GroundTruth:
    """Bind the logical current-report token at the evaluation boundary only.

    The token is intentionally resolved after Java execution.  It is never
    available to task routing, tool authorization, RAG retrieval, or the
    evaluated candidate.  When a deterministic/no-Java execution has no report
    identity, keep the token unresolved so the evaluator can record UNKNOWN.
    A supplied non-authoritative identity still fails closed instead of
    silently converting a report expectation into a fixture.
    """

    if not _contains_current_java_report(ground_truth):
        return ground_truth
    if report_id is None:
        return ground_truth
    if (
        not isinstance(report_id, str)
        or not report_id.strip()
        or report_id == CURRENT_JAVA_REPORT
        or report_id.startswith("fixture:")
    ):
        raise BenchmarkMappingError(
            "CURRENT_JAVA_REPORT requires a non-fixture Java report identity"
        )
    return ground_truth.model_copy(
        update={
            "expected_evidence_ids": tuple(
                _replace_current_java_report(value, report_id)
                for value in ground_truth.expected_evidence_ids
            )
            if ground_truth.expected_evidence_ids is not None
            else None,
            "expected_facts": tuple(
                fact.model_copy(
                    update={"value": _replace_current_java_report(fact.value, report_id)}
                )
                for fact in ground_truth.expected_facts
            ),
        }
    )


def _contains_current_java_report(ground_truth: GroundTruth) -> bool:
    return any(
        _contains_token(value, CURRENT_JAVA_REPORT)
        for value in (
            ground_truth.expected_evidence_ids,
            tuple(fact.value for fact in ground_truth.expected_facts),
        )
    )


def _contains_token(value: Any, token: str) -> bool:
    if value == token:
        return True
    if isinstance(value, dict):
        return any(_contains_token(item, token) for item in value.values())
    if isinstance(value, (list, tuple)):
        return any(_contains_token(item, token) for item in value)
    return False


def _replace_current_java_report(value: Any, report_id: str) -> Any:
    if value == CURRENT_JAVA_REPORT:
        return report_id
    if isinstance(value, dict):
        return {key: _replace_current_java_report(item, report_id) for key, item in value.items()}
    if isinstance(value, list):
        return [_replace_current_java_report(item, report_id) for item in value]
    if isinstance(value, tuple):
        return tuple(_replace_current_java_report(item, report_id) for item in value)
    return value


def expected_tool_arguments_for_task(
    task: BenchmarkTask,
) -> tuple[ExpectedToolArguments, ...]:
    """Translate task syntax to the Stage 19 comparison model without new semantics."""

    return tuple(_expected_arguments(call) for call in task.expected_tool_calls)


def _expected_arguments(call: ExpectedToolCallSpec) -> ExpectedToolArguments:
    if call.match_policy is None:
        raise BenchmarkMappingError(f"expected tool {call.tool_name!r} has no matchPolicy")
    return ExpectedToolArguments(
        tool_name=call.tool_name,
        arguments=call.params_contains,
        match_policy=call.match_policy,
        optional_fields=call.optional_fields,
        case_insensitive_fields=call.case_insensitive_fields,
        trim_fields=call.trim_fields,
        order_insensitive_fields=call.order_insensitive_fields,
    )


def validate_task_ground_truth_alignment(
    task: BenchmarkTask,
    ground_truth: GroundTruth,
) -> GroundTruth:
    """Check identity and expected-tool mapping before creating an EvaluationCase."""

    reference = task.ground_truth_ref
    if ground_truth.ground_truth_id != reference.ground_truth_id:
        raise GroundTruthIdentityMismatchError(
            "GroundTruth ID does not match EvaluationTask.groundTruthRef"
        )
    if ground_truth.version != reference.version:
        raise GroundTruthVersionMismatchError(
            "GroundTruth version does not match EvaluationTask.groundTruthRef"
        )

    expected_arguments = expected_tool_arguments_for_task(task)
    if not expected_arguments:
        return ground_truth

    task_tools = {item.tool_name for item in expected_arguments}
    if set(ground_truth.expected_tools) != task_tools:
        raise BenchmarkMappingError(
            "EvaluationTask expectedToolCalls and GroundTruth expected_tools differ"
        )
    truth_arguments = {item.tool_name: item for item in ground_truth.expected_tool_arguments}
    for expected in expected_arguments:
        actual = truth_arguments.get(expected.tool_name)
        if actual != expected:
            raise BenchmarkMappingError(
                f"GroundTruth expected arguments do not match task tool {expected.tool_name!r}"
            )
    return ground_truth


def resolve_ground_truth(
    task: BenchmarkTask,
    ground_truths: Iterable[GroundTruth],
) -> GroundTruth:
    """Resolve the exact referenced GroundTruth version from an independent registry."""

    candidates = tuple(ground_truths)
    reference = task.ground_truth_ref
    if not any(item.ground_truth_id == reference.ground_truth_id for item in candidates):
        raise GroundTruthNotFoundError(
            f"GroundTruth ID {reference.ground_truth_id!r} was not found"
        )
    match = next(
        (
            item
            for item in candidates
            if item.ground_truth_id == reference.ground_truth_id
            and item.version == reference.version
        ),
        None,
    )
    if match is None:
        raise GroundTruthVersionMismatchError(
            f"GroundTruth {reference.ground_truth_id!r} has no version {reference.version!r}"
        )
    return validate_task_ground_truth_alignment(task, match)


def to_evaluation_case(
    task: BenchmarkTask,
    ground_truth: GroundTruth,
    *,
    case_id: str,
    trace_id: str,
    agent_run_id: str,
    facts: EvaluationFacts | None = None,
    pricing: Sequence[ModelPricing] = (),
) -> EvaluationCase:
    """Build the existing Stage 19 EvaluationCase from explicit runtime facts."""

    validate_task_ground_truth_alignment(task, ground_truth)
    if case_id == task.benchmark_task_id or agent_run_id == task.benchmark_task_id:
        raise BenchmarkMappingError(
            "benchmarkTaskId is static task identity, not case_id or agent_run_id"
        )
    return EvaluationCase(
        case_id=case_id,
        trace_id=trace_id,
        agent_run_id=agent_run_id,
        ground_truth_id=ground_truth.ground_truth_id,
        ground_truth_version=ground_truth.version,
        facts=facts or EvaluationFacts(),
        applicable_metrics=task.evaluation_spec.selected_metrics,
        pricing=tuple(pricing),
    )


__all__ = [
    "BenchmarkMappingError",
    "CURRENT_JAVA_REPORT",
    "GroundTruthIdentityMismatchError",
    "GroundTruthNotFoundError",
    "GroundTruthVersionMismatchError",
    "expected_tool_arguments_for_task",
    "project_current_java_report",
    "resolve_ground_truth",
    "to_evaluation_case",
    "validate_task_ground_truth_alignment",
]
