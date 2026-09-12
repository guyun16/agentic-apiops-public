"""Small deterministic JSON Schema projections for Qwen native output."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from copy import deepcopy
from dataclasses import dataclass

from app.clients.llm import StructuredOutputSpec
from app.schemas.diagnosis_report import DiagnosisReport

_PRIMITIVE_TYPES = frozenset(
    {"string", "number", "integer", "boolean", "object", "array"}
)
_DROPPED_KEYWORDS = frozenset(
    {
        "$id",
        "$schema",
        "default",
        "deprecated",
        "exclusiveMaximum",
        "exclusiveMinimum",
        "examples",
        "format",
        "maxItems",
        "maxLength",
        "maxProperties",
        "maximum",
        "minItems",
        "minLength",
        "minProperties",
        "minimum",
        "multipleOf",
        "pattern",
        "readOnly",
        "title",
        "writeOnly",
    }
)
_STRUCTURAL_KEYWORDS = frozenset(
    {
        "allOf",
        "contains",
        "dependentSchemas",
        "else",
        "if",
        "not",
        "oneOf",
        "patternProperties",
        "prefixItems",
        "propertyNames",
        "then",
        "unevaluatedItems",
        "unevaluatedProperties",
    }
)


class SchemaProjectionError(ValueError):
    """The source schema cannot be projected without changing its shape."""


@dataclass(frozen=True, slots=True)
class SchemaProjection:
    """Projected provider schema and the non-structural keywords removed."""

    schema: dict[str, object]
    dropped_provider_keywords: tuple[str, ...]


def project_provider_schema(source: Mapping[str, object]) -> SchemaProjection:
    """Project a Pydantic JSON Schema to the documented Qwen keyword subset."""

    if not isinstance(source, Mapping):
        raise TypeError("source schema must be a mapping")
    definitions = source.get("$defs", {})
    if not isinstance(definitions, Mapping):
        raise SchemaProjectionError("$defs must be an object")
    dropped: set[str] = set()

    def local_definition(reference: str) -> Mapping[str, object]:
        parts = reference.split("/")
        if len(parts) != 3 or parts[0] != "#" or parts[1] != "$defs":
            raise SchemaProjectionError(f"unsupported schema reference: {reference}")
        name = parts[2].replace("~1", "/").replace("~0", "~")
        definition = definitions.get(name)
        if not isinstance(definition, Mapping):
            raise SchemaProjectionError(f"unknown local schema reference: {reference}")
        return definition

    def walk(
        node: object,
        *,
        path: str,
        reference_stack: tuple[str, ...] = (),
    ) -> dict[str, object]:
        if not isinstance(node, Mapping):
            raise SchemaProjectionError(f"schema node at {path or '/'} must be an object")
        reference = node.get("$ref")
        if reference is not None:
            if not isinstance(reference, str):
                raise SchemaProjectionError(f"schema reference at {path or '/'} must be a string")
            if reference in reference_stack:
                raise SchemaProjectionError(f"cyclic local schema reference: {reference}")
            if len(node) != 1:
                raise SchemaProjectionError(
                    f"schema reference at {path or '/'} cannot have sibling keywords"
                )
            return walk(
                local_definition(reference),
                path=path,
                reference_stack=reference_stack + (reference,),
            )

        result: dict[str, object] = {}
        for raw_key, raw_value in node.items():
            if not isinstance(raw_key, str):
                raise SchemaProjectionError(f"schema keyword at {path or '/'} must be a string")
            if raw_key == "$defs":
                continue
            if raw_key in _DROPPED_KEYWORDS:
                dropped.add(raw_key)
                continue
            if raw_key in _STRUCTURAL_KEYWORDS:
                raise SchemaProjectionError(
                    f"unsupported structural JSON Schema keyword: {raw_key}"
                )
            if raw_key == "anyOf":
                result.update(
                    _project_nullable(
                        raw_value,
                        path=path,
                        walk=walk,
                        reference_stack=reference_stack,
                    )
                )
                continue
            if raw_key == "const":
                if "enum" in node:
                    raise SchemaProjectionError(f"const and enum conflict at {path or '/'}")
                result["enum"] = [deepcopy(raw_value)]
                continue
            if raw_key == "type":
                if isinstance(raw_value, str) and raw_value in _PRIMITIVE_TYPES:
                    result[raw_key] = raw_value
                    continue
                if isinstance(raw_value, list) and all(
                    isinstance(value, str)
                    and (value in _PRIMITIVE_TYPES or value == "null")
                    for value in raw_value
                ):
                    result[raw_key] = deepcopy(raw_value)
                    continue
                raise SchemaProjectionError(f"unsupported type at {path or '/'}")
            if raw_key == "properties":
                if not isinstance(raw_value, Mapping):
                    raise SchemaProjectionError(f"properties at {path or '/'} must be an object")
                result[raw_key] = {
                    name: walk(value, path=f"{path}/{name}", reference_stack=reference_stack)
                    for name, value in raw_value.items()
                }
                continue
            if raw_key == "required":
                if not isinstance(raw_value, list) or not all(
                    isinstance(value, str) for value in raw_value
                ):
                    raise SchemaProjectionError(f"required at {path or '/'} must be string list")
                result[raw_key] = list(raw_value)
                continue
            if raw_key == "items":
                result[raw_key] = walk(
                    raw_value,
                    path=f"{path}/items",
                    reference_stack=reference_stack,
                )
                continue
            if raw_key == "additionalProperties":
                if isinstance(raw_value, bool):
                    result[raw_key] = raw_value
                elif isinstance(raw_value, Mapping):
                    result[raw_key] = walk(
                        raw_value,
                        path=f"{path}/additionalProperties",
                        reference_stack=reference_stack,
                    )
                else:
                    raise SchemaProjectionError(
                        f"additionalProperties at {path or '/'} must be boolean or object"
                    )
                continue
            if raw_key == "enum":
                if not isinstance(raw_value, list):
                    raise SchemaProjectionError(f"enum at {path or '/'} must be a list")
                result[raw_key] = deepcopy(raw_value)
                continue
            if raw_key == "description":
                if not isinstance(raw_value, str):
                    raise SchemaProjectionError(
                        f"description at {path or '/'} must be a string"
                    )
                result[raw_key] = raw_value
                continue
            raise SchemaProjectionError(f"unsupported JSON Schema keyword: {raw_key}")
        return result

    projected = walk(source, path="")
    return SchemaProjection(
        schema=projected,
        dropped_provider_keywords=tuple(sorted(dropped)),
    )


def _project_nullable(
    raw_value: object,
    *,
    path: str,
    walk: Callable[..., dict[str, object]],
    reference_stack: tuple[str, ...],
) -> dict[str, object]:
    if not isinstance(raw_value, list) or len(raw_value) != 2:
        raise SchemaProjectionError(f"unsupported JSON Schema anyOf at {path or '/'}")
    branches = [value for value in raw_value if isinstance(value, Mapping)]
    if len(branches) != 2:
        raise SchemaProjectionError(f"unsupported JSON Schema anyOf at {path or '/'}")
    null_branches = [branch for branch in branches if branch.get("type") == "null"]
    value_branches = [branch for branch in branches if branch.get("type") != "null"]
    if len(null_branches) != 1 or len(value_branches) != 1:
        raise SchemaProjectionError(f"unsupported JSON Schema anyOf at {path or '/'}")
    value_branch = value_branches[0]
    value_type = value_branch.get("type")
    if not isinstance(value_type, str) or value_type not in _PRIMITIVE_TYPES:
        raise SchemaProjectionError(f"unsupported nullable schema at {path or '/'}")
    projected = walk(value_branch, path=path, reference_stack=reference_stack)
    projected["type"] = [value_type, "null"]
    return projected


def schema_digest(schema: Mapping[str, object]) -> str:
    """Reuse the existing trace canonicalization for a stable schema identity."""

    from app.tracing.redaction import canonical_json_hash

    return canonical_json_hash(schema)


_DIAGNOSIS_PROJECTION = project_provider_schema(DiagnosisReport.model_json_schema(by_alias=True))
DIAGNOSIS_REPORT_SCHEMA_NAME = "diagnosis_report_v1"
DIAGNOSIS_REPORT_OUTPUT_SPEC = StructuredOutputSpec(
    schema_name=DIAGNOSIS_REPORT_SCHEMA_NAME,
    schema=_DIAGNOSIS_PROJECTION.schema,
    strict=True,
)
DIAGNOSIS_REPORT_SOURCE_SCHEMA = deepcopy(DiagnosisReport.model_json_schema(by_alias=True))
DIAGNOSIS_REPORT_PROVIDER_SCHEMA = deepcopy(_DIAGNOSIS_PROJECTION.schema)
DIAGNOSIS_REPORT_DROPPED_PROVIDER_KEYWORDS = _DIAGNOSIS_PROJECTION.dropped_provider_keywords

TESTCASE_CANDIDATE_SCHEMA_NAME = "testcase_candidate_object_v1"
TESTCASE_CANDIDATE_OUTPUT_SPEC = StructuredOutputSpec(
    schema_name=TESTCASE_CANDIDATE_SCHEMA_NAME,
    schema={"type": "object", "additionalProperties": True},
    strict=True,
)


__all__ = [
    "DIAGNOSIS_REPORT_DROPPED_PROVIDER_KEYWORDS",
    "DIAGNOSIS_REPORT_OUTPUT_SPEC",
    "DIAGNOSIS_REPORT_PROVIDER_SCHEMA",
    "DIAGNOSIS_REPORT_SCHEMA_NAME",
    "DIAGNOSIS_REPORT_SOURCE_SCHEMA",
    "SchemaProjection",
    "SchemaProjectionError",
    "TESTCASE_CANDIDATE_OUTPUT_SPEC",
    "TESTCASE_CANDIDATE_SCHEMA_NAME",
    "project_provider_schema",
    "schema_digest",
]
