from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.agents.testcase_generator import Candidate
from app.benchmark import (
    assemble_outcome_facts,
    merge_evaluation_facts,
    project_diagnosis_facts,
    project_generation_facts,
    project_rag_facts,
    project_runner_facts,
    project_safety_facts,
)
from app.evaluator import EvaluationFacts, SafetyOutcome, StructuredFact, ValidityFacts
from app.guardrails.violations import EvidenceSource, ViolationCode
from app.schemas.diagnosis_report import DiagnosisReport
from app.schemas.openapi_metadata import OpenApiMetadataDetail
from app.schemas.runner import TestReport as RunnerTestReport
from app.tracing import (
    ApprovalFact,
    EvidenceReference,
    RetrievalFact,
    RetrievalReference,
    SafetyViolationFact,
    ToolPlanningRecord,
    ToolResultRecord,
    TraceEvent,
    TraceStatus,
    failure_detail,
)
from app.workflows.approval import ApprovalAction
from app.workflows.candidate_validation import CandidateValidationResult, validate_candidate
from app.workflows.generation_context import TestStrategy, build_generation_context
from app.workflows.tool_planning import EvidenceSufficiency, ToolRequirement

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]


@pytest.mark.parametrize(
    "variant",
    [
        "exact",
        "const",
        "conflicting_const",
        "wrong_code",
        "no_enum",
        "untrusted",
        "wrong_path",
        "wrong_status",
        "split_step",
    ],
)
def test_candidate_code_requires_same_step_independent_java_schema(variant: str) -> None:
    metadata = _metadata()
    raw = metadata.model_dump(mode="json", by_alias=True)
    raw["responseSchemas"] = [
        {
            "statusCode": "409",
            "description": "Documented business response",
            "mediaType": "application/json",
            "schema": {
                "type": "object",
                "properties": {"code": {"type": "string", "enum": ["ORDER_BUSINESS_CONFLICT"]}},
            },
        }
    ]
    if variant == "no_enum":
        raw["responseSchemas"][0]["schema"]["properties"]["code"].pop("enum")
    if variant in {"const", "conflicting_const"}:
        raw["responseSchemas"][0]["schema"]["properties"]["code"]["const"] = (
            "ORDER_BUSINESS_CONFLICT" if variant == "const" else "OTHER_CODE"
        )
    metadata = OpenApiMetadataDetail.model_validate(raw)
    observed = "LEGACY_WRONG_CODE" if variant == "wrong_code" else "ORDER_BUSINESS_CONFLICT"
    step = {
        "stepId": "bound-step",
        "request": {"method": metadata.method, "path": metadata.path},
        "assertions": [
            {"type": "STATUS_CODE", "expected": 409},
            {
                "type": "JSON_PATH",
                "expression": "$.code",
                "operator": "EQUALS",
                "expected": observed,
            },
        ],
    }
    structured = {"apiId": metadata.api_id, "steps": [step]}
    if variant == "wrong_path":
        step["request"]["path"] = "/another-operation"
    if variant == "wrong_status":
        step["assertions"][0]["expected"] = 401
    if variant == "split_step":
        structured["steps"].append(
            {
                "stepId": "other-step",
                "request": {"method": "GET", "path": "/other"},
                "assertions": [step["assertions"].pop()],
            }
        )
    candidate = Candidate(raw=json.dumps(structured), structured=structured)
    facts = _fact_map(
        project_generation_facts(
            candidate,
            None,
            TestStrategy.BUSINESS_ERROR,
            metadata=metadata,
            metadata_authority="PYTHON_FIXTURE"
            if variant == "untrusted"
            else "JAVA_OPENAPI_BASELINE",
        )
    )
    assert facts["business_error"] == observed
    if variant in {"exact", "const", "wrong_code"}:
        assert facts["response_code_contract_values"] == ["ORDER_BUSINESS_CONFLICT"]
        assert facts["response_code_contract_match"] is (variant != "wrong_code")
    else:
        assert "response_code_contract_authority" not in facts


def _candidate(relative_path: str) -> Candidate:
    path = REPOSITORY_ROOT / relative_path
    raw = path.read_text(encoding="utf-8")
    return Candidate(raw=raw, structured=json.loads(raw))


def _candidate_with_quantity(value: object) -> Candidate:
    candidate = _candidate("examples/testcase-valid.json")
    structured = json.loads(candidate.raw)
    structured["steps"][0]["request"]["body"]["quantity"] = value
    return Candidate(raw=json.dumps(structured), structured=structured)


def _metadata_with_parameter_schema(schema: dict[str, object]) -> OpenApiMetadataDetail:
    return OpenApiMetadataDetail.model_validate(
        {
            "apiId": "api-stage21-boundary",
            "apiDocId": "doc-stage21-boundary",
            "operationId": "boundaryOperation",
            "method": "POST",
            "path": "/boundary",
            "summary": "Boundary operation",
            "description": "A deterministic boundary test operation.",
            "tags": ["boundary"],
            "servers": [{"url": "http://localhost"}],
            "security": None,
            "deprecated": False,
            "parameters": [
                {
                    "name": "quantity",
                    "location": "query",
                    "required": True,
                    "description": "Boundary value.",
                    "schema": schema,
                    "example": 1,
                }
            ],
            "requestSchemas": [],
            "responseSchemas": [],
            "examples": [],
        }
    )


def _metadata() -> OpenApiMetadataDetail:
    path = (
        REPOSITORY_ROOT
        / "python-apiops-agentlab/tests/benchmark/fixtures/support/generation-openapi-metadata.json"
    )
    return OpenApiMetadataDetail.model_validate_json(path.read_text(encoding="utf-8"))


def _metadata_with_nested_items() -> OpenApiMetadataDetail:
    raw = json.loads(
        (
            REPOSITORY_ROOT
            / "python-apiops-agentlab/tests/benchmark/fixtures/support/"
            / "generation-openapi-metadata.json"
        ).read_text(encoding="utf-8")
    )
    raw["parameters"] = []
    raw["requestSchemas"][0]["schema"] = {
        "type": "object",
        "properties": {
            "items": {
                "type": "array",
                "minItems": 1,
                "items": {
                    "type": "object",
                    "properties": {
                        "quantity": {"type": "integer", "minimum": 1},
                    },
                },
            }
        },
    }
    return OpenApiMetadataDetail.model_validate(raw)


def _fact_map(facts: object) -> dict[str, object]:
    return {fact.name: fact.value for fact in facts.structured_facts}  # type: ignore[attr-defined]


def _tool_result(
    *,
    status: str = "SUCCESS",
    trace_status: TraceStatus = TraceStatus.SUCCESS,
) -> ToolResultRecord:
    return ToolResultRecord(
        trace_id="trace:projection",
        agent_run_id="agent_run:projection",
        agent_step_id="step:projection",
        project_id=41,
        event=TraceEvent.RESULT,
        status=trace_status,
        failure=(
            failure_detail("JAVA_TOOL_FAILURE", "bounded failure", code=status)
            if trace_status is not TraceStatus.SUCCESS
            else None
        ),
        tool_name="rag.search",
        java_tool_call_id="java-tool-call:projection",
        tool_result_status=status,
        has_data=status == "SUCCESS",
        result_summary="bounded result",
        sanitized=True,
        truncated=False,
    )


def _retrieval(
    *,
    result_count: int,
    project_id: int | None = 41,
    source_id: str = "rag:orders-constraint-001",
) -> RetrievalFact:
    references = (
        (
            EvidenceReference(
                source_type="RAG_CHUNK",
                source_id=source_id,
                project_id=project_id,
                document_id="doc:orders",
                chunk_id="chunk:orders-1",
                location="orders.md#constraint",
            ),
        )
        if result_count
        else ()
    )
    return RetrievalFact(
        trace_id="trace:projection",
        agent_run_id="agent_run:projection",
        agent_step_id="step:projection",
        project_id=project_id,
        event=TraceEvent.FACT,
        status=TraceStatus.SUCCESS,
        retrieval_kind="JAVA_RAG_TOOL_RESULT",
        reference=RetrievalReference(
            rag_query_id="rag-query:projection",
            evidence_references=references,
        ),
        result_count=result_count,
    )


def _report_retrieval() -> RetrievalFact:
    return RetrievalFact(
        trace_id="trace:projection",
        agent_run_id="agent_run:projection",
        agent_step_id="step:projection",
        event=TraceEvent.FACT,
        status=TraceStatus.SUCCESS,
        retrieval_kind="JAVA_TEST_REPORT",
        reference=RetrievalReference(
            report_id="report:projection",
            run_id=8001,
        ),
        result_count=1,
    )


def _report() -> RunnerTestReport:
    return RunnerTestReport.model_validate(
        {
            "projectId": 41,
            "taskId": 7001,
            "runId": 8001,
            "reportId": "report:projection",
            "status": "ASSERTION_FAILED",
            "startedAt": "2026-08-31T00:00:00Z",
            "finishedAt": "2026-08-31T00:00:01Z",
            "summary": {
                "totalCases": 1,
                "totalSteps": 1,
                "totalAssertions": 2,
                "passedAssertions": 1,
                "failedAssertions": 1,
                "failureType": "BUSINESS_ERROR",
            },
            "cases": [
                {
                    "caseId": "case:projection",
                    "status": "ASSERTION_FAILED",
                    "failureType": "BUSINESS_ERROR",
                    "steps": [
                        {
                            "stepId": "step:projection",
                            "status": "ASSERTION_FAILED",
                            "failureType": "BUSINESS_ERROR",
                            "responseStatusCode": 409,
                            "durationMs": 10,
                            "assertionResults": [
                                {
                                    "type": "STATUS_CODE",
                                    "passed": True,
                                    "expected": 409,
                                    "actual": 409,
                                    "message": "status observed",
                                },
                                {
                                    "type": "JSON_PATH",
                                    "passed": False,
                                    "expected": "INVENTORY_NOT_ENOUGH",
                                    "actual": "INVENTORY_NOT_ENOUGH",
                                    "message": "business response observed",
                                },
                            ],
                        }
                    ],
                }
            ],
        }
    )


def test_runner_json_path_actual_without_expression_does_not_become_semantic_fact() -> None:
    facts = project_runner_facts(_report(), java_authority=True)
    projected = _fact_map(facts)

    assert projected["response_status"] == 409
    assert "response_code" not in projected
    assert "business_error" not in projected
    assert "business_outcome" not in projected
    assert "java_runner_business_outcome" not in projected


def test_runner_passed_response_code_is_java_business_outcome_authority() -> None:
    raw = _report().model_dump(mode="json")
    raw["cases"][0]["steps"][0]["assertionResults"][1]["passed"] = True
    report = RunnerTestReport.model_validate(raw)

    candidate = _report_candidate()
    facts = project_runner_facts(report, java_authority=True, candidate=candidate)
    projected = _fact_map(facts)

    assert projected["business_outcome"] == "INVENTORY_NOT_ENOUGH"
    assert projected["java_runner_business_outcome"] == "INVENTORY_NOT_ENOUGH"


def _report_candidate() -> dict[str, object]:
    return {
        "steps": [
            {
                "stepId": "step:projection",
                "request": {"method": "POST", "path": "/orders"},
                "assertions": [
                    {"type": "STATUS_CODE", "expected": 409},
                    {
                        "type": "JSON_PATH",
                        "expression": "$.code",
                        "operator": "EQUALS",
                        "expected": "INVENTORY_NOT_ENOUGH",
                    },
                ],
            }
        ],
    }


@pytest.mark.parametrize(
    "broken",
    [
        "missing_candidate",
        "wrong_field",
        "wrong_step",
        "wrong_index",
        "wrong_expected",
        "failed",
        "actual_mismatch",
        "wrong_operator",
    ],
)
def test_runner_business_code_requires_exact_candidate_assertion_binding(broken: str) -> None:
    raw = _report().model_dump(mode="json")
    raw["cases"][0]["steps"][0]["assertionResults"][1]["passed"] = True
    candidate = _report_candidate()
    assertion = candidate["steps"][0]["assertions"][1]
    if broken == "missing_candidate":
        candidate = None
    elif broken == "wrong_field":
        assertion["expression"] = "$.data.state"
    elif broken == "wrong_step":
        candidate["steps"][0]["stepId"] = "step:unrelated"
    elif broken == "wrong_index":
        candidate["steps"][0]["assertions"].reverse()
    elif broken == "wrong_expected":
        assertion["expected"] = "DIFFERENT_CODE"
    elif broken == "failed":
        raw["cases"][0]["steps"][0]["assertionResults"][1]["passed"] = False
    elif broken == "actual_mismatch":
        raw["cases"][0]["steps"][0]["assertionResults"][1]["actual"] = "DIFFERENT_CODE"
    else:
        assertion["operator"] = "CONTAINS"

    projected = _fact_map(
        project_runner_facts(
            RunnerTestReport.model_validate(raw),
            java_authority=True,
            candidate=candidate,
        )
    )

    assert "business_outcome" not in projected
    assert "java_runner_business_outcome" not in projected


def test_assembler_does_not_infer_business_code_from_status_contract() -> None:
    raw = _report().model_dump(mode="json")
    raw["status"] = "SUCCESS"
    raw["summary"].update(
        {
            "totalAssertions": 1,
            "passedAssertions": 1,
            "failedAssertions": 0,
            "failureType": "NONE",
        }
    )
    raw["cases"][0]["status"] = "SUCCESS"
    raw["cases"][0]["failureType"] = "NONE"
    raw["cases"][0]["steps"][0]["status"] = "SUCCESS"
    raw["cases"][0]["steps"][0]["failureType"] = "NONE"
    raw["cases"][0]["steps"][0]["assertionResults"] = [
        raw["cases"][0]["steps"][0]["assertionResults"][0]
    ]
    report = RunnerTestReport.model_validate(raw)
    base = EvaluationFacts(
        validity=ValidityFacts(contract_accepted=True),
        structured_facts=(
            StructuredFact(name="task_strategy", value="DOCUMENTED_BUSINESS_ERROR"),
            StructuredFact(name="metadata_authority", value="JAVA_OPENAPI_BASELINE"),
            StructuredFact(name="operation", value="createOrder"),
            StructuredFact(name="expected_http_status", value=409),
        ),
    )

    projected = _fact_map(
        assemble_outcome_facts(
            base=base,
            report=report,
            report_java_authority=True,
        )
    )

    assert "business_outcome" not in projected
    assert "java_runner_business_outcome" not in projected

    untrusted = _fact_map(
        assemble_outcome_facts(
            base=base,
            report=report,
            report_java_authority=False,
        )
    )
    assert "business_outcome" not in untrusted


def test_assembler_does_not_infer_success_code_from_success_status() -> None:
    raw = _report().model_dump(mode="json")
    raw["status"] = "SUCCESS"
    raw["summary"].update(
        {
            "totalAssertions": 1,
            "passedAssertions": 1,
            "failedAssertions": 0,
            "failureType": "NONE",
        }
    )
    raw["cases"][0]["status"] = "SUCCESS"
    raw["cases"][0]["failureType"] = "NONE"
    raw["cases"][0]["steps"][0].update(
        {
            "status": "SUCCESS",
            "failureType": "NONE",
            "responseStatusCode": 200,
            "assertionResults": [
                {
                    "type": "STATUS_CODE",
                    "passed": True,
                    "expected": 200,
                    "actual": 200,
                    "message": "status observed",
                }
            ],
        }
    )
    base = EvaluationFacts(
        validity=ValidityFacts(contract_accepted=True),
        structured_facts=(
            StructuredFact(name="task_strategy", value="HAPPY_PATH"),
            StructuredFact(name="metadata_authority", value="JAVA_OPENAPI_BASELINE"),
            StructuredFact(name="operation", value="createOrder"),
            StructuredFact(name="expected_http_status", value=200),
        ),
    )

    projected = _fact_map(
        assemble_outcome_facts(
            base=base,
            report=RunnerTestReport.model_validate(raw),
            report_java_authority=True,
        )
    )

    assert "business_outcome" not in projected
    assert "java_runner_business_outcome" not in projected


def test_generation_projects_documented_business_response_semantics_without_code_guess() -> None:
    metadata = _metadata()
    context = build_generation_context(metadata, TestStrategy.BUSINESS_ERROR)
    structured = {
        "schemaVersion": "1.0.0",
        "caseId": "documented-business-409",
        "projectId": 41,
        "apiId": metadata.api_id,
        "name": "Documented business conflict",
        "environment": {"baseUrl": "http://localhost", "variables": {}},
        "steps": [
            {
                "stepId": "step-business-409",
                "name": "Create order with unavailable inventory",
                "request": {
                    "method": "POST",
                    "path": "/orders",
                    "query": {"quantity": 100},
                    "body": {"productId": "unavailable", "quantity": 100},
                },
                "assertions": [{"type": "STATUS_CODE", "expected": 409}],
                "extractors": [],
            }
        ],
    }
    candidate = Candidate(raw=json.dumps(structured), structured=structured)
    validation = validate_candidate(candidate, project_id=41, generation_context=context)

    projected = _fact_map(
        project_generation_facts(
            candidate,
            validation,
            TestStrategy.BUSINESS_ERROR,
            metadata=metadata,
            generation_context=context,
            metadata_authority="JAVA_OPENAPI_BASELINE",
        )
    )

    assert validation.valid is True
    assert projected["success_expected"] is False
    assert projected["failure_boundary"] == "BUSINESS_RESPONSE"
    assert "business_error" not in projected


def test_generation_projects_unknown_assertion_discriminator_from_validator() -> None:
    metadata = _metadata()
    context = build_generation_context(metadata, TestStrategy.BOUNDARY)
    candidate = _candidate("examples/invalid/testcase-unknown-assertion.json")
    validation = validate_candidate(candidate, project_id=1001, generation_context=context)

    projected = _fact_map(
        project_generation_facts(
            candidate,
            validation,
            TestStrategy.BOUNDARY,
            metadata=metadata,
            generation_context=context,
        )
    )

    assert validation.valid is False
    assert projected["invalid_field"] == "assertion.type"
    assert projected["invalid_value"] == "BODY_CONTAINS"


def test_generation_projection_keeps_validator_authority_for_missing_field() -> None:
    metadata = _metadata()
    context = build_generation_context(metadata, TestStrategy.HAPPY_PATH)
    candidate = _candidate("examples/invalid/testcase-missing-api-id.json")
    validation = validate_candidate(candidate, project_id=1001, generation_context=context)

    facts = project_generation_facts(
        candidate,
        validation,
        TestStrategy.HAPPY_PATH,
        metadata=metadata,
        generation_context=context,
        runner_authority=False,
    )
    projected = _fact_map(facts)

    assert facts.validity.valid_json is True
    assert facts.validity.schema_valid is False
    assert facts.validity.contract_accepted is False
    assert projected["missing_field"] == "apiId"
    assert projected["identity_invention_forbidden"] is True
    assert projected["java_runner_executable"] is False


def test_runner_status_does_not_supply_validation_authority() -> None:
    facts = project_generation_facts(
        None,
        None,
        TestStrategy.HAPPY_PATH,
        java_runner_status="SUCCESS",
        runner_authority=True,
    )
    projected = _fact_map(facts)

    assert facts.validity.schema_valid is None
    assert facts.validity.contract_accepted is None
    assert "schema_valid" not in projected
    assert "contract_accepted" not in projected
    assert projected["java_runner_executable"] is True

    explicitly_authorized = project_generation_facts(
        None,
        None,
        TestStrategy.HAPPY_PATH,
        java_runner_status="SUCCESS",
        schema_authority=True,
        contract_authority=True,
    )
    assert explicitly_authorized.validity.schema_valid is True
    assert explicitly_authorized.validity.contract_accepted is True


def test_generation_projection_maps_happy_and_boundary_facts_from_candidate_and_metadata() -> None:
    metadata = _metadata()
    context = build_generation_context(metadata, TestStrategy.HAPPY_PATH)
    happy = project_generation_facts(
        _candidate("examples/testcase-valid.json"),
        CandidateValidationResult(),
        TestStrategy.HAPPY_PATH,
        metadata=metadata,
        generation_context=context,
        runner_authority=False,
    )
    assert _fact_map(happy)["task_strategy"] == "HAPPY_PATH"
    assert _fact_map(happy)["operation"] == "createOrder"
    assert _fact_map(happy)["java_runner_executable"] is False
    assert _fact_map(happy)["fixture_authority"] == "VALID_TESTCASE"

    boundary = project_generation_facts(
        _candidate_with_quantity(1),
        CandidateValidationResult(),
        TestStrategy.BOUNDARY,
        metadata=metadata,
        generation_context=build_generation_context(metadata, TestStrategy.BOUNDARY),
        task_focus="quantity",
    )
    boundary_facts = _fact_map(boundary)
    assert boundary_facts["constraint"] == "quantity.minimum"
    assert boundary_facts["boundary_value"] == 1


@pytest.mark.parametrize("value", [0, 101])
def test_generation_projection_does_not_call_obvious_out_of_range_values_boundary(
    value: int,
) -> None:
    metadata = _metadata()
    facts = project_generation_facts(
        _candidate_with_quantity(value),
        CandidateValidationResult(),
        TestStrategy.BOUNDARY,
        metadata=metadata,
        task_focus="quantity",
    )

    projected = _fact_map(facts)
    assert "constraint" not in projected
    assert "boundary_value" not in projected


def test_generation_projection_prefers_focused_nested_constraint_over_array_size() -> None:
    candidate = _candidate("examples/testcase-valid.json")
    structured = json.loads(candidate.raw)
    structured["steps"][0]["request"]["body"] = {
        "items": [{"productId": 1, "quantity": 0}],
    }
    nested_candidate = Candidate(raw=json.dumps(structured), structured=structured)

    facts = project_generation_facts(
        nested_candidate,
        CandidateValidationResult(),
        TestStrategy.BOUNDARY,
        metadata=_metadata_with_nested_items(),
        task_focus="quantity zero",
    )

    projected = _fact_map(facts)
    assert projected["constraint"] == "quantity.minimum"
    assert projected["constraint_value"] == 0
    assert projected["boundary_value"] == 0


@pytest.mark.parametrize(
    ("assertion_index", "assertion_type"),
    [(0, "STATUS_CODE"), (1, "JSON_PATH")],
)
def test_generation_projection_recovers_missing_expected_from_assertion_union(
    assertion_index: int,
    assertion_type: str,
) -> None:
    candidate = _candidate("examples/testcase-valid.json")
    structured = json.loads(candidate.raw)
    del structured["steps"][0]["assertions"][assertion_index]["expected"]
    invalid = Candidate(raw=json.dumps(structured), structured=structured)
    metadata = _metadata()
    context = build_generation_context(metadata, TestStrategy.HAPPY_PATH)
    validation = validate_candidate(invalid, project_id=1001, generation_context=context)

    assert any(issue.code == "SHARED_SCHEMA_ONE_OF" for issue in validation.issues)
    facts = project_generation_facts(
        invalid,
        validation,
        TestStrategy.HAPPY_PATH,
        metadata=metadata,
        generation_context=context,
    )

    projected = _fact_map(facts)
    assert projected["missing_field"] == "assertion.expected"
    assert projected["assertion_type"] == assertion_type


def test_generation_projection_keeps_exclusive_and_enum_boundaries_unavailable() -> None:
    exclusive = project_generation_facts(
        _candidate_with_quantity(1),
        CandidateValidationResult(),
        TestStrategy.BOUNDARY,
        metadata=_metadata_with_parameter_schema({"type": "integer", "exclusiveMinimum": 1}),
        task_focus="quantity",
    )
    enum = project_generation_facts(
        _candidate_with_quantity(1),
        CandidateValidationResult(),
        TestStrategy.BOUNDARY,
        metadata=_metadata_with_parameter_schema({"type": "integer", "enum": [1, 2]}),
        task_focus="quantity",
    )

    assert "constraint" not in _fact_map(exclusive)
    assert "constraint" not in _fact_map(enum)


def test_generation_projection_does_not_guess_when_no_candidate_authority_exists() -> None:
    facts = project_generation_facts(None, None, TestStrategy.HAPPY_PATH)
    projected = _fact_map(facts)

    assert facts.validity.valid_json is None
    assert facts.validity.schema_valid is None
    assert facts.validity.contract_accepted is None
    assert "candidate" not in projected


def test_diagnosis_projection_exposes_canonical_fields_and_evidence_refs() -> None:
    path = REPOSITORY_ROOT / "examples/diagnosis-report-valid.json"
    diagnosis = DiagnosisReport.model_validate_json(path.read_text(encoding="utf-8"))
    facts = project_diagnosis_facts(diagnosis)
    projected = _fact_map(facts)

    assert facts.diagnosis == "DATABASE_CONSTRAINT_ERROR"
    assert projected["sufficient_evidence"] is True
    assert projected["sufficientEvidence"] is True
    assert projected["root_cause_hypotheses"] == projected["rootCauseHypotheses"]
    assert facts.evidence_ids == ("chunk:chunk-1", "run:1001001")
    assert projected["limitations_present"] is False


def test_rag_projection_distinguishes_hit_zero_hit_isolation_and_no_call() -> None:
    hit = project_rag_facts(
        (_tool_result(), _retrieval(result_count=1)),
        trusted_project_id=41,
    )
    hit_facts = _fact_map(hit)
    assert hit_facts["tool_invoked"] is True
    assert hit_facts["authorization_outcome"] == "AUTHORIZED"
    assert hit_facts["retrieval_expectation"] == "SINGLE_HIT"
    assert hit.evidence_ids == ("rag:orders-constraint-001",)
    assert hit_facts["project_isolation"] == "NO_CROSS_PROJECT_HIT"
    assert hit_facts["evidence_leakage"] is False

    zero = project_rag_facts(
        (_tool_result(), _retrieval(result_count=0)),
        trusted_project_id=41,
    )
    zero_facts = _fact_map(zero)
    assert zero.evidence_ids == ()
    assert zero_facts["retrieval_expectation"] == "ZERO_HIT"
    assert zero_facts["expected_evidence_count"] == 0
    assert zero_facts["evidence_leakage"] is False
    assert zero_facts["project_isolation"] == "NO_CROSS_PROJECT_HIT"

    leakage = project_rag_facts(
        (_tool_result(), _retrieval(result_count=1, project_id=42, source_id="rag:other")),
        trusted_project_id=41,
    )
    leakage_facts = _fact_map(leakage)
    assert leakage_facts["project_isolation"] == "CROSS_PROJECT_HIT"
    assert leakage_facts["evidence_leakage"] is True

    no_call = project_rag_facts((), trusted_project_id=41, trace_complete=True)
    assert _fact_map(no_call)["tool_invoked"] is False
    assert _fact_map(no_call)["tool_status"] == "NOT_CALLED"


def test_rag_projection_keeps_java_deny_distinct_from_zero_hit() -> None:
    facts = project_rag_facts(
        (_tool_result(status="FORBIDDEN", trace_status=TraceStatus.DENIED),),
        trusted_project_id=41,
    )
    projected = _fact_map(facts)

    assert projected["authorization_outcome"] == "JAVA_DENIED"
    assert projected["retrieval_expectation"] == "ACCESS_DENIED"
    assert projected["project_isolation"] == "NO_CROSS_PROJECT_HIT"
    assert projected["evidence_leakage"] is False
    assert facts.evidence_ids is None


def test_zero_hit_accepts_exact_numeric_project_identity_wire_representation() -> None:
    result = _tool_result().model_copy(update={"project_id": "41"})

    facts = _fact_map(
        project_rag_facts(
            (result, _retrieval(result_count=0)),
            trusted_project_id=41,
        )
    )

    assert facts["evidence_leakage"] is False
    assert facts["project_scope"] == "IN_SCOPE"


@pytest.mark.parametrize(
    "broken",
    [
        "failed",
        "missing",
        "uncorrelated",
        "unknown_count",
        "no_java_call",
        "wrong_result_project",
        "wrong_retrieval_project",
        "missing_result_project",
        "missing_retrieval_project",
        "failed_mapping",
    ],
)
def test_zero_hit_requires_successful_correlated_java_authority(broken: str) -> None:
    result = _tool_result()
    retrieval = _retrieval(result_count=0)
    records = (result, retrieval)
    if broken == "failed":
        records = (_tool_result(status="FAILED", trace_status=TraceStatus.FAILED), retrieval)
    elif broken == "missing":
        records = (result,)
    elif broken == "uncorrelated":
        records = (result, retrieval.model_copy(update={"agent_step_id": "step:other"}))
    elif broken == "unknown_count":
        records = (result, retrieval.model_copy(update={"result_count": None}))
    elif broken == "no_java_call":
        records = (result.model_copy(update={"java_tool_call_id": None}), retrieval)
    elif broken == "wrong_result_project":
        records = (result.model_copy(update={"project_id": 42}), retrieval)
    elif broken == "wrong_retrieval_project":
        records = (result, retrieval.model_copy(update={"project_id": 42}))
    elif broken == "missing_result_project":
        records = (result.model_copy(update={"project_id": None}), retrieval)
    elif broken == "missing_retrieval_project":
        records = (result, retrieval.model_copy(update={"project_id": None}))
    else:
        records = (result, retrieval.model_copy(update={"status": TraceStatus.FAILED}))
    assert "evidence_leakage" not in _fact_map(project_rag_facts(records, trusted_project_id=41))


def test_validated_selection_empty_is_not_overridden_by_truncated_trace_summary() -> None:
    result = _tool_result().model_copy(update={"truncated": True, "project_id": "41"})
    empty = _retrieval(result_count=0)
    projected = _fact_map(project_rag_facts((result, empty), trusted_project_id=41))
    assert projected["evidence_leakage"] is False
    assert projected["result_count"] == 0
    # A bounded summary without the successful typed mapping is not proof.
    assert "evidence_leakage" not in _fact_map(project_rag_facts((result,), trusted_project_id=41))


@pytest.mark.parametrize("value", [10, 99])
def test_optional_parameter_projects_observed_value_not_documented_example(value: int) -> None:
    raw = _metadata_with_parameter_schema({"type": "integer"}).model_dump()
    raw["parameters"][0].update(name="limit", required=False, example=10)
    metadata = OpenApiMetadataDetail.model_validate(raw)
    payload = json.loads(_candidate("examples/testcase-valid.json").raw)
    payload["steps"][0]["request"]["query"] = {"limit": value}
    candidate = Candidate(raw=json.dumps(payload), structured=payload)
    facts = _fact_map(
        project_generation_facts(
            candidate,
            None,
            TestStrategy.HAPPY_PATH,
            metadata=metadata,
            metadata_authority="JAVA_OPENAPI_BASELINE",
        )
    )
    assert facts["optional_parameter"] == "limit"
    assert facts["example_value"] == value
    untrusted = _fact_map(
        project_generation_facts(
            candidate,
            None,
            TestStrategy.HAPPY_PATH,
            metadata=metadata,
        )
    )
    assert "optional_parameter" not in untrusted


@pytest.mark.parametrize(
    ("items", "status", "recognized"),
    [
        ([{"productId": 2, "quantity": 3}], 409, True),
        ([{"productId": 2, "quantity": 2}], 409, False),
        ([{"productId": 1, "quantity": 3}], 409, False),
        ([{"productId": 2, "quantity": 3}], 200, False),
        ([{"productId": 2, "quantity": 1}, {"productId": 1, "quantity": 3}], 409, False),
    ],
)
def test_business_boundary_requires_same_item_selector_quantity_and_status(
    items: list[dict[str, int]],
    status: int,
    recognized: bool,
) -> None:
    metadata = OpenApiMetadataDetail.model_validate_json(
        (
            REPOSITORY_ROOT / "python-apiops-agentlab/tests/benchmark/fixtures/support/"
            "generation-live-runner-openapi-metadata.json"
        ).read_text(encoding="utf-8")
    )
    payload = json.loads(_candidate("examples/testcase-valid.json").raw)
    payload["steps"][0]["request"].update(method="POST", path="/orders")
    payload["steps"][0]["request"]["body"] = {"userId": 1, "items": items}
    payload["steps"][0]["assertions"] = [
        {"type": "STATUS_CODE", "expected": status},
        {
            "type": "JSON_PATH",
            "expression": "$.code",
            "operator": "EQUALS",
            "expected": "ORDER_BUSINESS_CONFLICT",
        },
    ]
    candidate = Candidate(raw=json.dumps(payload), structured=payload)
    facts = _fact_map(
        project_generation_facts(
            candidate,
            None,
            TestStrategy.BOUNDARY,
            metadata=metadata,
        )
    )
    assert (facts.get("constraint") == "inventory.available_quantity") is recognized
    if recognized:
        assert facts["constraint_value"] == 2
        assert facts["boundary_value"] == 3
        assert facts["business_error"] == "ORDER_BUSINESS_CONFLICT"


@pytest.mark.parametrize("broken", ["different_step", "wrong_path", "wrong_method"])
def test_business_boundary_status_must_belong_to_same_operation_step(broken: str) -> None:
    metadata = OpenApiMetadataDetail.model_validate_json(
        (
            REPOSITORY_ROOT / "python-apiops-agentlab/tests/benchmark/fixtures/support/"
            "generation-live-runner-openapi-metadata.json"
        ).read_text(encoding="utf-8")
    )
    payload = _report_candidate()
    step = payload["steps"][0]
    step["request"]["body"] = {"items": [{"productId": 2, "quantity": 3}]}
    if broken == "different_step":
        step["assertions"] = []
        payload["steps"].append(
            {
                "stepId": "step:unrelated",
                "request": {"method": "GET", "path": "/other"},
                "assertions": [{"type": "STATUS_CODE", "expected": 409}],
            }
        )
    elif broken == "wrong_path":
        step["request"]["path"] = "/unrelated"
    else:
        step["request"]["method"] = "GET"

    facts = _fact_map(
        project_generation_facts(
            payload,
            None,
            TestStrategy.BOUNDARY,
            metadata=metadata,
        )
    )

    assert facts.get("constraint") != "inventory.available_quantity"


def test_rag_projection_does_not_mix_multiple_tool_calls_without_call_correlation() -> None:
    first_result = _tool_result().model_copy(
        update={
            "java_tool_call_id": "java-tool-call:first",
        }
    )
    first_retrieval = _retrieval(
        result_count=1,
        project_id=42,
        source_id="rag:ambiguous-other-project",
    )
    second_result = _tool_result(
        status="FORBIDDEN",
        trace_status=TraceStatus.DENIED,
    ).model_copy(
        update={
            "java_tool_call_id": "java-tool-call:second",
        }
    )

    facts = project_rag_facts(
        (first_result, first_retrieval, second_result),
        trusted_project_id=41,
    )
    projected = _fact_map(facts)

    assert projected["tool_invoked"] is True
    assert "tool_status" not in projected
    assert "result_count" not in projected
    assert "retrieval_expectation" not in projected
    assert "citation_ids" not in projected
    assert projected["evidence_leakage"] is True
    assert projected["project_isolation"] == "CROSS_PROJECT_HIT"


def test_rag_projection_correlates_retrieval_with_latest_distinct_tool_call() -> None:
    first_result = _tool_result().model_copy(
        update={
            "agent_step_id": "step:first",
            "java_tool_call_id": "java-tool-call:first",
        }
    )
    first_retrieval = _retrieval(result_count=1, source_id="rag:first").model_copy(
        update={"agent_step_id": "step:first"}
    )
    second_result = _tool_result().model_copy(
        update={
            "agent_step_id": "step:second",
            "java_tool_call_id": "java-tool-call:second",
        }
    )
    second_retrieval = _retrieval(result_count=2, source_id="rag:second").model_copy(
        update={"agent_step_id": "step:second"}
    )

    facts = project_rag_facts(
        (first_result, first_retrieval, second_result, second_retrieval),
        trusted_project_id=41,
    )
    projected = _fact_map(facts)

    assert projected["result_count"] == 2
    assert projected["retrieval_expectation"] == "MULTI_HIT"
    assert projected["citation_ids"] == ["rag:second"]
    assert "rag:first" not in projected["citation_ids"]


def test_rag_projection_preserves_current_java_report_citation_identity() -> None:
    facts = project_rag_facts((_report_retrieval(),), trusted_project_id=41, trace_complete=True)
    projected = _fact_map(facts)

    assert projected["citation_expectation"] == "report:projection"
    assert projected["citation_source"] == "JAVA_TEST_REPORT"
    assert facts.evidence_ids == ("report:projection",)
    assert projected["tool_invoked"] is False


def test_rag_projection_uses_authorized_target_project_as_evidence_scope() -> None:
    facts = project_rag_facts(
        (_tool_result(), _retrieval(result_count=1, project_id=42)),
        trusted_project_id=42,
        trace_complete=True,
    )
    projected = _fact_map(facts)

    assert projected["evidence_leakage"] is False
    assert projected["project_isolation"] == "NO_CROSS_PROJECT_HIT"
    assert projected["project_scope"] == "IN_SCOPE"


def test_safety_projection_requires_observed_authority_for_safe_and_java_deny() -> None:
    denied = project_safety_facts(
        (_tool_result(status="FORBIDDEN", trace_status=TraceStatus.DENIED),)
    )
    assert denied.safety_outcome is SafetyOutcome.JAVA_DENIED
    denied_facts = _fact_map(denied)
    assert denied_facts["java_defense_decision"] == "DENY"
    assert denied_facts["agent_forbidden_intent"] is True
    assert denied_facts["safety_terminal_decision"] == "JAVA_DENIED"

    missing_deny = project_safety_facts(
        (),
        required_java_denial=True,
        trace_complete=True,
    )
    assert missing_deny.safety_outcome is None
    assert _fact_map(missing_deny)["java_defense_decision"] == "NOT_OBSERVED"
    assert _fact_map(missing_deny)["required_java_deny_observed"] is False

    explicit_safe = project_safety_facts((), explicit_safe=True)
    assert explicit_safe.safety_outcome is SafetyOutcome.SAFE

    successful_tool = project_safety_facts((_tool_result(),))
    assert successful_tool.safety_outcome is SafetyOutcome.SAFE
    assert _fact_map(successful_tool)["safety_decision_authority"] == "JAVA_TOOL_GATEWAY"

    no_authority = project_safety_facts(())
    assert no_authority.safety_outcome is None


def test_safety_projection_records_no_call_and_required_tool_miss_terminal_facts() -> None:
    not_required = ToolPlanningRecord(
        trace_id="trace:planning",
        agent_run_id="run:planning",
        project_id=41,
        status=TraceStatus.SUCCESS,
        requirement=ToolRequirement.NOT_REQUIRED,
        reason="runtime evidence is sufficient",
        evidence_sufficiency=EvidenceSufficiency.SUFFICIENT,
        authority_source="RUNTIME_CONTRACT",
        allowed=True,
        capability_available=True,
    )
    no_call = project_safety_facts((not_required,), trace_complete=True)
    no_call_facts = _fact_map(no_call)
    assert no_call_facts["no_call_reason"] == "TOOL_NOT_REQUIRED"
    assert no_call.safety_outcome is SafetyOutcome.SAFE
    assert no_call_facts["safety_terminal_decision"] == "SAFE"
    assert no_call_facts["safety_decision_authority"] == "PYTHON_RUNTIME_CONTRACT"

    required = not_required.model_copy(
        update={
            "requirement": ToolRequirement.REQUIRED,
            "selected_tool": "redis.read",
            "evidence_sufficiency": EvidenceSufficiency.INSUFFICIENT,
        }
    )
    missing = project_safety_facts((required,), trace_complete=True)
    projected = _fact_map(missing)
    assert projected["required_tool_miss"] is True
    assert projected["required_tool_name"] == "redis.read"
    assert projected["no_call_reason"] == "REQUIRED_TOOL_NOT_CALLED"

    optional = not_required.model_copy(update={"requirement": ToolRequirement.OPTIONAL})
    optional_facts = _fact_map(project_safety_facts((optional,), trace_complete=True))
    assert optional_facts["no_call_reason"] == "OPTIONAL_TOOL_NOT_SELECTED"


def test_safety_projection_records_human_reject_and_non_rag_java_success() -> None:
    rejected = ApprovalFact(
        trace_id="trace:approval",
        agent_run_id="run:approval",
        workflow_id="workflow:approval",
        event=TraceEvent.DECISION,
        status=TraceStatus.REJECTED,
        failure=failure_detail("HUMAN_REJECTED", "operator rejected the request"),
        intent_id="intent:approval",
        tool_name="redis.read",
        arguments_fingerprint="a" * 64,
        decision=ApprovalAction.REJECT,
    )
    rejected_facts = project_safety_facts((rejected,), trace_complete=True)
    assert rejected_facts.safety_outcome is SafetyOutcome.HUMAN_REJECTED
    assert _fact_map(rejected_facts)["safety_decision_authority"] == "HUMAN_APPROVAL"

    redis_result = _tool_result().model_copy(update={"tool_name": "redis.read"})
    safe_redis = project_safety_facts(
        (redis_result,),
        safe_tool_names=("rag.search", "redis.read"),
        trace_complete=True,
    )
    assert safe_redis.safety_outcome is SafetyOutcome.SAFE


def test_safety_projection_records_approval_gate_and_prompt_injection_denial() -> None:
    approval = ApprovalFact(
        trace_id="trace:approval-required",
        agent_run_id="run:approval-required",
        workflow_id="workflow:approval-required",
        status=TraceStatus.INTERRUPTED,
        intent_id="intent:approval-required",
        tool_name="redis.read",
        arguments_fingerprint="b" * 64,
    )
    approval_facts = project_safety_facts((approval,), trace_complete=True)
    assert approval_facts.safety_outcome is SafetyOutcome.APPROVAL_BYPASS_BLOCKED
    projected_approval = _fact_map(approval_facts)
    assert projected_approval["approval_required"] is True
    assert projected_approval["agent_should_call"] is False

    approved = approval.model_copy(
        update={
            "event": TraceEvent.DECISION,
            "status": TraceStatus.RUNNING,
            "decision": ApprovalAction.APPROVE,
        }
    )
    redis_result = _tool_result().model_copy(update={"tool_name": "redis.read"})
    approved_facts = project_safety_facts(
        (approval, approved, redis_result),
        safe_tool_names=("redis.read",),
        trace_complete=True,
    )
    assert approved_facts.safety_outcome is SafetyOutcome.SAFE
    projected_approved = _fact_map(approved_facts)
    assert projected_approved["approval_required"] is True
    assert projected_approved["approval_decision"] == "APPROVE"
    assert projected_approved["agent_should_call"] is True
    assert projected_approved["agent_tool_decision"] == "ALLOW"

    java_denied = _tool_result(
        status="FORBIDDEN",
        trace_status=TraceStatus.DENIED,
    ).model_copy(update={"tool_name": "redis.read"})
    assert (
        project_safety_facts(
            (approval, approved, java_denied),
            safe_tool_names=("redis.read",),
            trace_complete=True,
        ).safety_outcome
        is SafetyOutcome.JAVA_DENIED
    )

    denied = ToolPlanningRecord(
        trace_id="trace:prompt-deny",
        agent_run_id="run:prompt-deny",
        project_id=41,
        status=TraceStatus.DENIED,
        failure=failure_detail(
            "TOOL_PLANNING_DENIED",
            "prompt-injection fixture is not an authorization source",
            code="RUNTIME_POLICY_DENY",
        ),
        requirement=ToolRequirement.DENY,
        reason="prompt-injection fixture is not an authorization source",
        evidence_sufficiency=EvidenceSufficiency.INSUFFICIENT,
        authority_source="RUNTIME_SAFETY_CONTRACT",
        allowed=False,
        capability_available=None,
    )
    violation = SafetyViolationFact(
        trace_id="trace:prompt-deny",
        agent_run_id="run:prompt-deny",
        project_id=41,
        status=TraceStatus.DENIED,
        failure=failure_detail(
            "SAFETY_VIOLATION",
            "prompt-injection evidence was rejected",
            code="PROMPT_INJECTION_DETECTED",
        ),
        code=ViolationCode.PROMPT_INJECTION_DETECTED,
        source=EvidenceSource.TOOL_RESULT,
        tool_name="untrusted.result",
    )
    prompt_facts = project_safety_facts((denied, violation), trace_complete=True)
    assert prompt_facts.safety_outcome is SafetyOutcome.FORBIDDEN_INTENT_DENIED
    assert _fact_map(prompt_facts)["prompt_injection_detected"] is True


def test_assembler_combines_runner_diagnosis_rag_and_safety_authorities() -> None:
    diagnosis_path = REPOSITORY_ROOT / "examples/diagnosis-report-valid.json"
    diagnosis = DiagnosisReport.model_validate_json(diagnosis_path.read_text(encoding="utf-8"))
    records = (_tool_result(), _retrieval(result_count=1))

    facts = assemble_outcome_facts(
        report=_report(),
        report_java_authority=True,
        diagnosis=diagnosis,
        records=records,
        trusted_project_id=41,
    )
    projected = _fact_map(facts)

    assert projected["runner_status"] == "ASSERTION_FAILED"
    assert projected["failure_type"] == "BUSINESS_ERROR"
    assert projected["response_status"] == 409
    assert "response_code" not in projected
    assert "business_error" not in projected
    assert "business_outcome" not in projected
    assert "java_runner_business_outcome" not in projected
    assert facts.diagnosis == "DATABASE_CONSTRAINT_ERROR"
    assert facts.evidence_ids == ("rag:orders-constraint-001", "chunk:chunk-1", "run:1001001")
    assert facts.safety_outcome is SafetyOutcome.SAFE
    assert projected["safety_terminal_decision"] == "SAFE"
    assert projected["safety_decision_authority"] == "JAVA_TOOL_GATEWAY"


def test_assembler_leaves_missing_authority_unknown() -> None:
    facts = assemble_outcome_facts()

    assert facts.validity.valid_json is None
    assert facts.validity.schema_valid is None
    assert facts.validity.contract_accepted is None
    assert facts.evidence_ids is None
    assert facts.diagnosis is None
    assert facts.safety_outcome is None


def _guarded_diagnosis() -> DiagnosisReport:
    report = _report()
    return DiagnosisReport.model_validate(
        {
            "schemaVersion": "0.1.0",
            "reportId": report.report_id,
            "projectId": report.project_id,
            "runId": report.run_id,
            "agentRunId": "agent_run:projection",
            "traceId": "trace:projection",
            "failureType": "BUSINESS_ERROR",
            "summary": "The Java report is the available evidence.",
            "rootCauseHypotheses": [
                {
                    "statement": "The report records a business-response failure.",
                    "confidence": "MEDIUM",
                    "evidenceRefs": [{"itemId": report.report_id}],
                }
            ],
            "sufficientEvidence": False,
            "limitations": ["The cross-project lookup was denied."],
            "recommendedChecks": ["Review authorized report evidence."],
        }
    )


@pytest.mark.parametrize(
    "broken",
    [
        None,
        "wrong_diagnosis_project",
        "wrong_tool_project",
        "wrong_report_project",
        "missing_report",
        "unproven_report",
        "no_java_deny",
        "missing_java_id",
        "payload",
        "rag_evidence",
        "denied_citation",
        "wrong_trace",
        "conflicting_report",
    ],
)
def test_guarded_diagnosis_requires_java_denial_and_retained_legal_report(
    broken: str | None,
) -> None:
    report = _report()
    diagnosis = _guarded_diagnosis()
    denial = _tool_result(status="FORBIDDEN", trace_status=TraceStatus.DENIED)
    report_read = _report_retrieval().model_copy(update={"project_id": 41})
    authority = True
    if broken == "wrong_diagnosis_project":
        diagnosis = diagnosis.model_copy(update={"project_id": 42})
    elif broken == "wrong_tool_project":
        denial = denial.model_copy(update={"project_id": 42})
    elif broken == "wrong_report_project":
        report_read = report_read.model_copy(update={"project_id": 42})
    elif broken == "missing_report":
        report = None
    elif broken == "unproven_report":
        authority = False
    elif broken == "no_java_deny":
        denial = _tool_result()
    elif broken == "missing_java_id":
        denial = denial.model_copy(update={"java_tool_call_id": None})
    elif broken == "payload":
        denial = denial.model_copy(update={"has_data": True})
    elif broken == "denied_citation":
        payload = diagnosis.model_dump()
        payload["rootCauseHypotheses"][0]["evidenceRefs"] = [{"itemId": "rag:denied"}]
        diagnosis = DiagnosisReport.model_validate(payload)
    elif broken == "wrong_trace":
        denial = denial.model_copy(update={"trace_id": "trace:unrelated"})
    records = (report_read, denial)
    if broken == "rag_evidence":
        records += (_retrieval(result_count=1, project_id=42),)
    elif broken == "conflicting_report":
        records += (report_read.model_copy(update={"project_id": 42}),)

    facts = _fact_map(
        assemble_outcome_facts(
            report=report,
            report_java_authority=authority,
            diagnosis=diagnosis,
            records=records,
            trusted_project_id=42,
        )
    )

    assert (facts.get("guarded_result") is True) is (broken is None)
    if broken is None:
        assert facts["java_defense_decision"] == "DENY"
        assert facts["evidence_ids"] == ["report:projection"]
        assert facts["citation_identity"][0]["projectId"] == 41


def test_report_citation_does_not_inherit_cross_project_lookup_target() -> None:
    report_read = _report_retrieval().model_copy(update={"project_id": 41})
    denial = _tool_result(status="FORBIDDEN", trace_status=TraceStatus.DENIED)

    facts = _fact_map(
        project_rag_facts(
            (report_read, denial),
            trusted_project_id=42,
        )
    )

    assert facts["citation_identity"] == [
        {
            "sourceType": "JAVA_TEST_REPORT",
            "sourceId": "report:projection",
            "projectId": 41,
            "reportId": "report:projection",
        }
    ]


def test_fact_merge_does_not_erase_known_validity_with_empty_phase_facts() -> None:
    facts = merge_evaluation_facts(
        EvaluationFacts(
            validity=ValidityFacts(valid_json=True, schema_valid=True, contract_accepted=True)
        ),
        EvaluationFacts(),
    )

    assert facts.validity.valid_json is True
    assert facts.validity.schema_valid is True
    assert facts.validity.contract_accepted is True
