"""Shared ToolCall compatibility tests."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.schemas.tool_call import ToolCall

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
EXAMPLES_ROOT = REPOSITORY_ROOT / "examples"
VALID_FIXTURE = EXAMPLES_ROOT / "tool-call-valid.json"
INVALID_UNKNOWN_FIELD_FIXTURE = EXAMPLES_ROOT / "invalid" / "tool-call-unknown-field.json"
INVALID_LEGACY_NAME_FIXTURE = EXAMPLES_ROOT / "invalid" / "tool-call-legacy-tool-name.json"

TOOL_NAMES = (
    "openapi.metadata.read",
    "testcase.validate",
    "runner.submit",
    "report.read",
    "sql.read",
    "redis.read",
    "log.search",
    "rag.search",
)
AUTHORITY_FIELDS = (
    "userId",
    "role",
    "permission",
    "authorities",
    "trustedProjectId",
    "datasource",
    "allowedHost",
    "securityPolicy",
)


def load_fixture(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def test_canonical_tool_call_fixture_passes() -> None:
    model = ToolCall.model_validate(load_fixture(VALID_FIXTURE))

    assert model.schema_version == "0.2.0"
    assert model.project_id == "42"
    assert model.tool_name == "sql.read"
    assert model.params["query"] == "select id, status from orders where id = ?"


def test_canonical_tool_call_round_trip_preserves_contract_semantics() -> None:
    fixture = load_fixture(VALID_FIXTURE)
    dumped = ToolCall.model_validate(fixture).model_dump(by_alias=True)

    assert dumped == fixture
    assert dumped["schemaVersion"] == "0.2.0"
    assert dumped["agentRunId"] == "agent_run_001"
    assert dumped["projectId"] == "42"
    assert dumped["toolName"] == "sql.read"
    assert dumped["params"]["args"] == ["order_001"]
    assert dumped["traceId"] == "trace_001"
    assert "tool_call_id" not in dumped


def test_unknown_top_level_field_fixture_fails() -> None:
    with pytest.raises(ValidationError):
        ToolCall.model_validate(load_fixture(INVALID_UNKNOWN_FIELD_FIXTURE))


def test_unsupported_schema_version_is_rejected() -> None:
    payload = load_fixture(VALID_FIXTURE)
    payload["schemaVersion"] = "9.9.9"

    with pytest.raises(ValidationError):
        ToolCall.model_validate(payload)


def test_params_must_be_a_json_object() -> None:
    payload = load_fixture(VALID_FIXTURE)
    payload["params"] = ["not", "an", "object"]

    with pytest.raises(ValidationError):
        ToolCall.model_validate(payload)


def test_legacy_tool_name_fixture_fails() -> None:
    with pytest.raises(ValidationError):
        ToolCall.model_validate(load_fixture(INVALID_LEGACY_NAME_FIXTURE))


@pytest.mark.parametrize(
    "field",
    (
        "schemaVersion",
        "agentRunId",
        "projectId",
        "toolName",
        "params",
        "traceId",
    ),
)
def test_required_fields_cannot_be_missing(field: str) -> None:
    payload = load_fixture(VALID_FIXTURE)
    del payload[field]

    with pytest.raises(ValidationError):
        ToolCall.model_validate(payload)


def test_optional_agent_step_id_can_be_missing_but_not_null() -> None:
    payload = load_fixture(VALID_FIXTURE)
    del payload["agentStepId"]

    model = ToolCall.model_validate(payload)
    dumped = model.model_dump(by_alias=True, exclude_unset=False)

    assert "agentStepId" not in dumped

    payload["agentStepId"] = None
    with pytest.raises(ValidationError):
        ToolCall.model_validate(payload)


@pytest.mark.parametrize("tool_name", TOOL_NAMES)
def test_all_shared_tool_names_are_accepted(tool_name: str) -> None:
    payload = load_fixture(VALID_FIXTURE)
    payload["toolName"] = tool_name

    model = ToolCall.model_validate(payload)

    assert model.tool_name == tool_name


@pytest.mark.parametrize("tool_name", ("UNKNOWN_TOOL", "banana"))
def test_unknown_tool_name_is_rejected(tool_name: str) -> None:
    payload = load_fixture(VALID_FIXTURE)
    payload["toolName"] = tool_name

    with pytest.raises(ValidationError):
        ToolCall.model_validate(payload)


@pytest.mark.parametrize(
    ("field", "value"),
    (("projectId", 123), ("agentRunId", 123)),
)
def test_string_fields_reject_numeric_coercion(field: str, value: object) -> None:
    payload = load_fixture(VALID_FIXTURE)
    payload[field] = value

    with pytest.raises(ValidationError):
        ToolCall.model_validate(payload)


def test_dynamic_params_accept_json_object_values() -> None:
    payload = load_fixture(VALID_FIXTURE)
    payload["params"] = {
        "query": "timeout",
        "topK": 5,
        "nested": {"enabled": True},
    }

    model = ToolCall.model_validate(payload)

    assert model.params == payload["params"]


def test_snake_case_input_is_not_silently_accepted() -> None:
    payload = load_fixture(VALID_FIXTURE)
    payload["agent_run_id"] = payload.pop("agentRunId")

    with pytest.raises(ValidationError):
        ToolCall.model_validate(payload)


def test_caller_generated_java_tool_call_id_is_rejected() -> None:
    payload = load_fixture(VALID_FIXTURE)
    payload["toolCallId"] = "attacker-controlled"

    with pytest.raises(ValidationError):
        ToolCall.model_validate(payload)


@pytest.mark.parametrize("legacy_name", ("RAG_SEARCH", "REDIS_GET"))
def test_legacy_uppercase_tool_names_are_not_public_contract_values(
    legacy_name: str,
) -> None:
    payload = load_fixture(VALID_FIXTURE)
    payload["toolName"] = legacy_name

    with pytest.raises(ValidationError):
        ToolCall.model_validate(payload)


@pytest.mark.parametrize("field", AUTHORITY_FIELDS)
def test_trusted_authority_fields_are_not_part_of_tool_call(field: str) -> None:
    model = ToolCall.model_validate(load_fixture(VALID_FIXTURE))
    assert field not in model.model_dump(by_alias=True)

    payload = copy.deepcopy(load_fixture(VALID_FIXTURE))
    payload[field] = "must-not-be-modeled"

    with pytest.raises(ValidationError):
        ToolCall.model_validate(payload)
