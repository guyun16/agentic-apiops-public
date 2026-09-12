"""Generalized pre-Formal105 diagnosis semantics with a deterministic model."""

from __future__ import annotations

import json

import pytest

from app.agents.diagnosis import DiagnosisSemanticContractError, validate_diagnosis_semantics
from app.rag.context import ContextItem, ContextPackBuilder, ContextPolicy, ContextSource
from app.schemas.diagnosis_report import DiagnosisReport
from app.schemas.runner import TestReport as RunnerTestReport
from app.tools import FakeToolGatewayAdapter, ToolCatalog, ToolRouter
from app.workflows.diagnosis_workflow import (
    build_diagnosis_workflow,
    diagnosis_initial_state,
)
from app.workflows.runtime_control import checkpoint_config


class SemanticFakeLLM:
    """Apply only the generalized rules present in the rendered prompt."""

    async def complete(self, prompt: str) -> str:
        required_rules = (
            "DiagnosisReport `failureType` is a separate Agent-authored semantic diagnosis",
            "Rank authority as: observed execution facts",
            "validated retrieval evidence",
            "model inference. Never override an observed fact",
            "An assertion mismatch proves only that actual differed from expected",
            "evidence is missing or conflicting",
            "known failure facts",
            "Empty hypotheses are allowed when no defensible hypothesis can be formed",
        )
        assert all(rule in prompt for rule in required_rules)
        context = json.loads(
            prompt.split("CONTEXT PACK\n", 1)[1].split("\n\nOUTPUT", 1)[0]
        )
        report_item = next(item for item in context if item["sourceType"] == "EXECUTION_FACT")
        report = json.loads(report_item["content"])
        evidence = " ".join(
            item["content"] for item in context if item["sourceType"] != "EXECUTION_FACT"
        ).lower()
        failure_type = report["summary"]["failureType"]
        statement: str | None = None
        sufficient = True

        if "conflicttype" in evidence or "conflict_type" in evidence:
            sufficient = False
        elif "inventory depleted" in evidence:
            statement = "The order was rejected by the observed inventory constraint."
        elif "duplicate idempotency" in evidence or "unique constraint" in evidence:
            statement = "The request violated the observed duplicate-key constraint."
        elif failure_type == "TIMEOUT":
            statement = "The execution deadline expired before an HTTP response was observed."
        elif failure_type == "DNS_ERROR":
            statement = "DNS resolution failed before an HTTP exchange began."
            sufficient = False
        elif failure_type == "CONNECT_ERROR":
            statement = "The connection failed before an HTTP response was observed."
        elif failure_type == "HTTP_STATUS_ERROR":
            statement = (
                "The execution observed an HTTP 5xx response; the underlying server or "
                "business cause remains unproven."
            )
            sufficient = False
        elif failure_type == "ASSERTION_MISMATCH":
            statement = (
                "The observed response differed from the expected assertion; the underlying "
                "cause remains unproven."
            )
            sufficient = False
        else:
            sufficient = False

        evidence_id = (
            next(
                item["itemId"]
                for item in context
                if item["sourceType"] != "EXECUTION_FACT"
                and any(
                    marker in item["content"].lower()
                    for marker in (
                        "inventory depleted",
                        "duplicate idempotency",
                        "unique constraint",
                    )
                )
            )
            if statement and ("constraint" in statement)
            else report_item["itemId"]
        )
        payload = {
            "schemaVersion": "0.1.0",
            "reportId": report["reportId"],
            "agentRunId": "agent-semantic",
            "projectId": report["projectId"],
            "runId": report["runId"],
            "failureType": failure_type,
            "summary": "The observed failure is classified separately from its cause.",
            "rootCauseHypotheses": (
                [
                    {
                        "statement": statement,
                        "confidence": "HIGH" if sufficient else "MEDIUM",
                        "evidenceRefs": [{"itemId": evidence_id}],
                    }
                ]
                if statement
                else []
            ),
            "sufficientEvidence": sufficient,
            "limitations": (
                []
                if sufficient
                else ["Bounded evidence does not establish a definitive root cause."]
            ),
            "recommendedChecks": ["Collect the missing project-authorized runtime evidence."],
            "traceId": "trace-semantic",
        }
        return json.dumps(payload)


def report(
    failure_type: str,
    *,
    status: str,
    response_status: int | None,
    assertion: bool = False,
) -> RunnerTestReport:
    return RunnerTestReport.model_validate(
        {
            "projectId": 41,
            "taskId": 301,
            "runId": 701,
            "reportId": f"report:{failure_type.lower()}",
            "status": status,
            "startedAt": "2026-08-31T00:00:00Z",
            "finishedAt": "2026-08-31T00:00:01Z",
            "summary": {
                "totalCases": 1,
                "totalSteps": 1,
                "totalAssertions": int(assertion),
                "passedAssertions": 0,
                "failedAssertions": int(assertion),
                "failureType": failure_type,
            },
            "cases": [
                {
                    "caseId": "case-generalized",
                    "status": status,
                    "failureType": failure_type,
                    "steps": [
                        {
                            "stepId": "step-generalized",
                            "status": status,
                            "failureType": failure_type,
                            "responseStatusCode": response_status,
                            "durationMs": 25,
                            "assertionResults": (
                                [
                                    {
                                        "type": "STATUS_CODE",
                                        "passed": False,
                                        "expected": 200,
                                        "actual": response_status,
                                        "message": "actual status differed from expected",
                                    }
                                ]
                                if assertion
                                else []
                            ),
                        }
                    ],
                }
            ],
        }
    )


async def diagnose(
    runtime_report: RunnerTestReport,
    evidence: str | None = None,
):
    supporting_context = (
        (
            ContextItem(
                source_type=ContextSource.SHORT_TERM_CONTEXT,
                source_id="runtime-evidence",
                project_scope=41,
                content=evidence,
                priority=90,
            ),
        )
        if evidence
        else ()
    )
    catalog = ToolCatalog()
    graph = build_diagnosis_workflow(
        SemanticFakeLLM(),
        ToolRouter(catalog, {"rag.search": FakeToolGatewayAdapter(None)}),
        project_id=41,
        catalog=catalog,
    )
    state = diagnosis_initial_state(
        runtime_report,
        trace_id="trace-semantic",
        agent_run_id="agent-semantic",
        workflow_id=f"workflow:{runtime_report.report_id}:{evidence or 'none'}",
        supporting_context=supporting_context,
    )
    result = await graph.ainvoke(
        state,
        config=checkpoint_config(state["workflow_id"]),
    )
    return result["diagnosis_report"]


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("family", "runtime_report", "evidence", "expected_sufficient", "root_marker"),
    [
        (
            "http-5xx",
            report("HTTP_STATUS_ERROR", status="EXECUTION_FAILED", response_status=500),
            None,
            False,
            "http 5xx",
        ),
        (
            "assertion-mismatch",
            report(
                "ASSERTION_MISMATCH",
                status="ASSERTION_FAILED",
                response_status=409,
                assertion=True,
            ),
            None,
            False,
            "observed response",
        ),
        (
            "transport-timeout",
            report("TIMEOUT", status="TIMEOUT", response_status=None),
            None,
            True,
            "deadline",
        ),
        (
            "dns-transport",
            report("DNS_ERROR", status="EXECUTION_FAILED", response_status=None),
            None,
            False,
            "dns",
        ),
        (
            "business-failure",
            report("BUSINESS_ERROR", status="EXECUTION_FAILED", response_status=409),
            "Validated response fact: inventory depleted for the requested quantity.",
            True,
            "inventory",
        ),
        (
            "duplicate-conflict",
            report(
                "DATABASE_CONSTRAINT_ERROR",
                status="EXECUTION_FAILED",
                response_status=409,
            ),
            "Validated response fact: unique constraint rejected duplicate idempotency key.",
            True,
            "duplicate-key",
        ),
        (
            "insufficient-evidence",
            report("UNKNOWN", status="EXECUTION_FAILED", response_status=None),
            "missingEvidence: response body and server trace",
            False,
            None,
        ),
        (
            "conflicting-evidence",
            report("HTTP_STATUS_ERROR", status="EXECUTION_FAILED", response_status=500),
            '{"conflictType":"MULTIPLE_PLAUSIBLE_ROOTS",'
            '"detail":"gateway says upstream; service says local validation"}',
            False,
            None,
        ),
    ],
)
async def test_generalized_diagnosis_families_preserve_semantic_boundaries(
    family: str,
    runtime_report: RunnerTestReport,
    evidence: str | None,
    expected_sufficient: bool,
    root_marker: str | None,
) -> None:
    diagnosis = await diagnose(runtime_report, evidence)

    assert diagnosis.failure_type == runtime_report.summary.failure_type, family
    assert diagnosis.sufficient_evidence is expected_sufficient, family
    assert bool(diagnosis.limitations) is (not expected_sufficient), family
    allowed_refs = {runtime_report.report_id, "runtime-evidence"}
    assert all(
        reference.item_id in allowed_refs
        for hypothesis in diagnosis.root_cause_hypotheses
        for reference in hypothesis.evidence_refs
    ), family
    if root_marker is None:
        assert not diagnosis.root_cause_hypotheses, family
    else:
        assert root_marker in diagnosis.root_cause_hypotheses[0].statement.lower(), family


@pytest.mark.anyio
async def test_semantic_diagnosis_may_differ_from_observed_runner_failure_type() -> None:
    runtime_report = report(
        "NONE",
        status="SUCCESS",
        response_status=409,
    )
    context = (
        ContextItem(
            source_type=ContextSource.EXECUTION_FACT,
            source_id=runtime_report.report_id,
            project_scope=41,
            content="authoritative Java response status 409",
            priority=100,
        ),
    )
    candidate = {
        "schemaVersion": "0.1.0",
        "reportId": runtime_report.report_id,
        "agentRunId": "agent-semantic",
        "projectId": 41,
        "runId": 701,
        "failureType": "BUSINESS_ERROR",
        "summary": "The successful Runner execution observed a business-error response.",
        "rootCauseHypotheses": [],
        "sufficientEvidence": False,
        "limitations": ["The response body is unavailable."],
        "recommendedChecks": ["Inspect the authorized response body."],
        "traceId": "trace-semantic",
    }

    pack = ContextPackBuilder(
        ContextPolicy(source_precedence=tuple(ContextSource)),
        project_scope=41,
    ).build(context)
    diagnosis = DiagnosisReport.model_validate(candidate)

    validate_diagnosis_semantics(diagnosis, report=runtime_report, context_pack=pack)
    assert diagnosis.failure_type == "BUSINESS_ERROR"
    assert diagnosis.semantic_diagnosis == "BUSINESS_ERROR"
    assert runtime_report.summary.failure_type == "NONE"


def test_error_http_response_rejects_semantic_none() -> None:
    runtime_report = report(
        "NONE",
        status="SUCCESS",
        response_status=500,
    )
    context = (
        ContextItem(
            source_type=ContextSource.EXECUTION_FACT,
            source_id=runtime_report.report_id,
            project_scope=41,
            content="authoritative Java response status 500",
            priority=100,
        ),
    )
    pack = ContextPackBuilder(
        ContextPolicy(source_precedence=tuple(ContextSource)),
        project_scope=41,
    ).build(context)
    diagnosis = DiagnosisReport.model_validate(
        {
            "schemaVersion": "0.1.0",
            "reportId": runtime_report.report_id,
            "agentRunId": "agent-semantic",
            "projectId": 41,
            "runId": 701,
            "failureType": "NONE",
            "summary": "No failure was observed.",
            "rootCauseHypotheses": [],
            "sufficientEvidence": False,
            "limitations": ["The response body is unavailable."],
            "recommendedChecks": ["Inspect the authorized response body."],
            "traceId": "trace-semantic",
        }
    )

    with pytest.raises(DiagnosisSemanticContractError, match="cannot have semantic diagnosis NONE"):
        validate_diagnosis_semantics(diagnosis, report=runtime_report, context_pack=pack)


@pytest.mark.anyio
async def test_same_failure_type_with_different_evidence_changes_hypothesis() -> None:
    runtime_report = report(
        "ASSERTION_MISMATCH",
        status="ASSERTION_FAILED",
        response_status=409,
        assertion=True,
    )

    inventory = await diagnose(runtime_report, "Validated response fact: inventory depleted.")
    duplicate = await diagnose(
        runtime_report,
        "Validated response fact: duplicate idempotency key violated a unique constraint.",
    )

    assert inventory.root_cause_hypotheses[0].statement != (
        duplicate.root_cause_hypotheses[0].statement
    )
    assert inventory.root_cause_hypotheses[0].evidence_refs[0].item_id == "runtime-evidence"
    assert duplicate.root_cause_hypotheses[0].evidence_refs[0].item_id == "runtime-evidence"


class EmptyDiagnosisLLM:
    async def complete(self, prompt: str) -> str:
        context = json.loads(
            prompt.split("CONTEXT PACK\n", 1)[1].split("\n\nOUTPUT", 1)[0]
        )
        report = json.loads(
            next(item["content"] for item in context if item["sourceType"] == "EXECUTION_FACT")
        )
        return json.dumps(
            {
                "schemaVersion": "0.1.0",
                "reportId": report["reportId"],
                "agentRunId": "agent-semantic",
                "projectId": report["projectId"],
                "runId": report["runId"],
                "failureType": report["summary"]["failureType"],
                "summary": "The report contains a known terminal failure.",
                "rootCauseHypotheses": [],
                "sufficientEvidence": False,
                "limitations": ["The model omitted a provisional hypothesis."],
                "recommendedChecks": ["Collect additional authorized evidence."],
                "traceId": "trace-semantic",
            }
        )


@pytest.mark.anyio
async def test_known_terminal_failure_can_abstain_without_erasing_observations() -> None:
    runtime_report = report("DNS_ERROR", status="EXECUTION_FAILED", response_status=None)
    catalog = ToolCatalog()
    graph = build_diagnosis_workflow(
        EmptyDiagnosisLLM(),
        ToolRouter(catalog, {"rag.search": FakeToolGatewayAdapter(None)}),
        project_id=41,
        catalog=catalog,
    )
    state = diagnosis_initial_state(
        runtime_report,
        trace_id="trace-semantic",
        agent_run_id="agent-semantic",
        workflow_id="workflow:semantic-empty-known",
    )

    result = await graph.ainvoke(state, config=checkpoint_config(state["workflow_id"]))
    diagnosis = result["diagnosis_report"]
    assert diagnosis.sufficient_evidence is False
    assert diagnosis.root_cause_hypotheses == []
    assert diagnosis.failure_type == "DNS_ERROR"
    assert diagnosis.limitations and diagnosis.recommended_checks
