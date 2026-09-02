"""Shared ToolResult compatibility tests."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.schemas.tool_result import ToolResult

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
EXAMPLES_ROOT = REPOSITORY_ROOT / "examples"
VALID_FIXTURE = EXAMPLES_ROOT / "tool-result-valid.json"
INVALID_UNKNOWN_FIELD_FIXTURE = EXAMPLES_ROOT / "invalid" / "tool-result-unknown-field.json"

TOOL_RESULT_STATUSES = (
    "SUCCESS",
    "FAILED",
    "FORBIDDEN",
    "TIMEOUT",
    "PARAM_INVALID",
    "RESULT_INVALID",
)


def load_fixture(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def test_canonical_tool_result_fixture_passes() -> None:
    model = ToolResult.model_validate(load_fixture(VALID_FIXTURE))

    assert model.schema_version == "0.1.0"
    assert model.status == "SUCCESS"
    assert model.sanitized is True
    assert model.error is None


def test_canonical_tool_result_round_trip_preserves_contract_semantics() -> None:
    fixture = load_fixture(VALID_FIXTURE)
    dumped = ToolResult.model_validate(fixture).model_dump(by_alias=True)

    assert dumped == fixture
    assert dumped["schemaVersion"] == "0.1.0"
    assert dumped["toolCallId"] == "tool_call_001"
    assert dumped["status"] == "SUCCESS"
    assert dumped["data"]["rows"][0]["id"] == "order_001"
    assert dumped["error"] is None
    assert dumped["sanitized"] is True
    assert dumped["traceId"] == "trace_001"
    assert "tool_call_id" not in dumped


def test_unknown_top_level_field_fixture_fails() -> None:
    with pytest.raises(ValidationError):
        ToolResult.model_validate(load_fixture(INVALID_UNKNOWN_FIELD_FIXTURE))


def test_unsupported_schema_version_is_rejected() -> None:
    payload = load_fixture(VALID_FIXTURE)
    payload["schemaVersion"] = "9.9.9"

    with pytest.raises(ValidationError):
        ToolResult.model_validate(payload)


@pytest.mark.parametrize("status", TOOL_RESULT_STATUSES)
def test_all_shared_tool_result_statuses_are_accepted(status: str) -> None:
    payload = load_fixture(VALID_FIXTURE)
    payload["status"] = status

    model = ToolResult.model_validate(payload)

    assert model.status == status


@pytest.mark.parametrize("status", ("DENIED", "INVALID", "banana"))
def test_unknown_tool_result_status_is_rejected(status: str) -> None:
    payload = load_fixture(VALID_FIXTURE)
    payload["status"] = status

    with pytest.raises(ValidationError):
        ToolResult.model_validate(payload)


@pytest.mark.parametrize(
    "field",
    ("schemaVersion", "toolCallId", "status", "data", "error", "sanitized", "traceId"),
)
def test_required_fields_cannot_be_missing(field: str) -> None:
    payload = load_fixture(VALID_FIXTURE)
    del payload[field]

    with pytest.raises(ValidationError):
        ToolResult.model_validate(payload)


@pytest.mark.parametrize("data", (None, "value", 7, 1.5, True, [], {}))
def test_data_accepts_json_values(data: object) -> None:
    payload = load_fixture(VALID_FIXTURE)
    payload["data"] = data

    model = ToolResult.model_validate(payload)

    assert model.data == data


def test_data_and_error_null_round_trip_without_dropping_required_fields() -> None:
    payload = load_fixture(VALID_FIXTURE)
    payload["data"] = None
    payload["error"] = None

    dumped = ToolResult.model_validate(payload).model_dump(by_alias=True)

    assert dumped["data"] is None
    assert dumped["error"] is None


def test_error_accepts_open_json_object_or_null() -> None:
    payload = load_fixture(VALID_FIXTURE)
    payload["error"] = {
        "code": "TOOL_TIMEOUT",
        "message": "tool execution timed out",
        "details": {"retryable": False},
    }

    model = ToolResult.model_validate(payload)

    assert model.error == payload["error"]
    assert ToolResult.model_validate({**payload, "error": {}}).error == {}
    assert ToolResult.model_validate({**payload, "error": None}).error is None


@pytest.mark.parametrize("error", ("failed", []))
def test_error_rejects_non_object_non_null_values(error: object) -> None:
    payload = load_fixture(VALID_FIXTURE)
    payload["error"] = error

    with pytest.raises(ValidationError):
        ToolResult.model_validate(payload)


@pytest.mark.parametrize("sanitized", (True, False))
def test_sanitized_accepts_only_json_boolean_values(sanitized: bool) -> None:
    payload = load_fixture(VALID_FIXTURE)
    payload["sanitized"] = sanitized

    model = ToolResult.model_validate(payload)

    assert model.sanitized is sanitized


@pytest.mark.parametrize("sanitized", (1, 0, "true"))
def test_sanitized_rejects_non_boolean_coercion(sanitized: object) -> None:
    payload = load_fixture(VALID_FIXTURE)
    payload["sanitized"] = sanitized

    with pytest.raises(ValidationError):
        ToolResult.model_validate(payload)


def test_non_json_python_object_is_rejected_from_data() -> None:
    payload = copy.deepcopy(load_fixture(VALID_FIXTURE))
    payload["data"] = {"not_json": object()}

    with pytest.raises(ValidationError):
        ToolResult.model_validate(payload)


def test_string_fields_reject_numeric_coercion() -> None:
    payload = load_fixture(VALID_FIXTURE)
    payload["toolCallId"] = 123

    with pytest.raises(ValidationError):
        ToolResult.model_validate(payload)


def test_snake_case_input_is_not_silently_accepted() -> None:
    payload = load_fixture(VALID_FIXTURE)
    payload["tool_call_id"] = payload.pop("toolCallId")

    with pytest.raises(ValidationError):
        ToolResult.model_validate(payload)
