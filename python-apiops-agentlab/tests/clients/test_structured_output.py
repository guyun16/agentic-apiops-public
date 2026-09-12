from __future__ import annotations

import copy

import pytest

from app.clients.llm import (
    LLMClient,
    StructuredLLMClient,
    StructuredOutputSpec,
    complete_with_structured_output,
)
from app.clients.qwen_structured_output import (
    DIAGNOSIS_REPORT_PROVIDER_SCHEMA,
    DIAGNOSIS_REPORT_SOURCE_SCHEMA,
    TESTCASE_CANDIDATE_OUTPUT_SPEC,
    SchemaProjectionError,
    project_provider_schema,
    schema_digest,
)


class _LegacyClient:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def complete(self, prompt: str) -> str:
        self.calls.append(prompt)
        return '{"legacy":true}'


class _StructuredClient(_LegacyClient):
    def __init__(self) -> None:
        super().__init__()
        self.structured_calls: list[tuple[str, StructuredOutputSpec]] = []

    async def complete_structured(
        self,
        prompt: str,
        *,
        output_spec: StructuredOutputSpec,
    ) -> str:
        self.structured_calls.append((prompt, output_spec))
        return '{"native":true}'


@pytest.mark.anyio
async def test_structured_helper_falls_back_only_when_native_is_optional() -> None:
    client = _LegacyClient()
    spec = TESTCASE_CANDIDATE_OUTPUT_SPEC

    assert isinstance(client, LLMClient)
    assert not isinstance(client, StructuredLLMClient)
    assert await complete_with_structured_output(client, "legacy", output_spec=spec) == (
        '{"legacy":true}'
    )
    assert client.calls == ["legacy"]


@pytest.mark.anyio
async def test_structured_helper_fails_closed_when_native_is_required() -> None:
    client = _LegacyClient()

    with pytest.raises(TypeError, match="native structured output is not supported"):
        await complete_with_structured_output(
            client,
            "native required",
            output_spec=TESTCASE_CANDIDATE_OUTPUT_SPEC,
            native_required=True,
        )
    assert client.calls == []


@pytest.mark.anyio
async def test_structured_helper_uses_native_capability_when_available() -> None:
    client = _StructuredClient()
    spec = TESTCASE_CANDIDATE_OUTPUT_SPEC

    assert isinstance(client, StructuredLLMClient)
    assert await complete_with_structured_output(
        client,
        "native",
        output_spec=spec,
        native_required=True,
    ) == '{"native":true}'
    assert client.calls == []
    assert client.structured_calls == [("native", spec)]


def test_diagnosis_projection_is_derived_without_mutating_source() -> None:
    source = copy.deepcopy(DIAGNOSIS_REPORT_SOURCE_SCHEMA)

    projection = project_provider_schema(source)

    assert source == DIAGNOSIS_REPORT_SOURCE_SCHEMA
    assert projection.schema == DIAGNOSIS_REPORT_PROVIDER_SCHEMA
    assert "$defs" not in projection.schema
    assert all(
        "$ref" not in node
        for node in _mapping_nodes(projection.schema)
    )
    assert projection.schema["properties"]["schemaVersion"] == {
        "type": "string",
        "enum": ["0.1.0"],
    }
    assert {"type", "properties", "required", "additionalProperties", "description"}.issubset(
        projection.schema
    )
    assert {"minLength", "minItems", "minimum", "title"}.issubset(
        set(projection.dropped_provider_keywords)
    )


def test_projection_inlines_refs_preserves_shape_and_projects_const() -> None:
    source = {
        "$defs": {
            "Item": {
                "title": "Item",
                "type": "object",
                "properties": {
                    "value": {"const": "fixed", "title": "Value"},
                    "tags": {
                        "type": "array",
                        "items": {"enum": ["a", "b"], "type": "string"},
                    },
                },
                "required": ["value", "tags"],
                "additionalProperties": False,
            }
        },
        "type": "object",
        "properties": {"item": {"$ref": "#/$defs/Item"}},
        "required": ["item"],
        "additionalProperties": False,
    }

    result = project_provider_schema(source)

    assert result.schema == {
        "type": "object",
        "properties": {
            "item": {
                "type": "object",
                "properties": {
                    "value": {"enum": ["fixed"]},
                    "tags": {
                        "type": "array",
                        "items": {"enum": ["a", "b"], "type": "string"},
                    },
                },
                "required": ["value", "tags"],
                "additionalProperties": False,
            }
        },
        "required": ["item"],
        "additionalProperties": False,
    }
    assert result.dropped_provider_keywords == ("title",)


def test_projection_converts_only_simple_nullable_anyof() -> None:
    source = {
        "type": "object",
        "properties": {
            "note": {"anyOf": [{"type": "string"}, {"type": "null"}]},
        },
        "required": ["note"],
        "additionalProperties": False,
    }

    assert project_provider_schema(source).schema["properties"] == {
        "note": {"type": ["string", "null"]}
    }


@pytest.mark.parametrize(
    "source",
    (
        {
            "$defs": {
                "Node": {
                    "type": "object",
                    "properties": {"child": {"$ref": "#/$defs/Node"}},
                }
            },
            "$ref": "#/$defs/Node",
        },
        {
            "type": "object",
            "properties": {"value": {"oneOf": [{"type": "string"}, {"type": "integer"}]}},
        },
        {
            "type": "object",
            "properties": {"value": {"anyOf": [{"type": "string"}, {"type": "integer"}]}},
        },
    ),
)
def test_projection_fails_closed_on_ambiguous_structural_schema(source: dict[str, object]) -> None:
    with pytest.raises(SchemaProjectionError):
        project_provider_schema(source)


def test_testcase_spec_is_only_a_native_root_object_constraint() -> None:
    assert TESTCASE_CANDIDATE_OUTPUT_SPEC.schema == {
        "type": "object",
        "additionalProperties": True,
    }
    assert TESTCASE_CANDIDATE_OUTPUT_SPEC.schema_name == "testcase_candidate_object_v1"
    assert TESTCASE_CANDIDATE_OUTPUT_SPEC.strict is True


def test_schema_digest_is_stable_and_does_not_depend_on_mapping_order() -> None:
    first = {"type": "object", "properties": {"a": {"type": "string"}}}
    second = {"properties": {"a": {"type": "string"}}, "type": "object"}

    assert schema_digest(first) == schema_digest(second)
    assert len(schema_digest(first)) == 64


def _mapping_nodes(value: object) -> list[dict[str, object]]:
    if isinstance(value, dict):
        return [value, *[node for child in value.values() for node in _mapping_nodes(child)]]
    if isinstance(value, list):
        return [node for child in value for node in _mapping_nodes(child)]
    return []
