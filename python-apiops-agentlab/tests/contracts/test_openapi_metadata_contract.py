"""Shared OpenAPI metadata compatibility tests."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.schemas.openapi_metadata import OpenApiMetadataDetail

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
VALID_FIXTURE = REPOSITORY_ROOT / "examples" / "openapi-metadata-valid.json"


def load_fixture() -> dict[str, object]:
    return json.loads(VALID_FIXTURE.read_text(encoding="utf-8"))


def test_canonical_metadata_fixture_passes_and_round_trips() -> None:
    fixture = load_fixture()
    model = OpenApiMetadataDetail.model_validate(fixture)

    assert model.model_dump() == fixture
    assert model.api_id == "api-1"
    assert model.parameters[0].location == "query"


def test_missing_required_field_is_rejected() -> None:
    payload = load_fixture()
    del payload["apiId"]

    with pytest.raises(ValidationError):
        OpenApiMetadataDetail.model_validate(payload)


def test_unknown_field_is_rejected() -> None:
    payload = load_fixture()
    payload["unknownField"] = True

    with pytest.raises(ValidationError):
        OpenApiMetadataDetail.model_validate(payload)


def test_malformed_parameters_structure_is_rejected() -> None:
    payload = load_fixture()
    payload["parameters"] = {"name": "limit"}

    with pytest.raises(ValidationError):
        OpenApiMetadataDetail.model_validate(payload)


def test_invalid_parameter_location_enum_is_rejected() -> None:
    payload = copy.deepcopy(load_fixture())
    payload["parameters"][0]["location"] = "body"  # type: ignore[index]

    with pytest.raises(ValidationError):
        OpenApiMetadataDetail.model_validate(payload)
