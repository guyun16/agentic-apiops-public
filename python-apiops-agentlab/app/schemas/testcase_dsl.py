"""Strict Pydantic v2 views for the shared TestCase DSL contract."""

from __future__ import annotations

from typing import Any, Literal, TypeAlias

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictFloat,
    StrictInt,
    StrictStr,
)
from pydantic.experimental.missing_sentinel import MISSING
from typing_extensions import TypeAliasType

JsonValue = TypeAliasType(
    "JsonValue",
    None
    | StrictBool
    | StrictInt
    | StrictFloat
    | StrictStr
    | list["JsonValue"]
    | dict[StrictStr, "JsonValue"],
)


class _ContractModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        populate_by_name=False,
        strict=True,
    )

    def model_dump(self, **kwargs: Any) -> dict[str, Any]:
        kwargs.setdefault("by_alias", True)
        return super().model_dump(**kwargs)


class Environment(_ContractModel):
    """Execution environment for a TestCase DSL document."""

    base_url: StrictStr = Field(alias="baseUrl", min_length=1)
    variables: dict[StrictStr, StrictStr]


class StatusCodeAssertion(_ContractModel):
    type: Literal["STATUS_CODE"]
    expected: StrictInt = Field(ge=100, le=599)


class HeaderAssertion(_ContractModel):
    type: Literal["HEADER"]
    name: StrictStr = Field(min_length=1)
    operator: Literal["EQUALS", "CONTAINS"]
    expected: StrictStr


class JsonPathEqualsAssertion(_ContractModel):
    type: Literal["JSON_PATH"]
    expression: StrictStr = Field(min_length=1)
    operator: Literal["EQUALS"]
    expected: JsonValue


class JsonPathExistsAssertion(_ContractModel):
    type: Literal["JSON_PATH"]
    expression: StrictStr = Field(min_length=1)
    operator: Literal["EXISTS"]


class ResponseTimeAssertion(_ContractModel):
    type: Literal["RESPONSE_TIME"]
    max_ms: StrictInt = Field(alias="maxMs", ge=1)


AssertionSpec: TypeAlias = (
    StatusCodeAssertion
    | HeaderAssertion
    | JsonPathEqualsAssertion
    | JsonPathExistsAssertion
    | ResponseTimeAssertion
)


class RequestSpec(_ContractModel):
    """Request fields with contract-defined dynamic maps and JSON body."""

    method: Literal[
        "GET",
        "POST",
        "PUT",
        "DELETE",
        "PATCH",
        "HEAD",
        "OPTIONS",
        "TRACE",
    ]
    path: StrictStr = Field(min_length=1)
    path_params: dict[StrictStr, JsonValue] | MISSING = Field(
        default=MISSING,
        alias="pathParams",
    )
    query: dict[StrictStr, JsonValue] | MISSING = MISSING
    headers: dict[StrictStr, StrictStr] | MISSING = MISSING
    body: JsonValue | MISSING = MISSING


class ExtractorSpec(_ContractModel):
    name: StrictStr = Field(min_length=1)
    expression: StrictStr = Field(min_length=1)


class TestStep(_ContractModel):
    step_id: StrictStr = Field(alias="stepId", min_length=1)
    name: StrictStr = Field(min_length=1)
    request: RequestSpec
    assertions: list[AssertionSpec] = Field(min_length=1)
    extractors: list[ExtractorSpec]


class TestCaseDSL(_ContractModel):
    """Typed view of shared-schemas/testcase-dsl-schema.json."""

    schema_version: Literal["1.0.0"] = Field(alias="schemaVersion")
    case_id: StrictStr = Field(alias="caseId", min_length=1)
    project_id: StrictInt = Field(alias="projectId", ge=0)
    api_id: StrictStr = Field(alias="apiId", min_length=1)
    name: StrictStr = Field(min_length=1)
    environment: Environment
    description: StrictStr | MISSING = MISSING
    tags: list[StrictStr] | MISSING = MISSING
    steps: list[TestStep] = Field(min_length=1)
