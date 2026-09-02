"""Shared TestCase DSL compatibility tests."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from pydantic import ValidationError
from pydantic.experimental.missing_sentinel import MISSING

from app.schemas.testcase_dsl import (
    JsonPathEqualsAssertion,
    JsonPathExistsAssertion,
)
from app.schemas.testcase_dsl import TestCaseDSL as CaseModel

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
EXAMPLES_ROOT = REPOSITORY_ROOT / "examples"
JAVA_TESTCASE_ROOT = (
    REPOSITORY_ROOT
    / "java-apiops-platform"
    / "apiops-runner"
    / "src"
    / "test"
    / "resources"
    / "testcase-dsl"
)

CANONICAL_VALID_FIXTURES = (
    EXAMPLES_ROOT / "testcase-valid.json",
    EXAMPLES_ROOT / "testcase-missing-token-valid.json",
    EXAMPLES_ROOT / "testcase-invalid-quantity-valid.json",
    EXAMPLES_ROOT / "testcase-insufficient-stock-valid.json",
)
CANONICAL_INVALID_FIXTURES = tuple(sorted((EXAMPLES_ROOT / "invalid").glob("testcase-*.json")))


def load_fixture(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.mark.parametrize("fixture_path", CANONICAL_VALID_FIXTURES, ids=lambda path: path.name)
def test_canonical_valid_fixtures_pass(fixture_path: Path) -> None:
    model = CaseModel.model_validate(load_fixture(fixture_path))

    assert model.schema_version == "1.0.0"
    assert model.steps


@pytest.mark.parametrize("fixture_path", CANONICAL_INVALID_FIXTURES, ids=lambda path: path.name)
def test_canonical_invalid_fixtures_fail(fixture_path: Path) -> None:
    with pytest.raises(ValidationError):
        CaseModel.model_validate(load_fixture(fixture_path))


def test_round_trip_preserves_shared_json_and_aliases() -> None:
    fixture = load_fixture(EXAMPLES_ROOT / "testcase-valid.json")
    model = CaseModel.model_validate(fixture)
    dumped = model.model_dump(by_alias=True, exclude_unset=True)

    assert dumped == fixture
    assert dumped["schemaVersion"] == "1.0.0"
    assert dumped["projectId"] == 1001
    assert dumped["apiId"] == "api_create_order"
    assert dumped["steps"][0]["assertions"][0]["type"] == "STATUS_CODE"
    assert dumped["steps"][0]["assertions"][1]["operator"] == "EQUALS"
    assert "schema_version" not in dumped
    assert "project_id" not in dumped


def test_default_round_trip_omits_unset_optional_fields() -> None:
    fixture = load_fixture(JAVA_TESTCASE_ROOT / "e2e" / "stage8-connect-failure.json")
    payload = copy.deepcopy(fixture)
    payload.pop("description", None)
    payload.pop("tags", None)
    model = CaseModel.model_validate(payload)

    for dumped in (
        model.model_dump(),
        model.model_dump(by_alias=True),
        model.model_dump(exclude_unset=False),
        model.model_dump(by_alias=True, exclude_unset=False),
    ):
        request = dumped["steps"][0]["request"]

        assert "description" not in dumped
        assert "tags" not in dumped
        assert "pathParams" not in request
        assert "query" not in request
        assert "headers" not in request
        assert "body" not in request
        assert_no_missing_sentinel(dumped)


def assert_no_missing_sentinel(value: object) -> None:
    assert value is not MISSING
    if isinstance(value, dict):
        for child in value.values():
            assert_no_missing_sentinel(child)
    elif isinstance(value, list):
        for child in value:
            assert_no_missing_sentinel(child)


def test_all_assertion_variants_from_java_fixture_are_typed() -> None:
    fixture = load_fixture(JAVA_TESTCASE_ROOT / "valid-basic.json")
    model = CaseModel.model_validate(fixture)
    assertions = model.steps[0].assertions

    assert [assertion.type for assertion in assertions] == [
        "STATUS_CODE",
        "HEADER",
        "JSON_PATH",
        "JSON_PATH",
        "RESPONSE_TIME",
    ]
    assert isinstance(assertions[2], JsonPathEqualsAssertion)
    assert isinstance(assertions[3], JsonPathExistsAssertion)


def test_dynamic_maps_remain_open() -> None:
    model = CaseModel.model_validate(load_fixture(JAVA_TESTCASE_ROOT / "valid-basic.json"))
    request = model.steps[0].request

    assert request.path_params == {"orderId": "order_001"}
    assert request.query == {"dryRun": False}
    assert request.headers == {"Content-Type": "application/json"}
    assert model.environment.variables == {"region": "test"}


@pytest.mark.parametrize("project_id", ["1001", True])
def test_project_id_rejects_string_and_bool_coercion(project_id: object) -> None:
    payload = load_fixture(EXAMPLES_ROOT / "testcase-valid.json")
    payload["projectId"] = project_id

    with pytest.raises(ValidationError):
        CaseModel.model_validate(payload)


def test_snake_case_json_alias_is_not_silently_accepted() -> None:
    payload = load_fixture(EXAMPLES_ROOT / "testcase-valid.json")
    payload["schema_version"] = payload.pop("schemaVersion")

    with pytest.raises(ValidationError):
        CaseModel.model_validate(payload)


def test_fixed_objects_reject_unknown_fields() -> None:
    payload = load_fixture(EXAMPLES_ROOT / "testcase-valid.json")
    payload["steps"][0]["request"]["unknownField"] = True

    with pytest.raises(ValidationError):
        CaseModel.model_validate(payload)


def test_body_and_json_path_equals_expected_are_json_values() -> None:
    payload = load_fixture(EXAMPLES_ROOT / "testcase-valid.json")
    payload["steps"][0]["request"]["body"] = None
    payload["steps"][0]["assertions"][1]["expected"] = None

    model = CaseModel.model_validate(payload)
    dumped = model.model_dump(by_alias=True, exclude_unset=True)
    default_dumped = model.model_dump()

    assert dumped["steps"][0]["request"]["body"] is None
    assert dumped["steps"][0]["assertions"][1]["expected"] is None
    assert default_dumped["steps"][0]["request"]["body"] is None
    assert default_dumped["steps"][0]["assertions"][1]["expected"] is None

    non_json_payload = copy.deepcopy(payload)
    non_json_payload["steps"][0]["request"]["body"] = {"value": object()}
    with pytest.raises(ValidationError):
        CaseModel.model_validate(non_json_payload)


@pytest.mark.parametrize("field", ["description", "tags"])
def test_optional_non_nullable_fields_reject_null(field: str) -> None:
    payload = load_fixture(EXAMPLES_ROOT / "testcase-valid.json")
    payload[field] = None

    with pytest.raises(ValidationError):
        CaseModel.model_validate(payload)


@pytest.mark.parametrize("field", ["pathParams", "query", "headers"])
def test_optional_request_maps_reject_null(field: str) -> None:
    payload = load_fixture(EXAMPLES_ROOT / "testcase-valid.json")
    payload["steps"][0]["request"][field] = None

    with pytest.raises(ValidationError):
        CaseModel.model_validate(payload)


def test_required_and_minimum_collection_rules_are_preserved() -> None:
    payload = load_fixture(EXAMPLES_ROOT / "testcase-valid.json")

    missing_variables = copy.deepcopy(payload)
    del missing_variables["environment"]["variables"]
    with pytest.raises(ValidationError):
        CaseModel.model_validate(missing_variables)

    empty_assertions = copy.deepcopy(payload)
    empty_assertions["steps"][0]["assertions"] = []
    with pytest.raises(ValidationError):
        CaseModel.model_validate(empty_assertions)

    missing_extractors = copy.deepcopy(payload)
    del missing_extractors["steps"][0]["extractors"]
    with pytest.raises(ValidationError):
        CaseModel.model_validate(missing_extractors)

    empty_steps = copy.deepcopy(payload)
    empty_steps["steps"] = []
    with pytest.raises(ValidationError):
        CaseModel.model_validate(empty_steps)

    empty_extractors = CaseModel.model_validate(payload)
    assert empty_extractors.steps[0].extractors == []


@pytest.mark.parametrize(
    "fixture_path",
    (
        EXAMPLES_ROOT / "invalid" / "testcase-invalid-method.json",
        EXAMPLES_ROOT / "invalid" / "testcase-missing-api-id.json",
        EXAMPLES_ROOT / "invalid" / "testcase-unknown-assertion.json",
        EXAMPLES_ROOT / "invalid" / "testcase-status-code-missing-expected.json",
        EXAMPLES_ROOT / "invalid" / "testcase-json-path-equals-missing-expected.json",
        EXAMPLES_ROOT / "invalid" / "testcase-missing-schema-version.json",
        JAVA_TESTCASE_ROOT / "unsupported-version.json",
    ),
    ids=lambda path: path.name,
)
def test_targeted_invalid_contract_cases_fail(fixture_path: Path) -> None:
    with pytest.raises(ValidationError):
        CaseModel.model_validate(load_fixture(fixture_path))


def test_json_path_exists_does_not_accept_expected() -> None:
    payload = load_fixture(JAVA_TESTCASE_ROOT / "valid-basic.json")
    payload["steps"][0]["assertions"][3]["expected"] = "must-not-exist"

    with pytest.raises(ValidationError):
        CaseModel.model_validate(payload)
