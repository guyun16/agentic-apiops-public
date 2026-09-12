"""Optional Java snapshot compatibility without changing model-facing reports."""

from copy import deepcopy

import pytest
from pydantic import ValidationError

from app.schemas.runner import TestReportStep as ReportStep

STEP = {
    "stepId": "read-products",
    "status": "SUCCESS",
    "failureType": "NONE",
    "responseStatusCode": 200,
    "durationMs": 12,
    "assertionResults": [],
}
EXCHANGE = {
    "request": {
        "method": "GET",
        "url": "http://localhost/products?page=[REDACTED]",
        "headers": {"Authorization": ["[REDACTED]"]},
        "body": None,
        "bodyState": "empty",
        "truncated": False,
    },
    "response": {
        "statusCode": 200,
        "headers": {"Content-Type": ["application/json"]},
        "body": '{"total":2,"name":"[REDACTED]"}',
        "bodyState": "captured",
        "truncated": False,
    },
}


def test_legacy_and_null_snapshots_keep_existing_model_facing_shape():
    for payload in [STEP, {**STEP, "httpExchange": None}]:
        report = ReportStep.model_validate(payload)
        assert report.http_exchange is None
        assert report.model_dump(mode="json") == STEP


def test_new_snapshot_is_accepted_but_not_added_to_prompts_or_checkpoints():
    report = ReportStep.model_validate({**STEP, "httpExchange": EXCHANGE})
    assert report.http_exchange.request.method == "GET"
    assert report.http_exchange.response.status_code == 200
    assert report.http_exchange.response.headers["Content-Type"] == ("application/json",)
    assert report.model_dump(mode="json") == STEP
    assert "httpExchange" not in report.model_dump_json(by_alias=True)


def test_request_without_response_is_supported_for_transport_failure():
    report = ReportStep.model_validate({**STEP, "httpExchange": {**EXCHANGE, "response": None}})
    assert report.http_exchange.response is None


@pytest.mark.parametrize(
    "field,value",
    [
        ("headers", {"Content-Type": "application/json"}),
        ("bodyState", "unknown"),
        ("truncated", "false"),
        ("body", {"not": "a string"}),
    ],
)
def test_snapshot_fields_remain_strict(field, value):
    exchange = deepcopy(EXCHANGE)
    exchange["request"][field] = value
    with pytest.raises(ValidationError):
        ReportStep.model_validate({**STEP, "httpExchange": exchange})


def test_unknown_snapshot_fields_do_not_silently_enter_the_consumer_contract():
    exchange = deepcopy(EXCHANGE)
    exchange["response"]["rawBody"] = "unexpected"
    with pytest.raises(ValidationError):
        ReportStep.model_validate({**STEP, "httpExchange": exchange})
