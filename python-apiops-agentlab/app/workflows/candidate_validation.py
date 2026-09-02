"""Deterministic Contract and context validation for generated candidates."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Literal

from jsonschema import ValidationError as JsonSchemaValidationError
from jsonschema.validators import validator_for
from pydantic import BaseModel, ConfigDict, StrictStr, ValidationError, computed_field

from app.agents.testcase_generator import Candidate
from app.schemas.testcase_dsl import TestCaseDSL
from app.workflows.generation_context import GenerationContext

ValidationLayer = Literal["PARSE", "SCHEMA", "SEMANTIC"]


class ValidationIssue(BaseModel):
    """One stable, machine-readable candidate validation failure."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    code: StrictStr
    path: StrictStr
    layer: ValidationLayer
    message: StrictStr


class CandidateValidationResult(BaseModel):
    """Validation result whose validity is derived only from its issues."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    issues: tuple[ValidationIssue, ...] = ()

    @computed_field
    @property
    def valid(self) -> bool:
        return not self.issues


_SCHEMA_PATH = Path(__file__).resolve().parents[3] / "shared-schemas" / "testcase-dsl-schema.json"
_loaded_schema = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
if not isinstance(_loaded_schema, dict):
    raise RuntimeError("shared TestCase schema must be a JSON object")
_TESTCASE_SCHEMA: dict[str, object] = _loaded_schema
_validator_class = validator_for(_TESTCASE_SCHEMA)
_validator_class.check_schema(_TESTCASE_SCHEMA)
_SCHEMA_VALIDATOR = _validator_class(_TESTCASE_SCHEMA)


def _pointer(path: str, token: object) -> str:
    escaped = str(token).replace("~", "~0").replace("/", "~1")
    return f"{path}/{escaped}"


def _display_path(path: str) -> str:
    return path or "/"


def _schema_code(keyword: str) -> str:
    codes = {
        "additionalProperties": "SHARED_SCHEMA_ADDITIONAL_PROPERTY",
        "const": "SHARED_SCHEMA_CONST",
        "enum": "SHARED_SCHEMA_ENUM",
        "maximum": "SHARED_SCHEMA_MAXIMUM",
        "minimum": "SHARED_SCHEMA_MINIMUM",
        "minItems": "SHARED_SCHEMA_MIN_ITEMS",
        "minLength": "SHARED_SCHEMA_MIN_LENGTH",
        "oneOf": "SHARED_SCHEMA_ONE_OF",
        "required": "SHARED_SCHEMA_REQUIRED",
        "type": "SHARED_SCHEMA_TYPE",
    }
    return codes.get(keyword, "SHARED_SCHEMA_VIOLATION")


def _schema_message(keyword: str) -> str:
    messages = {
        "additionalProperties": "Additional property is not allowed.",
        "const": "Value does not equal the required constant.",
        "enum": "Value is not one of the allowed values.",
        "maximum": "Number is above the allowed maximum.",
        "minimum": "Number is below the allowed minimum.",
        "minItems": "Array has fewer items than allowed.",
        "minLength": "String is shorter than allowed.",
        "oneOf": "Value must match exactly one shared-schema variant.",
        "required": "Required property is missing.",
        "type": "Value has the wrong JSON type.",
    }
    return messages.get(keyword, "Candidate violates the shared TestCase schema.")


def _error_paths(error: JsonSchemaValidationError) -> tuple[str, ...]:
    path = ""
    for token in error.absolute_path:
        path = _pointer(path, token)

    if error.validator == "required" and isinstance(error.instance, dict):
        required = error.validator_value
        if isinstance(required, list):
            missing = [name for name in required if name not in error.instance]
            return tuple(_pointer(path, name) for name in missing)

    if error.validator == "additionalProperties" and isinstance(error.instance, dict):
        properties = error.schema.get("properties", {})
        if isinstance(properties, dict):
            extras = sorted(set(error.instance) - set(properties))
            return tuple(_pointer(path, name) for name in extras)

    return (_display_path(path),)


def _schema_issues(value: object) -> tuple[ValidationIssue, ...]:
    errors = sorted(
        _SCHEMA_VALIDATOR.iter_errors(value),
        key=lambda error: (
            tuple(str(token) for token in error.absolute_path),
            str(error.validator),
            error.message,
        ),
    )
    issues: list[ValidationIssue] = []
    seen: set[tuple[str, str]] = set()
    for error in errors:
        keyword = str(error.validator)
        code = _schema_code(keyword)
        for path in _error_paths(error):
            key = (code, path)
            if key in seen:
                continue
            seen.add(key)
            issues.append(
                ValidationIssue(
                    code=code,
                    path=path,
                    layer="SCHEMA",
                    message=_schema_message(keyword),
                )
            )
    return tuple(issues)


def _parse_issues(error: ValidationError) -> tuple[ValidationIssue, ...]:
    issues: list[ValidationIssue] = []
    for detail in error.errors(include_url=False, include_context=False, include_input=False):
        path = ""
        for token in detail["loc"]:
            path = _pointer(path, token)
        issues.append(
            ValidationIssue(
                code="TESTCASE_TYPED_PARSE_FAILED",
                path=_display_path(path),
                layer="PARSE",
                message="Candidate does not match the typed TestCaseDSL view.",
            )
        )
    return tuple(issues)


def _semantic_issues(
    testcase: TestCaseDSL,
    *,
    project_id: int,
    generation_context: GenerationContext,
) -> Iterator[ValidationIssue]:
    if testcase.project_id != project_id:
        yield ValidationIssue(
            code="PROJECT_ID_MISMATCH",
            path="/projectId",
            layer="SEMANTIC",
            message="Candidate projectId does not match the requested project context.",
        )
    if testcase.api_id != generation_context.api_id:
        yield ValidationIssue(
            code="API_ID_MISMATCH",
            path="/apiId",
            layer="SEMANTIC",
            message="Candidate apiId does not match the generation context.",
        )
    for index, step in enumerate(testcase.steps):
        request_path = f"/steps/{index}/request"
        if step.request.method != generation_context.method:
            yield ValidationIssue(
                code="METHOD_MISMATCH",
                path=f"{request_path}/method",
                layer="SEMANTIC",
                message="Candidate request method does not match the target operation.",
            )
        if step.request.path != generation_context.path:
            yield ValidationIssue(
                code="PATH_MISMATCH",
                path=f"{request_path}/path",
                layer="SEMANTIC",
                message="Candidate request path does not match the target operation.",
            )


def validate_candidate(
    candidate: Candidate,
    *,
    project_id: int,
    generation_context: GenerationContext,
) -> CandidateValidationResult:
    """Validate one immutable candidate without model or runner calls."""

    issues = list(_schema_issues(candidate.structured))
    try:
        testcase = TestCaseDSL.model_validate(candidate.structured)
    except ValidationError as exc:
        if not issues:
            issues.extend(_parse_issues(exc))
        return CandidateValidationResult(issues=tuple(issues))

    issues.extend(
        _semantic_issues(
            testcase,
            project_id=project_id,
            generation_context=generation_context,
        )
    )
    return CandidateValidationResult(issues=tuple(issues))


__all__ = [
    "CandidateValidationResult",
    "ValidationIssue",
    "ValidationLayer",
    "validate_candidate",
]
