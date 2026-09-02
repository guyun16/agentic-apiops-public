"""Deterministic Stage 16 strategy applicability and minimal context views."""

from __future__ import annotations

import re
from collections.abc import Iterator
from copy import deepcopy
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, StrictBool, StrictStr

from app.schemas.openapi_metadata import OpenApiMetadataDetail
from app.schemas.testcase_dsl import JsonValue


class TestStrategy(StrEnum):
    """Python-internal generation intents; not part of a shared contract."""

    __test__ = False

    HAPPY_PATH = "HAPPY_PATH"
    MISSING_REQUIRED = "MISSING_REQUIRED"
    BOUNDARY = "BOUNDARY"
    AUTH_FAILURE = "AUTH_FAILURE"
    IDEMPOTENCY = "IDEMPOTENCY"
    BUSINESS_ERROR = "BUSINESS_ERROR"


class StrategyApplicability(BaseModel):
    """Deterministic evidence result for one internal strategy."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    strategy: TestStrategy
    applicable: StrictBool
    supporting_evidence: tuple[StrictStr, ...] = ()


class RequestFact(BaseModel):
    """Small request fragment needed to keep a generated request well-formed."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    source: StrictStr
    kind: Literal["PARAMETER", "REQUEST_SCHEMA"]
    name: StrictStr | None = None
    location: Literal["path", "query", "header", "cookie"] | None = None
    required: StrictBool
    media_type: StrictStr | None = None
    schema_: dict[StrictStr, JsonValue] | None = None
    example: JsonValue = None


class DocumentedResponse(BaseModel):
    """Small documented response fragment relevant to the selected strategy."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    status_code: StrictStr
    description: StrictStr | None
    media_type: StrictStr
    schema_: dict[StrictStr, JsonValue] | None = None


class GenerationContext(BaseModel):
    """Minimal, strategy-oriented context; it is not a copy of API metadata."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    api_id: StrictStr
    api_doc_id: StrictStr
    operation_id: StrictStr | None
    method: StrictStr
    path: StrictStr
    base_url: StrictStr
    strategy: TestStrategy
    supporting_evidence: tuple[StrictStr, ...]
    request_facts: tuple[RequestFact, ...] = ()
    documented_responses: tuple[DocumentedResponse, ...] = ()


_BOUNDARY_KEYS = frozenset(
    {
        "minimum",
        "maximum",
        "exclusiveMinimum",
        "exclusiveMaximum",
        "multipleOf",
        "minLength",
        "maxLength",
        "minItems",
        "maxItems",
        "minProperties",
        "maxProperties",
        "enum",
    }
)
_INTEGER_BOUNDARY_KEYS = frozenset(
    {"minLength", "maxLength", "minItems", "maxItems", "minProperties", "maxProperties"}
)
_NUMBER_BOUNDARY_KEYS = frozenset(
    {"minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum", "multipleOf"}
)
_IDEMPOTENCY_RE = re.compile(r"\b(?:idempotent|idempotency)\b", re.IGNORECASE)


def _valid_boundary_value(key: str, value: object) -> bool:
    if key == "enum":
        return isinstance(value, list) and bool(value)
    if key in _INTEGER_BOUNDARY_KEYS:
        return isinstance(value, int) and not isinstance(value, bool) and value >= 0
    if key in _NUMBER_BOUNDARY_KEYS:
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    return False


def _iter_boundary_paths(value: object, path: str) -> Iterator[str]:
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}"
            if key in _BOUNDARY_KEYS and _valid_boundary_value(key, child):
                yield child_path
            if key != "enum":
                yield from _iter_boundary_paths(child, child_path)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _iter_boundary_paths(child, f"{path}[{index}]")


def _schema_boundary_paths(schema_json: dict[str, JsonValue] | None, path: str) -> tuple[str, ...]:
    if schema_json is None:
        return ()
    return tuple(_iter_boundary_paths(schema_json, path))


def _numeric_status_code(status_code: str) -> int | None:
    value = status_code.strip()
    if len(value) != 3 or not value.isdigit():
        return None
    numeric = int(value)
    return numeric if 100 <= numeric <= 599 else None


def _required_evidence(metadata: OpenApiMetadataDetail) -> tuple[str, ...]:
    evidence: list[str] = []
    for index, parameter in enumerate(metadata.parameters):
        if parameter.required:
            evidence.append(f"parameters[{index}].required=true")
    for index, request_schema in enumerate(metadata.request_schemas):
        if request_schema.required:
            evidence.append(f"requestSchemas[{index}].required=true")
    return tuple(evidence)


def _boundary_evidence(metadata: OpenApiMetadataDetail) -> tuple[str, ...]:
    evidence: list[str] = []
    for index, parameter in enumerate(metadata.parameters):
        evidence.extend(_schema_boundary_paths(parameter.schema_, f"parameters[{index}].schema"))
    for index, request_schema in enumerate(metadata.request_schemas):
        evidence.extend(
            _schema_boundary_paths(request_schema.schema_, f"requestSchemas[{index}].schema")
        )
    return tuple(evidence)


def _response_evidence(
    metadata: OpenApiMetadataDetail,
    *,
    success: bool,
) -> tuple[str, ...]:
    evidence: list[str] = []
    for index, response in enumerate(metadata.response_schemas):
        status_code = _numeric_status_code(response.status_code)
        if status_code is None:
            continue
        is_success = 200 <= status_code <= 299
        if is_success is success:
            evidence.append(f"responseSchemas[{index}].statusCode={response.status_code}")
    return tuple(evidence)


def _auth_evidence(metadata: OpenApiMetadataDetail) -> tuple[str, ...]:
    evidence: list[str] = []
    for index, declaration in enumerate(metadata.security or []):
        if declaration:
            schemes = ",".join(sorted(declaration))
            evidence.append(f"security[{index}] declares {schemes}")
    return tuple(evidence)


def _idempotency_evidence(metadata: OpenApiMetadataDetail) -> tuple[str, ...]:
    for source, value in (
        ("summary", metadata.summary),
        ("description", metadata.description),
    ):
        if value is not None and _IDEMPOTENCY_RE.search(value):
            return (f"{source} explicitly documents idempotency",)
    return ()


def assess_strategy(
    metadata: OpenApiMetadataDetail,
    strategy: TestStrategy,
) -> StrategyApplicability:
    """Assess one strategy using only evidence present in typed metadata."""

    strategy = TestStrategy(strategy)
    if strategy is TestStrategy.HAPPY_PATH:
        evidence = _response_evidence(metadata, success=True)
    elif strategy is TestStrategy.MISSING_REQUIRED:
        evidence = _required_evidence(metadata)
    elif strategy is TestStrategy.BOUNDARY:
        evidence = _boundary_evidence(metadata)
    elif strategy is TestStrategy.AUTH_FAILURE:
        evidence = _auth_evidence(metadata)
    elif strategy is TestStrategy.IDEMPOTENCY:
        evidence = _idempotency_evidence(metadata)
    else:
        evidence = _response_evidence(metadata, success=False)
    return StrategyApplicability(
        strategy=strategy,
        applicable=bool(evidence),
        supporting_evidence=evidence,
    )


def strategy_applicability(
    metadata: OpenApiMetadataDetail,
) -> dict[TestStrategy, StrategyApplicability]:
    """Return stable applicability results in enum declaration order."""

    return {strategy: assess_strategy(metadata, strategy) for strategy in TestStrategy}


def _request_facts(
    metadata: OpenApiMetadataDetail,
    strategy: TestStrategy,
) -> tuple[RequestFact, ...]:
    facts: list[RequestFact] = []
    for index, parameter in enumerate(metadata.parameters):
        source = f"parameters[{index}]"
        boundary = _schema_boundary_paths(parameter.schema_, f"{source}.schema")
        if parameter.required or strategy is TestStrategy.BOUNDARY and boundary:
            facts.append(
                RequestFact(
                    source=source,
                    kind="PARAMETER",
                    name=parameter.name,
                    location=parameter.location,
                    required=parameter.required,
                    schema_=deepcopy(parameter.schema_),
                    example=deepcopy(parameter.example),
                )
            )
    for index, request_schema in enumerate(metadata.request_schemas):
        source = f"requestSchemas[{index}]"
        boundary = _schema_boundary_paths(request_schema.schema_, f"{source}.schema")
        if request_schema.required or strategy is TestStrategy.BOUNDARY and boundary:
            facts.append(
                RequestFact(
                    source=source,
                    kind="REQUEST_SCHEMA",
                    required=request_schema.required,
                    media_type=request_schema.media_type,
                    schema_=deepcopy(request_schema.schema_),
                )
            )
    return tuple(facts)


def _documented_responses(
    metadata: OpenApiMetadataDetail,
    strategy: TestStrategy,
) -> tuple[DocumentedResponse, ...]:
    responses: list[DocumentedResponse] = []
    for response in metadata.response_schemas:
        status_code = _numeric_status_code(response.status_code)
        if status_code is None:
            continue
        is_success = 200 <= status_code <= 299
        include = (
            (strategy is TestStrategy.HAPPY_PATH and is_success)
            or (strategy is TestStrategy.BUSINESS_ERROR and not is_success)
            or (strategy is TestStrategy.AUTH_FAILURE and status_code in {401, 403})
            or strategy is TestStrategy.IDEMPOTENCY
        )
        if include:
            responses.append(
                DocumentedResponse(
                    status_code=response.status_code,
                    description=response.description,
                    media_type=response.media_type,
                    schema_=deepcopy(response.schema_),
                )
            )
    return tuple(responses)


def _base_url(metadata: OpenApiMetadataDetail) -> str:
    for server in metadata.servers or []:
        value = server.get("url")
        if isinstance(value, str) and value.strip():
            return value.strip()
    raise ValueError("metadata must provide a non-empty server URL")


def build_generation_context(
    metadata: OpenApiMetadataDetail,
    strategy: TestStrategy,
) -> GenerationContext:
    """Build context only after the requested strategy has applicable evidence."""

    assessment = assess_strategy(metadata, strategy)
    if not assessment.applicable:
        raise ValueError(f"strategy {assessment.strategy.value} is not applicable")
    return GenerationContext(
        api_id=metadata.api_id,
        api_doc_id=metadata.api_doc_id,
        operation_id=metadata.operation_id,
        method=metadata.method,
        path=metadata.path,
        base_url=_base_url(metadata),
        strategy=assessment.strategy,
        supporting_evidence=assessment.supporting_evidence,
        request_facts=_request_facts(metadata, assessment.strategy),
        documented_responses=_documented_responses(metadata, assessment.strategy),
    )


__all__ = [
    "DocumentedResponse",
    "GenerationContext",
    "RequestFact",
    "StrategyApplicability",
    "TestStrategy",
    "assess_strategy",
    "build_generation_context",
    "strategy_applicability",
]
