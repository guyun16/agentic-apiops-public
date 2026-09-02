"""Strict typed view of the Java OpenAPI metadata response data."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictStr

from .testcase_dsl import JsonValue


class _OpenApiMetadataModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        populate_by_name=False,
        strict=True,
    )

    def model_dump(self, **kwargs: Any) -> dict[str, Any]:
        kwargs.setdefault("by_alias", True)
        return super().model_dump(**kwargs)


class ParameterMetadata(_OpenApiMetadataModel):
    name: StrictStr
    location: Literal["path", "query", "header", "cookie"]
    required: StrictBool
    description: StrictStr | None
    schema_: dict[StrictStr, JsonValue] | None = Field(alias="schema")
    example: JsonValue


class RequestSchemaMetadata(_OpenApiMetadataModel):
    required: StrictBool
    media_type: StrictStr = Field(alias="mediaType")
    schema_: dict[StrictStr, JsonValue] | None = Field(alias="schema")


class ResponseSchemaMetadata(_OpenApiMetadataModel):
    status_code: StrictStr = Field(alias="statusCode")
    description: StrictStr | None
    media_type: StrictStr = Field(alias="mediaType")
    schema_: dict[StrictStr, JsonValue] | None = Field(alias="schema")


class ExampleOwnerMetadata(_OpenApiMetadataModel):
    type: Literal["PARAMETER", "REQUEST_SCHEMA", "RESPONSE_SCHEMA"]
    parameter_name: StrictStr | None = Field(alias="parameterName")
    parameter_location: StrictStr | None = Field(alias="parameterLocation")
    media_type: StrictStr | None = Field(alias="mediaType")
    status_code: StrictStr | None = Field(alias="statusCode")


class ExampleMetadata(_OpenApiMetadataModel):
    owner: ExampleOwnerMetadata
    example_name: StrictStr = Field(alias="exampleName")
    summary: StrictStr | None
    description: StrictStr | None
    value: JsonValue


class OpenApiMetadataDetail(_OpenApiMetadataModel):
    """Typed view of ``ApiMetadataDetailVO`` and its shared JSON Schema."""

    api_id: StrictStr = Field(alias="apiId")
    api_doc_id: StrictStr = Field(alias="apiDocId")
    operation_id: StrictStr | None = Field(alias="operationId")
    method: StrictStr
    path: StrictStr
    summary: StrictStr | None
    description: StrictStr | None
    tags: list[StrictStr] | None
    servers: list[dict[StrictStr, JsonValue]] | None
    security: list[dict[StrictStr, JsonValue]] | None
    deprecated: StrictBool
    parameters: list[ParameterMetadata]
    request_schemas: list[RequestSchemaMetadata] = Field(alias="requestSchemas")
    response_schemas: list[ResponseSchemaMetadata] = Field(alias="responseSchemas")
    examples: list[ExampleMetadata]
