"""Deterministic tests for Stage 16 strategy applicability and context shaping."""

from __future__ import annotations

from copy import deepcopy
from typing import get_type_hints

import pytest

from app.schemas.openapi_metadata import OpenApiMetadataDetail
from app.workflows.generation_context import TestStrategy as Strategy
from app.workflows.generation_context import (
    build_generation_context,
    documented_business_boundaries,
    strategy_applicability,
)
from app.workflows.state import APIOpsAgentState


def make_metadata(**overrides: object) -> OpenApiMetadataDetail:
    payload: dict[str, object] = {
        "apiId": "api-1",
        "apiDocId": "doc-1",
        "operationId": "getOrders",
        "method": "GET",
        "path": "/orders/{orderId}",
        "summary": "Get order",
        "description": "Returns one order.",
        "tags": ["orders"],
        "servers": [{"url": "https://api.example"}],
        "security": None,
        "deprecated": False,
        "parameters": [
            {
                "name": "orderId",
                "location": "path",
                "required": True,
                "description": "Order identifier",
                "schema": {"type": "string"},
                "example": "order-1",
            }
        ],
        "requestSchemas": [],
        "responseSchemas": [
            {
                "statusCode": "200",
                "description": "ok",
                "mediaType": "application/json",
                "schema": {"type": "object"},
            }
        ],
        "examples": [],
    }
    payload.update(overrides)
    return OpenApiMetadataDetail.model_validate(payload)


def test_state_retains_prior_fields_and_adds_stage16_workflow_fields() -> None:
    hints = get_type_hints(APIOpsAgentState)

    assert set(hints) == {
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
    assert hints["agent_run_id"] is str
    assert hints["project_id"] is int
    assert hints["api_id"] is str
    assert hints["generation_intent"] is str
    assert hints["repair_attempts"] is int
    assert hints["max_repair_attempts"] is int


def test_happy_path_requires_documented_success_response() -> None:
    result = strategy_applicability(make_metadata())

    assert result[Strategy.HAPPY_PATH].applicable is True
    assert result[Strategy.HAPPY_PATH].supporting_evidence == ("responseSchemas[0].statusCode=200",)


def test_missing_required_uses_only_required_parameter_or_request_schema_evidence() -> None:
    metadata = make_metadata(
        parameters=[
            {
                "name": "optional",
                "location": "query",
                "required": False,
                "description": None,
                "schema": {"type": "string"},
                "example": "value",
            }
        ],
        responseSchemas=[],
    )

    assert strategy_applicability(metadata)[Strategy.MISSING_REQUIRED].applicable is False


def test_boundary_reads_real_nested_schema_constraints() -> None:
    metadata = make_metadata(
        parameters=[
            {
                "name": "quantity",
                "location": "query",
                "required": False,
                "description": None,
                "schema": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 10,
                },
                "example": 2,
            }
        ]
    )

    result = strategy_applicability(metadata)[Strategy.BOUNDARY]

    assert result.applicable is True
    assert result.supporting_evidence == (
        "parameters[0].schema.minimum",
        "parameters[0].schema.maximum",
    )


def test_auth_failure_requires_declared_security() -> None:
    metadata = make_metadata(security=[{"apiKeyAuth": []}])

    result = strategy_applicability(metadata)[Strategy.AUTH_FAILURE]

    assert result.applicable is True
    assert result.supporting_evidence == ("security[0] declares apiKeyAuth",)


def test_business_error_requires_documented_non_2xx_response() -> None:
    metadata = make_metadata(
        responseSchemas=[
            {
                "statusCode": "400",
                "description": "bad request",
                "mediaType": "application/json",
                "schema": {"type": "object"},
            }
        ]
    )

    result = strategy_applicability(metadata)[Strategy.BUSINESS_ERROR]

    assert result.applicable is True
    assert result.supporting_evidence == ("responseSchemas[0].statusCode=400",)


def test_idempotency_is_not_inferred_from_post_or_request_id_header() -> None:
    metadata = make_metadata(
        method="POST",
        parameters=[
            {
                "name": "X-Request-Id",
                "location": "header",
                "required": False,
                "description": None,
                "schema": {"type": "string"},
                "example": "request-1",
            }
        ],
    )

    assert strategy_applicability(metadata)[Strategy.IDEMPOTENCY].applicable is False


def test_idempotency_accepts_explicit_operation_documentation() -> None:
    metadata = make_metadata(description="This operation is idempotent.")

    result = strategy_applicability(metadata)[Strategy.IDEMPOTENCY]

    assert result.applicable is True
    assert result.supporting_evidence == ("description explicitly documents idempotency",)


def test_not_applicable_strategy_cannot_build_formal_context() -> None:
    with pytest.raises(ValueError, match="IDEMPOTENCY is not applicable"):
        build_generation_context(make_metadata(), Strategy.IDEMPOTENCY)


def test_context_requires_documented_server_url_for_dsl_environment() -> None:
    with pytest.raises(ValueError, match="non-empty server URL"):
        build_generation_context(make_metadata(servers=None), Strategy.HAPPY_PATH)


def test_context_retains_operation_identity_required_control_facts_and_responses() -> None:
    metadata = make_metadata(
        requestSchemas=[
            {
                "required": True,
                "mediaType": "application/json",
                "schema": {"type": "object"},
            }
        ]
    )

    context = build_generation_context(metadata, Strategy.HAPPY_PATH)

    assert context.api_id == "api-1"
    assert context.api_doc_id == "doc-1"
    assert context.operation_id == "getOrders"
    assert context.method == "GET"
    assert context.path == "/orders/{orderId}"
    assert context.base_url == "https://api.example"
    assert context.strategy is Strategy.HAPPY_PATH
    assert [fact.source for fact in context.request_facts] == [
        "parameters[0]",
        "requestSchemas[0]",
    ]
    assert context.request_facts[0].name == "orderId"
    assert context.request_facts[0].location == "path"
    assert context.request_facts[0].example == "order-1"
    assert context.request_facts[1].required is True
    assert context.request_facts[1].media_type == "application/json"
    assert [response.status_code for response in context.documented_responses] == ["200"]


def test_happy_context_retains_documented_optional_parameter_example() -> None:
    metadata = make_metadata(
        path="/orders",
        parameters=[
            {
                "name": "limit",
                "location": "query",
                "required": False,
                "description": "Maximum orders to return",
                "schema": {"type": "integer"},
                "example": 10,
            },
            {
                "name": "cursor",
                "location": "query",
                "required": False,
                "description": "Optional cursor without an example",
                "schema": {"type": "string"},
                "example": None,
            },
        ],
    )

    context = build_generation_context(metadata, Strategy.HAPPY_PATH)

    assert [(fact.name, fact.location, fact.example) for fact in context.request_facts] == [
        ("limit", "query", 10)
    ]


def test_boundary_context_retains_success_and_business_response_authority() -> None:
    metadata = make_metadata(
        parameters=[
            {
                "name": "quantity",
                "location": "query",
                "required": True,
                "description": "Requested quantity",
                "schema": {"type": "integer", "minimum": 1},
                "example": 1,
            }
        ],
        responseSchemas=[
            {
                "statusCode": "200",
                "description": "accepted boundary",
                "mediaType": "application/json",
                "schema": {"type": "object"},
            },
            {
                "statusCode": "409",
                "description": "inventory boundary crossed",
                "mediaType": "application/json",
                "schema": {"type": "object"},
            },
        ],
    )

    context = build_generation_context(metadata, Strategy.BOUNDARY)

    assert [response.status_code for response in context.documented_responses] == [
        "200",
        "409",
    ]


def test_context_does_not_mutate_or_alias_metadata() -> None:
    metadata = make_metadata(
        parameters=[
            {
                "name": "quantity",
                "location": "query",
                "required": False,
                "description": None,
                "schema": {"type": "integer", "minimum": 1},
                "example": 2,
            }
        ]
    )
    before = deepcopy(metadata.model_dump())

    context = build_generation_context(metadata, Strategy.BOUNDARY)

    assert metadata.model_dump() == before
    assert context.request_facts[0].schema_ == {"type": "integer", "minimum": 1}
    assert context.request_facts[0].schema_ is not metadata.parameters[0].schema_


def business_boundary_metadata() -> OpenApiMetadataDetail:
    return make_metadata(
        parameters=[],
        requestSchemas=[{
            "required": True,
            "mediaType": "application/json",
            "schema": {
                "type": "object",
                "properties": {"items": {
                    "type": "array",
                    "items": {"type": "object", "properties": {
                        "productId": {"type": "integer"},
                        "quantity": {"type": "integer"},
                    }},
                }},
                "x-business-boundaries": [{
                    "name": "inventory.available_quantity",
                    "requestPath": "items[].quantity",
                    "selector": {"path": "items[].productId", "value": 2},
                    "limit": 2,
                    "operator": "GT",
                    "statusCode": 409,
                }],
            },
        }],
        responseSchemas=[{
            "statusCode": "409", "description": "Business rejection",
            "mediaType": "application/json", "schema": {"type": "object"},
        }],
    )


def test_structured_business_boundary_uses_documented_integer_rejection_edge() -> None:
    metadata = business_boundary_metadata()

    context = build_generation_context(metadata, Strategy.BOUNDARY)

    assert context.business_boundaries[0]["boundaryValue"] == 3
    assert context.business_boundaries[0]["limit"] == 2
    assert context.business_boundaries[0]["selector"] == {
        "path": "items[].productId", "value": 2,
    }
    assert context.supporting_evidence == (
        "requestSchemas[0].schema.x-business-boundaries[0]: "
        "inventory.available_quantity rejection boundary=3",
    )
    assert "maximum" not in metadata.request_schemas[0].schema_["properties"]["items"][
        "items"
    ]["properties"]["quantity"]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("requestPath", "items[].missing"),
        ("requestPath", "other[].quantity"),
        ("selector", {"path": "items[].productId", "value": "2"}),
        ("statusCode", 418),
        ("limit", True),
        ("operator", "UNPROVEN"),
    ],
)
def test_business_boundary_rejects_unbound_or_ill_typed_authority(
    field: str, value: object,
) -> None:
    metadata = business_boundary_metadata()
    metadata.request_schemas[0].schema_["x-business-boundaries"][0][field] = value

    with pytest.raises(ValueError):
        documented_business_boundaries(metadata)


def test_business_boundary_is_not_inferred_from_description() -> None:
    metadata = make_metadata(description="Inventory 2; above 2 returns 409.")

    assert documented_business_boundaries(metadata) == ()
    assert not strategy_applicability(metadata)[Strategy.BOUNDARY].applicable
