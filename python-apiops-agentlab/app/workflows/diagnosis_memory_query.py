"""Deterministic query facts for Diagnosis Historical Memory."""

from __future__ import annotations

import json
import sqlite3

from app.memory import (
    HistoricalFailureMemoryEntry,
    MemoryLifecycleStatus,
    MemoryRetriever,
    VerificationStatus,
    build_failure_fingerprint,
)
from app.schemas.diagnosis_report import DiagnosisReport
from app.schemas.runner import TestReport


def build_memory_symptoms(report: TestReport) -> tuple[str, ...]:
    """Build the v1 failure-semantic atoms from one Java TestReport."""

    if not isinstance(report, TestReport):
        raise TypeError("report must be a TestReport")

    atoms = {
        f"run_status:{report.status}",
        f"summary_failure_type:{report.summary.failure_type}",
    }
    for case in report.cases:
        if not (case.status == "SUCCESS" and case.failure_type == "NONE"):
            atoms.add(f"case_failure_type:{case.failure_type}")
        for step in case.steps:
            failed_assertions = tuple(
                assertion for assertion in step.assertion_results if not assertion.passed
            )
            if step.status == "SUCCESS" and step.failure_type == "NONE" and not failed_assertions:
                continue
            atoms.add(f"step_failure_type:{step.failure_type}")
            if step.response_status_code is not None:
                atoms.add(f"response_status_code:{step.response_status_code}")
            atoms.update(f"assertion_type:{assertion.type}" for assertion in failed_assertions)
    return tuple(sorted(atoms))


def recall_historical_memory(
    *,
    project_id: int,
    api_id: str | None,
    report: TestReport,
    candidate: DiagnosisReport,
    retriever: MemoryRetriever,
) -> tuple[HistoricalFailureMemoryEntry, ...]:
    """Read only trusted, exact, ACTIVE memories for one candidate report."""

    if isinstance(project_id, bool) or not isinstance(project_id, int) or project_id < 1:
        raise ValueError("project_id must be a positive integer")
    if not isinstance(report, TestReport):
        raise TypeError("report must be a TestReport")
    if not isinstance(candidate, DiagnosisReport):
        raise TypeError("candidate must be a DiagnosisReport")
    if not isinstance(retriever, MemoryRetriever):
        raise TypeError("retriever must be a MemoryRetriever")
    if api_id is None or not isinstance(api_id, str) or not api_id.strip():
        return ()
    if candidate.project_id != project_id or report.project_id != project_id:
        return ()
    if candidate.run_id != report.run_id:
        return ()

    symptoms = build_memory_symptoms(report)
    expected_fingerprints = {
        build_failure_fingerprint(
            api_id=api_id,
            symptoms=symptoms,
            root_cause=hypothesis.statement,
        )
        for hypothesis in candidate.root_cause_hypotheses
    }
    memories: dict[str, HistoricalFailureMemoryEntry] = {}
    for hypothesis in candidate.root_cause_hypotheses:
        try:
            matches = retriever.retrieve_similar(
                project_id=project_id,
                api_id=api_id,
                symptoms=symptoms,
                root_cause=hypothesis.statement,
            )
        except (sqlite3.Error, json.JSONDecodeError, KeyError, IndexError, TypeError, ValueError):
            # Storage outages and strict row decoding failures are fail-closed;
            # unexpected exceptions must remain visible to the caller.
            return ()
        for memory in matches:
            if (
                not isinstance(memory, HistoricalFailureMemoryEntry)
                or memory.project_id != project_id
                or memory.lifecycle_status is not MemoryLifecycleStatus.ACTIVE
                or memory.verification_status is not VerificationStatus.VERIFIED
                or memory.failure_fingerprint not in expected_fingerprints
            ):
                return ()
            memories.setdefault(memory.memory_id, memory)
    return tuple(memories[memory_id] for memory_id in sorted(memories))


__all__ = ["build_memory_symptoms", "recall_historical_memory"]
