from __future__ import annotations

import copy
import json

import pytest
from pydantic import ValidationError
from pydantic.experimental.missing_sentinel import MISSING

from app.agents.testcase_generator import Candidate
from app.schemas.testcase_dsl import TestCaseDSL as CaseModel
from app.workflows.candidate_validation import (
    CandidateValidationResult,
    ValidationIssue,
    validate_candidate,
)
from app.workflows.generation_context import DocumentedResponse, GenerationContext
from app.workflows.generation_context import TestStrategy as Strategy


def make_context() -> GenerationContext:
    return GenerationContext(
        api_id="api-orders",
        api_doc_id="doc-orders-v1",
        operation_id="getOrder",
        method="GET",
        path="/orders/{order_id}",
        base_url="https://example.test",
        strategy=Strategy.HAPPY_PATH,
        supporting_evidence=("responseSchemas[0].statusCode=200",),
    )


def context_with_responses(
    strategy: Strategy,
    *statuses: str,
) -> GenerationContext:
    context = make_context()
    return context.model_copy(
        update={
            "strategy": strategy,
            "documented_responses": tuple(
                DocumentedResponse(
                    status_code=status,
                    description="documented response",
                    media_type="application/json",
                    schema_={"type": "object"},
                )
                for status in statuses
            ),
        }
    )


def valid_payload() -> dict[str, object]:
    return {
        "schemaVersion": "1.0.0",
        "caseId": "case-get-order",
        "projectId": 101,
        "apiId": "api-orders",
        "name": "Get one order",
        "environment": {"baseUrl": "https://example.test", "variables": {}},
        "steps": [
            {
                "stepId": "get-order",
                "name": "Get the order",
                "request": {
                    "method": "GET",
                    "path": "/orders/{order_id}",
                    "pathParams": {"order_id": "order-123"},
                },
                "assertions": [{"type": "STATUS_CODE", "expected": 200}],
                "extractors": [],
            }
        ],
    }


def make_candidate(payload: dict[str, object] | None = None) -> Candidate:
    structured = valid_payload() if payload is None else payload
    return Candidate(raw=json.dumps(structured), structured=structured)


def validate(candidate: Candidate) -> CandidateValidationResult:
    return validate_candidate(candidate, project_id=101, generation_context=make_context())


def test_fully_valid_candidate_has_no_issues() -> None:
    result = validate(make_candidate())

    assert result.valid is True
    assert result.issues == ()
    assert result.model_dump() == {"issues": (), "valid": True}


def test_project_id_mismatch_is_a_semantic_issue() -> None:
    payload = valid_payload()
    payload["projectId"] = 999

    result = validate(make_candidate(payload))

    assert result.valid is False
    assert result.issues == (
        ValidationIssue(
            code="PROJECT_ID_MISMATCH",
            path="/projectId",
            layer="SEMANTIC",
            message="Candidate projectId does not match the requested project context.",
        ),
    )


def test_api_id_mismatch_is_a_semantic_issue() -> None:
    payload = valid_payload()
    payload["apiId"] = "api-other"

    result = validate(make_candidate(payload))

    assert [(issue.code, issue.path, issue.layer) for issue in result.issues] == [
        ("API_ID_MISMATCH", "/apiId", "SEMANTIC")
    ]


def test_shared_schema_violation_is_a_schema_issue() -> None:
    payload = valid_payload()
    del payload["schemaVersion"]

    result = validate(make_candidate(payload))

    assert result.valid is False
    assert [(issue.code, issue.path, issue.layer) for issue in result.issues] == [
        ("SHARED_SCHEMA_REQUIRED", "/schemaVersion", "SCHEMA")
    ]


def test_shared_schema_rejects_additional_property() -> None:
    payload = valid_payload()
    payload["unexpected"] = True

    result = validate(make_candidate(payload))

    assert [(issue.code, issue.path, issue.layer) for issue in result.issues] == [
        ("SHARED_SCHEMA_ADDITIONAL_PROPERTY", "/unexpected", "SCHEMA")
    ]


def test_shared_schema_remains_authority_when_pydantic_accepts_payload() -> None:
    payload = valid_payload()
    payload["description"] = MISSING
    CaseModel.model_validate(payload)
    candidate = Candidate(raw=json.dumps(valid_payload()), structured=payload)

    result = validate(candidate)

    assert [(issue.code, issue.path, issue.layer) for issue in result.issues] == [
        ("SHARED_SCHEMA_TYPE", "/description", "SCHEMA")
    ]


def test_multiple_semantic_mismatches_are_collected() -> None:
    payload = valid_payload()
    payload["projectId"] = 999
    payload["apiId"] = "api-other"

    result = validate(make_candidate(payload))

    assert [issue.code for issue in result.issues] == [
        "PROJECT_ID_MISMATCH",
        "API_ID_MISMATCH",
    ]


@pytest.mark.parametrize(
    ("field", "value", "expected_code"),
    (
        ("method", "POST", "METHOD_MISMATCH"),
        ("path", "/other", "PATH_MISMATCH"),
    ),
)
def test_operation_snapshot_mismatch_is_semantic_issue(
    field: str,
    value: str,
    expected_code: str,
) -> None:
    payload = valid_payload()
    payload["steps"][0]["request"][field] = value

    result = validate(make_candidate(payload))

    assert [issue.code for issue in result.issues] == [expected_code]


@pytest.mark.parametrize(
    ("strategy", "documented", "candidate_status"),
    (
        (Strategy.HAPPY_PATH, "200", 500),
        (Strategy.AUTH_FAILURE, "401", 200),
        (Strategy.BUSINESS_ERROR, "409", 200),
    ),
)
def test_strategy_requires_a_documented_status_assertion(
    strategy: Strategy,
    documented: str,
    candidate_status: int,
) -> None:
    payload = valid_payload()
    payload["steps"][0]["assertions"] = [
        {"type": "STATUS_CODE", "expected": candidate_status}
    ]
    context = context_with_responses(strategy, documented)

    result = validate_candidate(
        make_candidate(payload),
        project_id=101,
        generation_context=context,
    )

    assert result.valid is False
    assert result.issues[0].code == "STRATEGY_STATUS_EXPECTATION_MISSING"
    if strategy is Strategy.BUSINESS_ERROR:
        assert result.issues[1].code == "BUSINESS_ERROR_STATUS_EXPECTATION_MISSING"


@pytest.mark.parametrize(
    ("strategy", "documented", "candidate_status"),
    (
        (Strategy.HAPPY_PATH, "200", 200),
        (Strategy.AUTH_FAILURE, "401", 401),
        (Strategy.BUSINESS_ERROR, "409", 409),
    ),
)
def test_strategy_accepts_its_documented_status_assertion(
    strategy: Strategy,
    documented: str,
    candidate_status: int,
) -> None:
    payload = valid_payload()
    payload["steps"][0]["assertions"] = [
        {"type": "STATUS_CODE", "expected": candidate_status}
    ]

    result = validate_candidate(
        make_candidate(payload),
        project_id=101,
        generation_context=context_with_responses(strategy, documented),
    )

    assert result.valid is True


def test_validator_does_not_modify_candidate() -> None:
    candidate = make_candidate()
    before = copy.deepcopy(candidate.model_dump())

    validate(candidate)

    assert candidate.model_dump() == before


def test_valid_is_derived_from_issues_and_cannot_be_supplied() -> None:
    issue = ValidationIssue(
        code="API_ID_MISMATCH",
        path="/apiId",
        layer="SEMANTIC",
        message="Candidate apiId does not match the generation context.",
    )

    assert CandidateValidationResult().valid is True
    assert CandidateValidationResult(issues=(issue,)).valid is False
    with pytest.raises(ValidationError):
        CandidateValidationResult(valid=True, issues=(issue,))
