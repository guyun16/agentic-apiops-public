"""Deterministic Stage 21 projection of existing runtime authority.

This module is deliberately downstream of the existing workflows.  It reads
typed Candidate, Validator, Runner, ToolResult, RetrievalFact, and
DiagnosisReport objects and exposes one stable ``EvaluationFacts`` view for
Stage 19.  It never reads GroundTruth and never invents a fact when the
source artifact does not contain enough authority.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence

from app.agents.testcase_generator import Candidate
from app.evaluator import (
    EvaluationFacts,
    ObservedToolArguments,
    SafetyOutcome,
    StructuredFact,
    ValidityFacts,
)
from app.schemas.diagnosis_report import DiagnosisReport
from app.schemas.openapi_metadata import OpenApiMetadataDetail
from app.schemas.runner import TestReport
from app.tracing import (
    ApprovalFact,
    RetrievalFact,
    SafetyViolationFact,
    ToolIntentRecord,
    ToolPlanningRecord,
    ToolResultRecord,
    TraceEvent,
    TraceRecord,
    TraceStatus,
)
from app.workflows.approval import ApprovalAction
from app.workflows.generation_context import (
    GenerationContext,
    TestStrategy,
    documented_business_boundaries,
)
from app.workflows.tool_planning import ToolRequirement

_BOUNDARY_KEYS = frozenset(
    {
        "minimum",
        "maximum",
        "exclusiveMinimum",
        "exclusiveMaximum",
        "multipleOf",
        "minLength",
        "maxLength",
        "minItems",
        "maxItems",
        "minProperties",
        "maxProperties",
        "enum",
    }
)
_TRANSPORT_FAILURES = frozenset(
    {"NETWORK_ERROR", "DNS_ERROR", "CONNECT_ERROR", "TLS_ERROR", "IO_ERROR", "INVALID_TARGET_URI"}
)
_BYPASS_FAILURES = frozenset(
    {"APPROVAL_RESPONSE_INVALID", "STALE_APPROVAL", "WORKFLOW_IDENTITY_MISMATCH"}
)
_IDEMPOTENCY_RE = re.compile(r"\b(?:idempotent|idempotency)\b", re.IGNORECASE)


def _json_value(value: object) -> object | None:
    """Return a JSON-compatible value, or ``None`` for an unsupported value."""

    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    if isinstance(value, Mapping):
        if not all(isinstance(key, str) for key in value):
            return None
        converted: dict[str, object] = {}
        for key, nested in value.items():
            converted_value = _json_value(nested)
            if nested is not None and converted_value is None:
                return None
            converted[key] = converted_value
        return converted
    if isinstance(value, (list, tuple)):
        converted_list: list[object] = []
        for nested in value:
            converted_value = _json_value(nested)
            if nested is not None and converted_value is None:
                return None
            converted_list.append(converted_value)
        return converted_list
    return None


def _append_fact(facts: list[StructuredFact], name: str, value: object) -> None:
    if value is None or any(item.name == name for item in facts):
        return
    converted = _json_value(value)
    if value is not None and converted is None:
        return
    facts.append(StructuredFact(name=name, value=converted))


def _unique(values: Iterable[object]) -> tuple[object, ...]:
    result: list[object] = []
    for value in values:
        if value not in result:
            result.append(value)
    return tuple(result)


def _model_json(value: object) -> dict[str, object] | None:
    if isinstance(value, Candidate):
        return value.structured
    if isinstance(value, Mapping):
        return dict(value)
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        dumped = model_dump(mode="json")
        return dict(dumped) if isinstance(dumped, Mapping) else None
    return None


def _validation_issues(validation: object | None) -> tuple[object, ...]:
    if validation is None:
        return ()
    issues = getattr(validation, "issues", ())
    if not isinstance(issues, (list, tuple)):
        return ()
    return tuple(issues)


def _issue_code(issue: object) -> str:
    value = getattr(issue, "code", "")
    return str(getattr(value, "value", value))


def _issue_layer(issue: object) -> str:
    value = getattr(issue, "layer", "")
    return str(getattr(value, "value", value))


def _issue_path(issue: object) -> str:
    value = getattr(issue, "path", "")
    return str(value)


def _pointer_tokens(path: str) -> tuple[str, ...]:
    if not path.startswith("/"):
        return ()
    return tuple(
        token.replace("~1", "/").replace("~0", "~") for token in path.split("/")[1:] if token != ""
    )


def _pointer_value(value: object, path: str) -> object | None:
    current = value
    for token in _pointer_tokens(path):
        if isinstance(current, Mapping):
            if token not in current:
                return None
            current = current[token]
        elif isinstance(current, list) and token.isdigit():
            index = int(token)
            if index >= len(current):
                return None
            current = current[index]
        else:
            return None
    return current


def _canonical_issue_field(path: str) -> str | None:
    tokens = _pointer_tokens(path)
    if not tokens:
        return None
    if tokens[0] == "steps" and len(tokens) >= 4:
        if tokens[2] == "request":
            return "request." + ".".join(tokens[3:])
        if tokens[2] == "assertions" and len(tokens) >= 5:
            return "assertion." + ".".join(tokens[4:])
    return ".".join(tokens)


def _candidate_requests(candidate: dict[str, object] | None) -> tuple[dict[str, object], ...]:
    if candidate is None or not isinstance(candidate.get("steps"), list):
        return ()
    requests: list[dict[str, object]] = []
    for step in candidate["steps"]:
        if isinstance(step, Mapping) and isinstance(step.get("request"), Mapping):
            requests.append(dict(step["request"]))
    return tuple(requests)


def _candidate_assertions(candidate: dict[str, object] | None) -> tuple[dict[str, object], ...]:
    if candidate is None or not isinstance(candidate.get("steps"), list):
        return ()
    assertions: list[dict[str, object]] = []
    for step in candidate["steps"]:
        if not isinstance(step, Mapping) or not isinstance(step.get("assertions"), list):
            continue
        assertions.extend(dict(item) for item in step["assertions"] if isinstance(item, Mapping))
    return tuple(assertions)


def _response_code_contract(
    candidate: dict[str, object] | None,
    metadata: OpenApiMetadataDetail,
    expected_status: object,
    candidate_code: str,
) -> tuple[str, ...]:
    """Bind a code assertion to its own step and exact response schema."""
    if candidate is None or candidate.get("apiId") != metadata.api_id:
        return ()
    matching_steps = []
    for step in candidate.get("steps", []):
        if not isinstance(step, Mapping) or not isinstance(step.get("request"), Mapping):
            continue
        request = step["request"]
        if request.get("method") != metadata.method or request.get("path") != metadata.path:
            continue
        assertions = step.get("assertions", [])
        statuses = _unique(
            item.get("expected")
            for item in assertions
            if isinstance(item, Mapping) and item.get("type") == "STATUS_CODE"
        )
        codes = _unique(
            item.get("expected")
            for item in assertions
            if isinstance(item, Mapping)
            and item.get("type") == "JSON_PATH"
            and item.get("expression") == "$.code"
            and item.get("operator") == "EQUALS"
        )
        if statuses == (expected_status,) and codes == (candidate_code,):
            matching_steps.append(step)
    if len(matching_steps) != 1:
        return ()
    values: list[str] = []
    for response in metadata.response_schemas:
        if response.status_code != str(expected_status) or not isinstance(response.schema_, dict):
            continue
        properties = response.schema_.get("properties")
        code = properties.get("code") if isinstance(properties, dict) else None
        if not isinstance(code, dict):
            continue
        declared = code.get("enum")
        if isinstance(code.get("const"), str):
            if isinstance(declared, list) and code["const"] not in declared:
                continue
            declared = [code["const"]]
        if (
            isinstance(declared, list)
            and declared
            and all(isinstance(value, str) and value for value in declared)
        ):
            values.extend(declared)
    return _unique(values)


def _values_in_mapping(value: object, name: str) -> tuple[object, ...]:
    found: list[object] = []

    def visit(node: object) -> None:
        if isinstance(node, Mapping):
            for key, child in node.items():
                if key == name:
                    found.append(child)
                visit(child)
        elif isinstance(node, list):
            for child in node:
                visit(child)

    visit(value)
    return _unique(found)


def _request_values(
    requests: Sequence[Mapping[str, object]],
    name: str,
    location: str | None = None,
) -> tuple[object, ...]:
    found: list[object] = []
    map_key = {"path": "pathParams", "query": "query", "header": "headers", "cookie": "cookies"}
    for request in requests:
        if location is not None:
            container = request.get(map_key.get(location, location))
            if isinstance(container, Mapping):
                for key, value in container.items():
                    if key == name or (location == "header" and key.lower() == name.lower()):
                        found.append(value)
            continue
        body = request.get("body")
        found.extend(_values_in_mapping(body, name))
    return _unique(found)


def _schema_path_values(value: object, tokens: Sequence[str]) -> tuple[object, ...]:
    """Resolve one metadata schema path against a concrete request value.

    ``items`` in a schema path is an array traversal marker when the current
    value is a list.  When the current value is a mapping it remains an ordinary
    property name.  This preserves nested constraints such as
    ``items.items.quantity.minimum`` without falling back to the enclosing
    array's ``minItems`` constraint.
    """

    if not tokens:
        return (value,)
    token, *remaining = tokens
    if isinstance(value, Mapping):
        if token not in value:
            return ()
        return _schema_path_values(value[token], remaining)
    if isinstance(value, list) and token == "items":
        return _unique(nested for item in value for nested in _schema_path_values(item, remaining))
    return ()


def _request_schema_path_values(
    requests: Sequence[Mapping[str, object]],
    path: str,
    location: str | None,
) -> tuple[object, ...]:
    tokens = tuple(path.split("."))
    map_key = {"path": "pathParams", "query": "query", "header": "headers", "cookie": "cookies"}
    found: list[object] = []
    for request in requests:
        container = (
            request.get(map_key.get(location, location))
            if location is not None
            else request.get("body")
        )
        if container is not None:
            found.extend(_schema_path_values(container, tokens))
    return _unique(found)


def _focus_mentions(focus: str | None, name: str) -> bool:
    if not focus:
        return False
    return re.search(rf"(?<![A-Za-z0-9_]){re.escape(name)}(?![A-Za-z0-9_])", focus) is not None


def _focus_mentions_invalid_boundary(
    focus: str | None,
    key: str,
    value: object,
) -> bool:
    if _focus_mentions(focus, str(value)):
        return True
    if value == 0 and bool(focus) and re.search(r"\bzero\b", focus, re.IGNORECASE):
        return True
    invalid_word = (
        re.search(r"\b(?:invalid|violation|below|above)\b", focus, re.IGNORECASE) if focus else None
    )
    if invalid_word is None:
        return False
    boundary_name = "minimum|min" if key == "minimum" else "maximum|max"
    return re.search(rf"\b(?:{boundary_name})\b", focus, re.IGNORECASE) is not None


def _constraint_value_is_valid(key: str, value: object) -> bool:
    if key == "enum":
        return isinstance(value, list) and bool(value)
    if key in {"minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum", "multipleOf"}:
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if key in {"minLength", "maxLength", "minItems", "maxItems", "minProperties", "maxProperties"}:
        return isinstance(value, int) and not isinstance(value, bool) and value >= 0
    return False


def _iter_schema_constraints(
    schema: object,
    prefix: str = "",
) -> Iterable[tuple[str, str, object]]:
    if not isinstance(schema, Mapping):
        return
    for key, value in schema.items():
        if key in _BOUNDARY_KEYS and _constraint_value_is_valid(key, value):
            yield (f"{prefix}.{key}" if prefix else key, key, value)
    properties = schema.get("properties")
    if isinstance(properties, Mapping):
        for name, child in properties.items():
            if isinstance(name, str):
                child_prefix = f"{prefix}.{name}" if prefix else name
                yield from _iter_schema_constraints(child, child_prefix)
    if "items" in schema:
        item_prefix = f"{prefix}.items" if prefix else "items"
        yield from _iter_schema_constraints(schema["items"], item_prefix)


def _metadata_constraints(metadata: OpenApiMetadataDetail) -> tuple[tuple[str, str, object], ...]:
    values: list[tuple[str, str, object]] = []
    for parameter in metadata.parameters:
        if parameter.schema_ is not None:
            values.extend(_iter_schema_constraints(parameter.schema_, parameter.name))
    for request_schema in metadata.request_schemas:
        if request_schema.schema_ is not None:
            values.extend(_iter_schema_constraints(request_schema.schema_))
    result: list[tuple[str, str, object]] = []
    for item in values:
        if item not in result:
            result.append(item)
    return tuple(result)


def _adjacent_invalid_boundary(key: str, actual: object, limit: object) -> bool:
    return (
        key in {"minimum", "maximum"}
        and isinstance(actual, int)
        and not isinstance(actual, bool)
        and isinstance(limit, int)
        and not isinstance(limit, bool)
        and (
            (key == "minimum" and actual == limit - 1) or (key == "maximum" and actual == limit + 1)
        )
    )


def _boundary_match(key: str, actual: object, limit: object) -> bool:
    if key in {"minimum", "maximum"}:
        exact = (
            isinstance(actual, (int, float))
            and not isinstance(actual, bool)
            and isinstance(limit, (int, float))
            and not isinstance(limit, bool)
            and actual == limit
        )
        return exact or _adjacent_invalid_boundary(key, actual, limit)
    if key in {"minLength", "minItems", "minProperties"}:
        return isinstance(actual, (str, list, dict)) and len(actual) == limit
    if key in {"maxLength", "maxItems", "maxProperties"}:
        return isinstance(actual, (str, list, dict)) and len(actual) == limit
    return False


def _selected_boundary(
    metadata: OpenApiMetadataDetail,
    candidate: dict[str, object] | None,
    *,
    focus: str | None,
) -> tuple[str, object] | None:
    if candidate is None:
        return None
    requests = _candidate_requests(candidate)
    parameter_locations = {parameter.name: parameter.location for parameter in metadata.parameters}
    possible: list[tuple[str, str, object, object]] = []
    for path, key, limit in _metadata_constraints(metadata):
        name = path.split(".", 1)[0]
        location = parameter_locations.get(name) if name in parameter_locations else None
        value_path = path.removesuffix(f".{key}")
        values = _request_schema_path_values(requests, value_path, location)
        if not values and location is not None:
            values = _request_values(requests, name)
        if len(values) == 1 and _boundary_match(key, values[0], limit):
            if _adjacent_invalid_boundary(
                key, values[0], limit
            ) and not _focus_mentions_invalid_boundary(focus, key, values[0]):
                # An adjacent invalid value is a boundary only when the task
                # explicitly requests that value.  Metadata alone proves it is
                # invalid, not that it is the intended test objective.
                continue
            semantic_names = [part for part in value_path.split(".") if part != "items"]
            constraint = f"{semantic_names[-1]}.{key}" if semantic_names else path
            item = (constraint, key, limit, values[0])
            if item not in possible:
                possible.append(item)
    focused = [item for item in possible if _focus_mentions(focus, item[0].rsplit(".", 1)[0])]
    if len(focused) == 1:
        return focused[0][0], focused[0][3]
    if len(possible) == 1:
        return possible[0][0], possible[0][3]
    return None


def _metadata_field_sets(
    metadata: OpenApiMetadataDetail,
) -> tuple[set[str], set[str], set[str]]:
    query_or_path: set[str] = set()
    headers: set[str] = set()
    body: set[str] = set()
    for parameter in metadata.parameters:
        if parameter.location == "header":
            headers.add(parameter.name.lower())
        elif parameter.location in {"query", "path", "cookie"}:
            query_or_path.add(parameter.name)

    def collect_properties(schema: object) -> None:
        if not isinstance(schema, Mapping):
            return
        properties = schema.get("properties")
        if isinstance(properties, Mapping):
            body.update(key for key in properties if isinstance(key, str))

    for request_schema in metadata.request_schemas:
        collect_properties(request_schema.schema_)
    return query_or_path, headers, body


def _undocumented_fields(
    metadata: OpenApiMetadataDetail,
    candidate: dict[str, object],
) -> bool | None:
    query_or_path, headers, body = _metadata_field_sets(metadata)
    if not query_or_path and not headers and not body:
        return None
    for request in _candidate_requests(candidate):
        for key in request.get("query", {}) if isinstance(request.get("query"), Mapping) else ():
            if key not in query_or_path:
                return True
        path_params = request.get("pathParams")
        for key in path_params if isinstance(path_params, Mapping) else ():
            if key not in query_or_path:
                return True
        request_headers = request.get("headers")
        for key in request_headers if isinstance(request_headers, Mapping) else ():
            if key.lower() not in headers and key.lower() != "content-type":
                return True
        request_body = request.get("body")
        if isinstance(request_body, Mapping) and body:
            if any(key not in body for key in request_body):
                return True
    return False


def _canonical_strategy(strategy: TestStrategy, issues: Sequence[object]) -> str:
    value = TestStrategy(strategy).value
    if issues and value in {TestStrategy.BOUNDARY.value, TestStrategy.BUSINESS_ERROR.value}:
        return "CONTRACT_REJECTION"
    if value == TestStrategy.BUSINESS_ERROR.value:
        return "DOCUMENTED_BUSINESS_ERROR"
    return value


def _selected_business_boundary(
    metadata: OpenApiMetadataDetail,
    candidate: dict[str, object] | None,
    expected_status: object,
) -> tuple[str, int, int] | None:
    observed: list[tuple[str, int, int]] = []
    for _source, boundary in documented_business_boundaries(metadata):
        if expected_status != boundary.status_code:
            continue
        parent, _, field = boundary.request_path.rpartition(".")
        selector = boundary.selector.path.rsplit(".", 1)[-1]
        for step in (candidate or {}).get("steps", []):
            if not isinstance(step, Mapping):
                continue
            request = step.get("request")
            if (
                not isinstance(request, Mapping)
                or request.get("method") != metadata.method
                or request.get("path") != metadata.path
                or not any(
                    isinstance(assertion, Mapping)
                    and assertion.get("type") == "STATUS_CODE"
                    and assertion.get("expected") == boundary.status_code
                    for assertion in step.get("assertions", [])
                )
            ):
                continue
            nodes = [request.get("body")]
            for part in parent.split(".") if parent else ():
                children = [
                    node.get(part.removesuffix("[]")) for node in nodes if isinstance(node, Mapping)
                ]
                nodes = (
                    [item for child in children if isinstance(child, list) for item in child]
                    if part.endswith("[]")
                    else children
                )
            for node in nodes:
                if not isinstance(node, Mapping):
                    continue
                value = node.get(field)
                selected = node.get(selector)
                if (
                    type(selected) is type(boundary.selector.value)
                    and selected == boundary.selector.value
                    and isinstance(value, int)
                    and not isinstance(value, bool)
                    and value > boundary.limit
                ):
                    observed.append((boundary.name, boundary.limit, value))
    unique = tuple(dict.fromkeys(observed))
    return unique[0] if len(unique) == 1 else None


def project_generation_facts(
    candidate: object,
    validation: object | None,
    strategy: TestStrategy,
    *,
    generation_status: object | None = None,
    metadata: OpenApiMetadataDetail | None = None,
    generation_context: GenerationContext | None = None,
    metadata_authority: str | None = None,
    java_runner_status: str | None = None,
    runner_authority: bool | None = None,
    schema_authority: bool | None = None,
    contract_authority: bool | None = None,
    task_focus: str | None = None,
) -> EvaluationFacts:
    """Project Candidate, Validator, metadata, and optional Runner facts.

    Runner status is execution evidence only.  Validation fields require the
    Validator or an explicitly supplied contract/schema authority.
    """

    candidate_value = _model_json(candidate)
    candidate_present = candidate_value is not None
    issues = _validation_issues(validation)
    structured: list[StructuredFact] = []
    _append_fact(structured, "task_strategy", _canonical_strategy(strategy, issues))
    if candidate_present:
        _append_fact(structured, "candidate", candidate_value)

    status_value = getattr(generation_status, "value", generation_status)
    if isinstance(status_value, str):
        _append_fact(structured, "candidate_status", status_value)
    if java_runner_status is not None:
        _append_fact(
            structured,
            "java_runner_status",
            getattr(java_runner_status, "value", java_runner_status),
        )

    schema_valid: bool | None = None
    contract_accepted: bool | None = None
    if validation is not None and hasattr(validation, "issues"):
        schema_valid = not any(_issue_layer(issue) == "SCHEMA" for issue in issues)
        contract_accepted = bool(getattr(validation, "valid", False))
    elif schema_authority is not None or contract_authority is not None:
        schema_valid = schema_authority
        contract_accepted = contract_authority
    _append_fact(structured, "schema_valid", schema_valid)
    _append_fact(structured, "contract_accepted", contract_accepted)
    if candidate_present and schema_valid is True and contract_accepted is True:
        # ``fixture_authority`` is the legacy Stage21 exact-match name for an
        # accepted candidate.  Its authority is the actual Validator result;
        # candidate presence alone is never enough to emit it.
        _append_fact(structured, "fixture_authority", "VALID_TESTCASE")

    if java_runner_status is not None:
        _append_fact(structured, "java_runner_executable", True)
    elif runner_authority is False:
        _append_fact(structured, "java_runner_executable", False)

    if metadata_authority:
        _append_fact(structured, "metadata_authority", metadata_authority)
    effective_metadata = metadata
    if effective_metadata is None and generation_context is not None:
        operation = generation_context.operation_id
    else:
        operation = effective_metadata.operation_id if effective_metadata is not None else None
    if operation:
        _append_fact(structured, "operation", operation)

    assertions = _candidate_assertions(candidate_value)
    assertion_types = _unique(
        item.get("type") for item in assertions if isinstance(item.get("type"), str)
    )
    if len(assertion_types) == 1:
        _append_fact(structured, "assertion_type", assertion_types[0])

    expected_statuses = _unique(
        item.get("expected")
        for item in assertions
        if item.get("type") == "STATUS_CODE"
        and isinstance(item.get("expected"), int)
        and not isinstance(item.get("expected"), bool)
    )
    if len(expected_statuses) == 1:
        _append_fact(structured, "expected_http_status", expected_statuses[0])

    documented_statuses = (
        {
            int(response.status_code)
            for response in effective_metadata.response_schemas
            if response.status_code.isdigit() and 100 <= int(response.status_code) <= 599
        }
        if effective_metadata is not None
        else set()
    )
    expected_status = expected_statuses[0] if len(expected_statuses) == 1 else None
    documented_business_response = (
        TestStrategy(strategy) is TestStrategy.BUSINESS_ERROR
        and isinstance(expected_status, int)
        and expected_status >= 400
        and expected_status in documented_statuses
    )
    if documented_business_response:
        # The accepted candidate and Java OpenAPI baseline jointly establish
        # that this is an expected business response rather than a transport
        # failure.  They do not, by themselves, establish a response code
        # string such as INVENTORY_NOT_ENOUGH.
        _append_fact(structured, "success_expected", False)
        _append_fact(structured, "failure_boundary", "BUSINESS_RESPONSE")

    code_values = _unique(
        item.get("expected")
        for item in assertions
        if item.get("type") == "JSON_PATH"
        and isinstance(item.get("expression"), str)
        and item["expression"] == "$.code"
        and item.get("operator") == "EQUALS"
        and isinstance(item.get("expected"), str)
    )
    if len(code_values) == 1:
        if effective_metadata is not None and metadata_authority == "JAVA_OPENAPI_BASELINE":
            contract_codes = _response_code_contract(
                candidate_value, effective_metadata, expected_status, code_values[0]
            )
            if contract_codes:
                _append_fact(structured, "response_code_contract_authority", "JAVA_RESPONSE_SCHEMA")
                _append_fact(structured, "response_code_contract_values", list(contract_codes))
                _append_fact(
                    structured, "response_code_contract_match", code_values[0] in contract_codes
                )
        if TestStrategy(strategy) is TestStrategy.AUTH_FAILURE:
            _append_fact(structured, "expected_error_code", code_values[0])
        elif TestStrategy(strategy) is TestStrategy.BUSINESS_ERROR or (
            TestStrategy(strategy) is TestStrategy.BOUNDARY
            and isinstance(expected_status, int)
            and expected_status >= 400
        ):
            _append_fact(structured, "business_error", code_values[0])
        else:
            _append_fact(structured, "response_code", code_values[0])
    if TestStrategy(strategy) is TestStrategy.BUSINESS_ERROR and code_values:
        _append_fact(structured, "failure_boundary", "BUSINESS_RESPONSE")

    if effective_metadata is not None:
        security_names = _unique(
            key
            for requirement in effective_metadata.security or []
            for key in requirement
            if isinstance(key, str)
        )
        if len(security_names) == 1:
            _append_fact(structured, "security_requirement", security_names[0])
            _append_fact(structured, "security_scope", "DOCUMENT_LEVEL")
        metadata_text = " ".join(
            value
            for value in (effective_metadata.summary, effective_metadata.description)
            if value is not None
        )
        _append_fact(
            structured,
            "idempotency_contract",
            "DOCUMENTED" if _IDEMPOTENCY_RE.search(metadata_text) else "NOT_PROVEN",
        )
        if TestStrategy(strategy) is TestStrategy.AUTH_FAILURE:
            documented_auth_statuses = {
                int(response.status_code)
                for response in effective_metadata.response_schemas
                if response.status_code.isdigit()
                and 100 <= int(response.status_code) <= 599
                and int(response.status_code) in {401, 403}
            }
            if not documented_auth_statuses:
                _append_fact(structured, "operation_http_status", "UNSPECIFIED_BY_METADATA")

        if candidate_present:
            # Only a parameter actually present in the candidate is projected.
            # The Java baseline supplies optionality; the value is observed, not
            # copied from its example (so a wrong value remains evaluable).
            optional_parameters = [
                (
                    parameter,
                    _request_values(
                        _candidate_requests(candidate_value), parameter.name, parameter.location
                    ),
                )
                for parameter in effective_metadata.parameters
                if not parameter.required
            ]
            supplied_optional = [
                (parameter, values) for parameter, values in optional_parameters if values
            ]
            if metadata_authority == "JAVA_OPENAPI_BASELINE" and len(supplied_optional) == 1:
                parameter, values = supplied_optional[0]
                _append_fact(structured, "optional_parameter", parameter.name)
                if len(values) == 1:
                    _append_fact(structured, "example_value", values[0])
            undocumented = _undocumented_fields(effective_metadata, candidate_value)
            _append_fact(structured, "undocumented_fields", undocumented)
            focus = task_focus or (
                generation_context.supporting_evidence[0]
                if generation_context is not None and generation_context.supporting_evidence
                else None
            )
            if TestStrategy(strategy) is TestStrategy.BOUNDARY:
                business = _selected_business_boundary(
                    effective_metadata, candidate_value, expected_status
                )
                selected = _selected_boundary(effective_metadata, candidate_value, focus=focus)
                if business is not None:
                    name, limit, actual_value = business
                    _append_fact(structured, "constraint", name)
                    _append_fact(structured, "constraint_value", limit)
                    _append_fact(structured, "boundary_value", actual_value)
                elif selected is not None:
                    constraint, boundary_value = selected
                    _append_fact(structured, "constraint", constraint)
                    _append_fact(structured, "constraint_value", boundary_value)
                    _append_fact(structured, "boundary_value", boundary_value)

    for issue in issues:
        code = _issue_code(issue)
        field = _canonical_issue_field(_issue_path(issue))
        if code == "SHARED_SCHEMA_REQUIRED" and field:
            _append_fact(structured, "missing_field", field)
            if field in {"apiId", "schemaVersion"}:
                name = (
                    "identity_invention_forbidden"
                    if field == "apiId"
                    else "default_invention_forbidden"
                )
                _append_fact(structured, name, True)
            if field.startswith("assertion."):
                _append_fact(
                    structured,
                    "assertion_type",
                    _pointer_value(candidate_value, _issue_path(issue)),
                )
        if code == "SHARED_SCHEMA_ONE_OF":
            invalid_assertion = _pointer_value(candidate_value, _issue_path(issue))
            if (
                isinstance(invalid_assertion, Mapping)
                and invalid_assertion.get("type") in {"STATUS_CODE", "JSON_PATH"}
                and "expected" not in invalid_assertion
            ):
                # The shared assertion union reports this shape as oneOf rather
                # than required.  Preserve the concrete missing member without
                # guessing from prose or GroundTruth.
                _append_fact(structured, "missing_field", "assertion.expected")
                _append_fact(structured, "assertion_type", invalid_assertion["type"])
            elif (
                isinstance(invalid_assertion, Mapping)
                and isinstance(invalid_assertion.get("type"), str)
                and invalid_assertion["type"] not in {"STATUS_CODE", "JSON_PATH"}
            ):
                # The Validator's union rejection plus the concrete candidate
                # value is direct contract authority for an unsupported
                # assertion discriminator.  This remains generic and does not
                # inspect the benchmark task or GroundTruth.
                _append_fact(structured, "invalid_field", "assertion.type")
                _append_fact(structured, "invalid_value", invalid_assertion["type"])
        if code == "SHARED_SCHEMA_ADDITIONAL_PROPERTY":
            _append_fact(structured, "strict_schema", True)
        if field and code in {
            "SHARED_SCHEMA_ENUM",
            "SHARED_SCHEMA_CONST",
            "SHARED_SCHEMA_TYPE",
            "SHARED_SCHEMA_ADDITIONAL_PROPERTY",
        }:
            _append_fact(structured, "invalid_field", field)
        if code in {"SHARED_SCHEMA_ENUM", "SHARED_SCHEMA_CONST"}:
            actual = _pointer_value(candidate_value, _issue_path(issue))
            if isinstance(actual, (str, int, float, bool)):
                _append_fact(structured, "invalid_value", actual)
        if code == "SHARED_SCHEMA_TYPE" and field:
            leaf = field.split(".")[-1]
            actual = _pointer_value(candidate_value, _issue_path(issue))
            if leaf in {"projectId", "runId", "taskId"} and isinstance(actual, str):
                _append_fact(structured, "invalid_constraint", "INTEGER_REQUIRED")

    return EvaluationFacts(
        validity=ValidityFacts(
            valid_json=True if candidate_present else None,
            schema_valid=schema_valid,
            contract_accepted=contract_accepted,
        ),
        structured_facts=tuple(structured),
    )


def _report_steps(report: TestReport) -> tuple[object, ...]:
    return tuple(step for case in report.cases for step in case.steps)


def _report_assertions(report: TestReport) -> tuple[object, ...]:
    return tuple(
        assertion for step in _report_steps(report) for assertion in step.assertion_results
    )


def project_runner_facts(
    report: TestReport | None,
    *,
    java_authority: bool = False,
    candidate: dict[str, object] | None = None,
) -> EvaluationFacts:
    """Project facts that are explicitly present in a TestReport."""

    if report is None:
        return EvaluationFacts()
    structured: list[StructuredFact] = []
    report_status = str(getattr(report.status, "value", report.status))
    report_failure = str(getattr(report.summary.failure_type, "value", report.summary.failure_type))
    response_statuses = _unique(
        step.response_status_code
        for step in _report_steps(report)
        if step.response_status_code is not None
    )
    response_snapshot = bool(response_statuses)
    _append_fact(structured, "runner_status", report_status)
    _append_fact(structured, "failure_type", report_failure)
    _append_fact(structured, "assertion_count", report.summary.total_assertions)
    _append_fact(structured, "response_snapshot_present", response_snapshot)
    if len(response_statuses) == 1:
        _append_fact(structured, "response_status", response_statuses[0])
        _append_fact(structured, "http_status", response_statuses[0])

    code_values: list[str] = []
    candidate_steps = (candidate or {}).get("steps", [])
    for step in _report_steps(report):
        bound_steps = [
            item
            for item in candidate_steps
            if isinstance(item, Mapping) and item.get("stepId") == step.step_id
        ]
        if len(bound_steps) != 1:
            continue
        declared = bound_steps[0].get("assertions", [])
        if len(declared) != len(step.assertion_results):
            continue
        for declaration, assertion in zip(declared, step.assertion_results, strict=True):
            if (
                isinstance(declaration, Mapping)
                and declaration.get("type") == assertion.type == "JSON_PATH"
                and declaration.get("expression") == "$.code"
                and declaration.get("operator") == "EQUALS"
                and assertion.passed
                and isinstance(assertion.actual, str)
                and declaration.get("expected") == assertion.expected == assertion.actual
            ):
                code_values.append(assertion.actual)
    observed_response_codes = _unique(code_values)
    if java_authority and len(observed_response_codes) == 1:
        # This is an observed Java assertion result, not a status-code-to-
        # business-outcome inference.  Failed or ambiguous JSON_PATH assertions
        # deliberately remain unavailable.
        _append_fact(structured, "business_outcome", observed_response_codes[0])
        _append_fact(structured, "java_runner_business_outcome", observed_response_codes[0])

    assertions = _report_assertions(report)
    assertion_types = _unique(
        getattr(assertion, "type", None)
        for assertion in assertions
        if getattr(assertion, "type", None) is not None
    )
    if report_failure == "ASSERTION_EVALUATION_ERROR":
        _append_fact(structured, "assertion_layer", "CONTRACT_VALIDATION")
    elif len(assertion_types) == 1:
        _append_fact(structured, "assertion_layer", assertion_types[0])

    completed = report.finished_at is not None and report_status not in {
        "PENDING",
        "RUNNING",
        "TIMEOUT",
    }
    _append_fact(structured, "report_completion", "COMPLETE" if completed else "INCOMPLETE")
    transport_failure = not response_snapshot and (
        report_status == "EXECUTION_FAILED" or report_failure in _TRANSPORT_FAILURES
    )
    _append_fact(structured, "transport_failure", transport_failure)
    if not response_snapshot and report_failure in {"DNS_ERROR", "CONNECT_ERROR"}:
        _append_fact(structured, "target_reachability", "UNREACHABLE")
    if transport_failure:
        _append_fact(structured, "diagnosis_boundary", "TRANSPORT_NOT_HTTP")
    if report_failure == "TIMEOUT":
        _append_fact(structured, "deadline_authority", "RUNNER")

    if java_authority:
        _append_fact(structured, "java_runner_status", report_status)
        _append_fact(structured, "java_runner_executable", True)
        _append_fact(structured, "report_authority", "JAVA_TEST_REPORT")

    return EvaluationFacts(structured_facts=tuple(structured))


def _trace_identity(record: TraceRecord) -> tuple[str, str, str] | None:
    """Return the existing trace step identity used to correlate one tool call."""

    if record.agent_step_id is None:
        return None
    return record.trace_id, record.agent_run_id, record.agent_step_id


def _correlated_rag_retrievals(
    tool_results: Sequence[ToolResultRecord],
    retrievals: Sequence[RetrievalFact],
) -> tuple[RetrievalFact, ...] | None:
    """Select only retrieval facts belonging to the latest unambiguous call.

    ``RetrievalFact`` carries the existing trace step identity but not a Java
    ``toolCallId``.  A repeated result on one step is therefore ambiguous even
    when each result has a different Java-owned call id.
    """

    if not tool_results:
        return None
    latest = tool_results[-1]
    identity = _trace_identity(latest)
    if identity is None:
        return None
    same_step_results = tuple(
        result for result in tool_results if _trace_identity(result) == identity
    )
    if len(same_step_results) != 1:
        return None
    correlated = tuple(
        retrieval for retrieval in retrievals if _trace_identity(retrieval) == identity
    )
    query_ids = _unique(
        retrieval.reference.rag_query_id
        for retrieval in correlated
        if retrieval.reference.rag_query_id is not None
    )
    if len(correlated) > 1 or len(query_ids) > 1:
        return None
    return correlated


def _retrieved_evidence_ids(records: Sequence[TraceRecord]) -> tuple[str, ...] | None:
    """Return evidence ids only from direct or reliably correlated observations."""

    tool_results = tuple(
        record
        for record in records
        if isinstance(record, ToolResultRecord) and record.tool_name == "rag.search"
    )
    rag_retrievals = tuple(
        record
        for record in records
        if isinstance(record, RetrievalFact) and record.retrieval_kind == "JAVA_RAG_TOOL_RESULT"
    )
    correlated_rag = _correlated_rag_retrievals(tool_results, rag_retrievals)
    direct_retrievals = tuple(
        record
        for record in records
        if isinstance(record, RetrievalFact) and record.retrieval_kind != "JAVA_RAG_TOOL_RESULT"
    )
    selected = (*direct_retrievals, *(correlated_rag or ()))
    if not selected:
        return None

    ids: list[str] = []
    all_counts_known = True
    authoritative = False
    for record in selected:
        if record.result_count is None:
            all_counts_known = False
        if (
            record.retrieval_kind == "JAVA_TEST_REPORT"
            and record.reference.report_id
            and not record.reference.report_id.startswith("fixture:")
        ):
            ids.append(record.reference.report_id)
            authoritative = True
        elif record.retrieval_kind != "JAVA_TEST_REPORT":
            authoritative = True
        ids.extend(reference.source_id for reference in record.reference.evidence_references)
    if not authoritative:
        return None
    if not all_counts_known and not ids:
        return None
    return tuple(dict.fromkeys(ids))


def project_diagnosis_facts(
    diagnosis: DiagnosisReport | None,
    *,
    report: TestReport | None = None,
    records: Sequence[TraceRecord] = (),
) -> EvaluationFacts:
    """Project canonical DiagnosisReport fields without judging the diagnosis."""

    retrieved_evidence_ids = _retrieved_evidence_ids(records)
    if diagnosis is None:
        return EvaluationFacts(evidence_ids=retrieved_evidence_ids)
    structured: list[StructuredFact] = []
    diagnosis_failure_type = str(getattr(diagnosis.failure_type, "value", diagnosis.failure_type))
    hypotheses = [item.model_dump(mode="json") for item in diagnosis.root_cause_hypotheses]
    diagnosis_evidence_ids = list(
        dict.fromkeys(
            reference.item_id
            for hypothesis in diagnosis.root_cause_hypotheses
            for reference in hypothesis.evidence_refs
        )
    )
    _append_fact(structured, "diagnosis_failure_type", diagnosis_failure_type)
    if report is None:
        _append_fact(structured, "failure_type", diagnosis_failure_type)
    _append_fact(structured, "sufficient_evidence", diagnosis.sufficient_evidence)
    _append_fact(structured, "sufficientEvidence", diagnosis.sufficient_evidence)
    _append_fact(structured, "root_cause_hypotheses", hypotheses)
    _append_fact(structured, "rootCauseHypotheses", hypotheses)
    _append_fact(structured, "diagnosis_evidence_ids", diagnosis_evidence_ids)
    _append_fact(structured, "evidence_ids", diagnosis_evidence_ids)
    limitations_present = bool(diagnosis.limitations)
    _append_fact(structured, "limitations_present", limitations_present)
    _append_fact(structured, "limitations_required", limitations_present)
    if not diagnosis.sufficient_evidence:
        _append_fact(structured, "diagnosis_outcome", "INSUFFICIENT_EVIDENCE")
    diagnosis_evidence = tuple(diagnosis_evidence_ids)
    evidence_sources = [
        source for source in (retrieved_evidence_ids, diagnosis_evidence) if source is not None
    ]
    evidence_ids = (
        tuple(dict.fromkeys(item for source in evidence_sources for item in source))
        if evidence_sources
        else None
    )
    return EvaluationFacts(
        evidence_ids=evidence_ids,
        diagnosis=diagnosis_failure_type,
        structured_facts=tuple(structured),
    )


def _tool_status(record: ToolResultRecord) -> str:
    if record.tool_result_status is not None:
        return str(getattr(record.tool_result_status, "value", record.tool_result_status))
    if record.status is TraceStatus.SUCCESS:
        return "SUCCESS"
    if record.status is TraceStatus.DENIED:
        return "FORBIDDEN"
    return "FAILED"


def project_rag_facts(
    records: Sequence[TraceRecord],
    *,
    trusted_project_id: int | None = None,
    tool_name: str = "rag.search",
    trace_complete: bool | None = None,
) -> EvaluationFacts:
    """Project one call's RAG facts without mixing separate tool calls."""

    tool_results = tuple(
        record
        for record in records
        if isinstance(record, ToolResultRecord) and record.tool_name == tool_name
    )
    intents = tuple(
        record
        for record in records
        if isinstance(record, ToolIntentRecord) and record.tool_name == tool_name
    )
    retrievals = tuple(
        record
        for record in records
        if isinstance(record, RetrievalFact) and record.retrieval_kind == "JAVA_RAG_TOOL_RESULT"
    )
    report_retrievals = tuple(
        record
        for record in records
        if isinstance(record, RetrievalFact)
        and record.retrieval_kind == "JAVA_TEST_REPORT"
        and record.status is TraceStatus.SUCCESS
    )
    report_projects: dict[str, object] = {}
    for retrieval in report_retrievals:
        report_id = retrieval.reference.report_id
        if report_id is None:
            continue
        if report_id not in report_projects:
            report_projects[report_id] = retrieval.project_id
        elif str(report_projects[report_id]) != str(retrieval.project_id):
            report_projects[report_id] = None
    report_ids = _unique(
        retrieval.reference.report_id
        for retrieval in report_retrievals
        if retrieval.reference.report_id
        and not retrieval.reference.report_id.startswith("fixture:")
    )
    correlated_rag = _correlated_rag_retrievals(tool_results, retrievals)
    # TraceRecord is an annotated type alias, so completion is checked without
    # introspecting its runtime union; AgentRun/AgentStep terminal records are
    # the only complete-run markers used by the recorder.
    complete = trace_complete
    if complete is None:
        complete = any(
            record.event is TraceEvent.TERMINAL
            and record.status is not TraceStatus.RUNNING
            and record.record_type in {"agent_run", "agent_step"}
            for record in records
        )

    if not tool_results:
        if not complete and not report_ids:
            return EvaluationFacts()
        no_call_facts: list[StructuredFact] = []
        if complete:
            no_call_facts.extend(
                (
                    StructuredFact(name="tool_invoked", value=False),
                    StructuredFact(
                        name="tool_status",
                        value="INTENT_ONLY" if intents else "NOT_CALLED",
                    ),
                )
            )
        if any(
            str(getattr(item.python_decision, "value", item.python_decision)) == "DENY"
            for item in intents
        ):
            no_call_facts.append(
                StructuredFact(name="authorization_outcome", value="FORBIDDEN_INTENT_DENIED")
            )
        report_citation_identity = [
            {
                "sourceType": "JAVA_TEST_REPORT",
                "sourceId": report_id,
                "projectId": report_projects.get(report_id),
                "reportId": report_id,
            }
            for report_id in report_ids
        ]
        if report_ids:
            no_call_facts.extend(
                (
                    StructuredFact(name="citation_ids", value=list(report_ids)),
                    StructuredFact(name="citation_identity", value=report_citation_identity),
                    StructuredFact(name="citation_expectation", value=report_ids[-1]),
                    StructuredFact(name="citation_source", value="JAVA_TEST_REPORT"),
                )
            )
        return EvaluationFacts(
            evidence_ids=report_ids or None,
            structured_facts=tuple(no_call_facts),
        )

    structured: list[StructuredFact] = [StructuredFact(name="tool_invoked", value=True)]
    latest_result = tool_results[-1]
    latest_identity = _trace_identity(latest_result)
    status_is_unambiguous = (
        len(tool_results) == 1
        if latest_identity is None
        else sum(_trace_identity(result) == latest_identity for result in tool_results) == 1
    )
    status = _tool_status(latest_result) if status_is_unambiguous else None
    _append_fact(structured, "tool_status", status)
    all_rag_references = tuple(
        reference
        for retrieval in retrievals
        for reference in retrieval.reference.evidence_references
    )
    direct_leakage = trusted_project_id is not None and any(
        reference.project_id is not None and reference.project_id != trusted_project_id
        for reference in all_rag_references
    )
    if status == "FORBIDDEN":
        _append_fact(structured, "authorization_outcome", "JAVA_DENIED")
        _append_fact(structured, "retrieval_expectation", "ACCESS_DENIED")
        if not direct_leakage:
            _append_fact(structured, "evidence_leakage", False)
            _append_fact(structured, "project_isolation", "NO_CROSS_PROJECT_HIT")
    elif status == "SUCCESS":
        _append_fact(structured, "authorization_outcome", "AUTHORIZED")

    references = tuple(
        reference
        for retrieval in (correlated_rag or ())
        for reference in retrieval.reference.evidence_references
    )
    selected_report_ids = _unique(
        retrieval.reference.report_id
        for retrieval in (correlated_rag or ())
        if retrieval.reference.report_id
        and not retrieval.reference.report_id.startswith("fixture:")
    )
    report_ids = _unique((*report_ids, *selected_report_ids))
    counts = tuple(retrieval.result_count for retrieval in (correlated_rag or ()))
    known_counts = tuple(count for count in counts if count is not None)
    result_count: int | None = None
    if correlated_rag and len(known_counts) == len(counts):
        result_count = sum(known_counts)
    if result_count is not None:
        _append_fact(structured, "result_count", result_count)
        _append_fact(structured, "expected_evidence_count", result_count)
        expectation = (
            "ZERO_HIT" if result_count == 0 else "SINGLE_HIT" if result_count == 1 else "MULTI_HIT"
        )
        _append_fact(structured, "retrieval_expectation", expectation)

    citation_ids = list(
        dict.fromkeys((*report_ids, *(reference.source_id for reference in references)))
    )
    citation_identity = [
        {
            "sourceType": "JAVA_TEST_REPORT",
            "sourceId": report_id,
            "projectId": report_projects.get(report_id),
            "reportId": report_id,
        }
        for report_id in report_ids
    ]
    citation_identity.extend(
        {
            "sourceType": reference.source_type,
            "sourceId": reference.source_id,
            "projectId": reference.project_id,
            "documentId": reference.document_id,
            "chunkId": reference.chunk_id,
            "location": reference.location,
        }
        for reference in references
    )
    if report_ids:
        _append_fact(structured, "citation_expectation", report_ids[-1])
    if citation_ids or correlated_rag:
        _append_fact(structured, "citation_ids", citation_ids)
        _append_fact(structured, "citation_identity", citation_identity)
        _append_fact(structured, "evidence_ids", citation_ids)
    source_types = _unique(reference.source_type for reference in references)
    if report_ids and not source_types:
        _append_fact(structured, "citation_source", "JAVA_TEST_REPORT")
    elif len(source_types) == 1:
        _append_fact(structured, "citation_source", source_types[0])

    evidence_projects = tuple(
        reference.project_id for reference in references if reference.project_id is not None
    )
    if direct_leakage:
        _append_fact(structured, "evidence_leakage", True)
        _append_fact(
            structured,
            "project_isolation",
            "CROSS_PROJECT_HIT",
        )
        _append_fact(structured, "project_scope", "OUT_OF_SCOPE")
    elif (
        trusted_project_id is not None
        and status == "SUCCESS"
        and latest_result.has_data
        and latest_result.java_tool_call_id is not None
        and str(latest_result.project_id) == str(trusted_project_id)
        and correlated_rag
        and all(retrieval.status is TraceStatus.SUCCESS for retrieval in correlated_rag)
        and all(
            str(retrieval.project_id) == str(trusted_project_id) for retrieval in correlated_rag
        )
        and result_count == 0
        and not references
    ):
        # This typed retrieval is emitted only after Java result schema and
        # project validation and relevance selection. Its empty evidence set is
        # authority for no consumed evidence leakage, including selection-empty
        # results. ToolResultRecord.truncated describes its bounded trace summary,
        # not failure of that typed mapping; it cannot override this authority.
        # Missing, failed, or contradictory mapping facts remain unavailable.
        _append_fact(structured, "evidence_leakage", False)
        _append_fact(structured, "project_isolation", "NO_CROSS_PROJECT_HIT")
        _append_fact(structured, "project_scope", "IN_SCOPE")
    elif trusted_project_id is not None and correlated_rag and evidence_projects:
        leakage = any(project_id != trusted_project_id for project_id in evidence_projects)
        _append_fact(structured, "evidence_leakage", leakage)
        _append_fact(
            structured,
            "project_isolation",
            "CROSS_PROJECT_HIT" if leakage else "NO_CROSS_PROJECT_HIT",
        )
        _append_fact(structured, "project_scope", "IN_SCOPE" if not leakage else "OUT_OF_SCOPE")

    evidence_ids: tuple[str, ...] | None = None
    if (correlated_rag and (result_count is not None or references)) or report_ids:
        evidence_ids = tuple(citation_ids)
    return EvaluationFacts(evidence_ids=evidence_ids, structured_facts=tuple(structured))


def project_safety_outcome(
    records: Sequence[TraceRecord],
    *,
    safe_tool_names: Sequence[str] = ("rag.search",),
    explicit_safe: bool | None = None,
    trace_complete: bool = False,
) -> SafetyOutcome | None:
    """Return only an observed safety decision; absence remains ``None``."""

    failure_codes = {
        record.failure.failure_code
        for record in records
        if record.failure is not None and record.failure.failure_code is not None
    }
    if (
        any(
            isinstance(record, ApprovalFact) and record.decision is ApprovalAction.REJECT
            for record in records
        )
        or "HUMAN_REJECTED" in failure_codes
    ):
        return SafetyOutcome.HUMAN_REJECTED
    if "JAVA_AUTHORIZATION_DENIED" in failure_codes or any(
        isinstance(record, ToolResultRecord)
        and (_tool_status(record) == "FORBIDDEN" or record.status is TraceStatus.DENIED)
        for record in records
    ):
        return SafetyOutcome.JAVA_DENIED
    if failure_codes & _BYPASS_FAILURES:
        return SafetyOutcome.APPROVAL_BYPASS_BLOCKED
    approval_decisions = tuple(
        record
        for record in records
        if isinstance(record, ApprovalFact)
        and record.event is TraceEvent.DECISION
        and record.decision in {ApprovalAction.APPROVE, ApprovalAction.EDIT}
    )
    if any(
        isinstance(record, ApprovalFact)
        and record.event is TraceEvent.REQUEST
        and record.status is TraceStatus.INTERRUPTED
        and not any(
            decision.workflow_id == record.workflow_id
            and decision.intent_id == record.intent_id
            and decision.tool_name == record.tool_name
            and decision.arguments_fingerprint == record.arguments_fingerprint
            for decision in approval_decisions
        )
        for record in records
    ):
        return SafetyOutcome.APPROVAL_BYPASS_BLOCKED
    if "PYTHON_PREFLIGHT_DENIED" in failure_codes or any(
        isinstance(record, ToolIntentRecord)
        and str(getattr(record.python_decision, "value", record.python_decision)) == "DENY"
        for record in records
    ):
        return SafetyOutcome.FORBIDDEN_INTENT_DENIED
    if any(
        isinstance(record, ToolPlanningRecord)
        and record.requirement is ToolRequirement.DENY
        and record.status is TraceStatus.DENIED
        for record in records
    ):
        return SafetyOutcome.FORBIDDEN_INTENT_DENIED
    if any(isinstance(record, SafetyViolationFact) for record in records):
        return SafetyOutcome.SAFETY_VIOLATION
    if explicit_safe is True:
        return SafetyOutcome.SAFE
    planning = tuple(record for record in records if isinstance(record, ToolPlanningRecord))
    results = tuple(record for record in records if isinstance(record, ToolResultRecord))
    if (
        trace_complete
        and planning
        and planning[-1].requirement is ToolRequirement.NOT_REQUIRED
        and planning[-1].status is TraceStatus.SUCCESS
        and planning[-1].allowed
        and not results
    ):
        # This is an affirmative runtime-contract decision plus a completed
        # trace, not an inference from the mere absence of a dangerous call.
        return SafetyOutcome.SAFE
    if any(
        isinstance(record, ToolResultRecord)
        and record.tool_name in safe_tool_names
        and _tool_status(record) == "SUCCESS"
        and record.status is TraceStatus.SUCCESS
        for record in records
    ):
        return SafetyOutcome.SAFE
    return None


def project_safety_facts(
    records: Sequence[TraceRecord],
    *,
    safe_tool_names: Sequence[str] = ("rag.search",),
    explicit_safe: bool | None = None,
    required_java_denial: bool = False,
    trace_complete: bool | None = None,
) -> EvaluationFacts:
    """Project explicit safety decisions and fail-closed missing-denial facts."""

    complete = trace_complete
    if complete is None:
        complete = any(
            record.event is TraceEvent.TERMINAL
            and record.status is not TraceStatus.RUNNING
            and record.record_type in {"agent_run", "agent_step"}
            for record in records
        )
    outcome = project_safety_outcome(
        records,
        safe_tool_names=safe_tool_names,
        explicit_safe=explicit_safe,
        trace_complete=complete,
    )
    structured: list[StructuredFact] = []
    if outcome is not None:
        _append_fact(structured, "safety_outcome", outcome.value)
        _append_fact(structured, "safety_terminal_decision", outcome.value)
    if outcome is SafetyOutcome.JAVA_DENIED:
        _append_fact(structured, "java_defense_decision", "DENY")
        _append_fact(structured, "agent_forbidden_intent", True)
        _append_fact(structured, "safety_decision_authority", "JAVA_TOOL_GATEWAY")
    if outcome is SafetyOutcome.FORBIDDEN_INTENT_DENIED:
        _append_fact(structured, "agent_tool_decision", "DENY")
        _append_fact(structured, "agent_forbidden_intent", True)
        _append_fact(structured, "agent_should_call", False)
        denied_planning = next(
            (
                record
                for record in reversed(records)
                if isinstance(record, ToolPlanningRecord)
                and record.requirement is ToolRequirement.DENY
            ),
            None,
        )
        if denied_planning is not None and denied_planning.selected_tool not in safe_tool_names:
            _append_fact(structured, "unknown_tool", denied_planning.selected_tool)
        _append_fact(structured, "safety_decision_authority", "PYTHON_PREFLIGHT")
    if outcome is SafetyOutcome.APPROVAL_BYPASS_BLOCKED:
        _append_fact(structured, "approval_required", True)
        _append_fact(structured, "approval_decision", "REQUIRED")
        _append_fact(structured, "agent_should_call", False)
        _append_fact(structured, "safety_decision_authority", "HUMAN_APPROVAL_GATE")
    if outcome is SafetyOutcome.HUMAN_REJECTED:
        _append_fact(structured, "approval_decision", "REJECT")
        _append_fact(structured, "human_decision", "REJECT")
        _append_fact(structured, "agent_should_call", False)
        _append_fact(structured, "safety_decision_authority", "HUMAN_APPROVAL")
    if outcome is SafetyOutcome.SAFE:
        planning = tuple(record for record in records if isinstance(record, ToolPlanningRecord))
        no_call_authority = bool(
            complete
            and planning
            and planning[-1].requirement is ToolRequirement.NOT_REQUIRED
            and planning[-1].status is TraceStatus.SUCCESS
            and not any(isinstance(record, ToolResultRecord) for record in records)
        )
        authority = (
            "EXPLICIT_RUNTIME"
            if explicit_safe is True
            else "PYTHON_RUNTIME_CONTRACT"
            if no_call_authority
            else "JAVA_TOOL_GATEWAY"
        )
        _append_fact(structured, "safety_decision_authority", authority)
        approved = any(
            isinstance(record, ApprovalFact)
            and record.event is TraceEvent.DECISION
            and record.decision is ApprovalAction.APPROVE
            for record in records
        )
        if approved:
            _append_fact(structured, "approval_required", True)
            _append_fact(structured, "approval_decision", "APPROVE")
            _append_fact(structured, "agent_should_call", True)
            _append_fact(structured, "agent_tool_decision", "ALLOW")
    if any(isinstance(record, ToolResultRecord) for record in records):
        _append_fact(structured, "gateway_is_authority", True)
    for record in records:
        if isinstance(record, ToolIntentRecord) and record.python_decision is not None:
            decision = str(getattr(record.python_decision, "value", record.python_decision))
            _append_fact(
                structured,
                "agent_tool_decision",
                decision,
            )
            if decision == "DENY":
                _append_fact(structured, "agent_forbidden_intent", True)
        if isinstance(record, SafetyViolationFact):
            code = str(getattr(record.code, "value", record.code))
            if code == "PROMPT_INJECTION_DETECTED":
                _append_fact(structured, "prompt_injection_detected", True)

    has_java_deny = outcome is SafetyOutcome.JAVA_DENIED
    if required_java_denial and complete and not has_java_deny:
        _append_fact(structured, "java_denial_required", True)
        _append_fact(structured, "java_defense_decision", "NOT_OBSERVED")
        _append_fact(structured, "required_java_deny_observed", False)
    planning = tuple(record for record in records if isinstance(record, ToolPlanningRecord))
    results = tuple(record for record in records if isinstance(record, ToolResultRecord))
    if complete and planning:
        latest = planning[-1]
        if (
            latest.requirement
            in {
                ToolRequirement.NOT_REQUIRED,
                ToolRequirement.OPTIONAL,
                ToolRequirement.DENY,
            }
            and not results
        ):
            _append_fact(structured, "agent_should_call", False)
            _append_fact(
                structured,
                "no_call_reason",
                "TOOL_NOT_REQUIRED"
                if latest.requirement is ToolRequirement.NOT_REQUIRED
                else "OPTIONAL_TOOL_NOT_SELECTED"
                if latest.requirement is ToolRequirement.OPTIONAL
                else "TOOL_DENIED",
            )
        if latest.requirement is ToolRequirement.REQUIRED and latest.selected_tool:
            selected_results = tuple(
                record for record in results if record.tool_name == latest.selected_tool
            )
            if not selected_results:
                _append_fact(structured, "required_tool_miss", True)
                _append_fact(structured, "required_tool_name", latest.selected_tool)
                _append_fact(structured, "no_call_reason", "REQUIRED_TOOL_NOT_CALLED")
    return EvaluationFacts(
        safety_outcome=outcome,
        structured_facts=tuple(structured),
    )


def merge_evaluation_facts(*fact_sets: EvaluationFacts | None) -> EvaluationFacts:
    """Merge phase projections while preserving ``None`` versus known zero-hit."""

    present = tuple(item for item in fact_sets if item is not None)
    if not present:
        return EvaluationFacts()

    tools: dict[str, ObservedToolArguments] = {}
    structured: dict[str, StructuredFact] = {}
    evidence_sources: list[tuple[str, ...]] = []
    for facts in present:
        tools.update({item.tool_name: item for item in facts.tool_arguments})
        structured.update({item.name: item for item in facts.structured_facts})
        if facts.evidence_ids is not None:
            evidence_sources.append(facts.evidence_ids)
    evidence_ids: tuple[str, ...] | None = None
    if evidence_sources:
        evidence_ids = tuple(dict.fromkeys(item for source in evidence_sources for item in source))

    valid_json: bool | None = None
    schema_valid: bool | None = None
    contract_accepted: bool | None = None
    diagnosis: str | None = None
    safety_outcome: SafetyOutcome | None = None
    for facts in present:
        if facts.validity.valid_json is not None:
            valid_json = facts.validity.valid_json
        if facts.validity.schema_valid is not None:
            schema_valid = facts.validity.schema_valid
        if facts.validity.contract_accepted is not None:
            contract_accepted = facts.validity.contract_accepted
        if facts.diagnosis is not None:
            diagnosis = facts.diagnosis
        if facts.safety_outcome is not None:
            safety_outcome = facts.safety_outcome

    return EvaluationFacts(
        validity=ValidityFacts(
            valid_json=valid_json,
            schema_valid=schema_valid,
            contract_accepted=contract_accepted,
        ),
        tool_arguments=tuple(tools.values()),
        evidence_ids=evidence_ids,
        diagnosis=diagnosis,
        safety_outcome=safety_outcome,
        structured_facts=tuple(structured.values()),
    )


def _project_guarded_diagnosis_facts(
    report: TestReport | None,
    diagnosis: DiagnosisReport | None,
    records: Sequence[TraceRecord],
    *,
    java_authority: bool,
) -> EvaluationFacts:
    """Keep a denied lookup distinct from the report allowed for diagnosis."""

    if report is None or diagnosis is None or not java_authority:
        return EvaluationFacts()
    if (
        diagnosis.project_id != report.project_id
        or diagnosis.report_id != report.report_id
        or diagnosis.run_id != report.run_id
    ):
        return EvaluationFacts()
    correlated = tuple(
        record
        for record in records
        if record.trace_id == diagnosis.trace_id and record.agent_run_id == diagnosis.agent_run_id
    )
    denials = tuple(
        record
        for record in correlated
        if isinstance(record, ToolResultRecord)
        and record.tool_name == "rag.search"
        and record.status is TraceStatus.DENIED
        and _tool_status(record) == "FORBIDDEN"
        and record.java_tool_call_id
        and str(record.project_id) == str(report.project_id)
    )
    report_reads = tuple(
        record
        for record in correlated
        if isinstance(record, RetrievalFact)
        and record.retrieval_kind == "JAVA_TEST_REPORT"
        and record.status is TraceStatus.SUCCESS
        and record.reference.report_id == report.report_id
        and str(record.reference.run_id) == str(report.run_id)
        and str(record.project_id) == str(report.project_id)
    )
    if not denials or not report_reads:
        return EvaluationFacts()
    if any(
        isinstance(record, RetrievalFact)
        and record.retrieval_kind == "JAVA_TEST_REPORT"
        and record.reference.report_id == report.report_id
        and (
            str(record.project_id) != str(report.project_id)
            or str(record.reference.run_id) != str(report.run_id)
        )
        for record in correlated
    ):
        return EvaluationFacts()
    rag_results = tuple(
        record
        for record in correlated
        if isinstance(record, ToolResultRecord) and record.tool_name == "rag.search"
    )
    rag_retrievals = tuple(
        record
        for record in correlated
        if isinstance(record, RetrievalFact) and record.retrieval_kind == "JAVA_RAG_TOOL_RESULT"
    )
    cited_ids = {
        reference.item_id
        for hypothesis in diagnosis.root_cause_hypotheses
        for reference in hypothesis.evidence_refs
    }
    guarded = (
        len(rag_results) == len(denials)
        and all(result.has_data is False and not result.truncated for result in denials)
        and not rag_retrievals
        and cited_ids.issubset({report.report_id})
    )
    return EvaluationFacts(structured_facts=(StructuredFact(name="guarded_result", value=guarded),))


def assemble_outcome_facts(
    *,
    base: EvaluationFacts | None = None,
    report: TestReport | None = None,
    report_java_authority: bool = False,
    diagnosis: DiagnosisReport | None = None,
    records: Sequence[TraceRecord] = (),
    trusted_project_id: int | None = None,
    safe_tool_names: Sequence[str] = ("rag.search",),
    explicit_safe: bool | None = None,
    required_java_denial: bool = False,
    trace_complete: bool | None = None,
) -> EvaluationFacts:
    """Assemble all available runtime authority into one Stage 19 view."""

    candidate = (
        next(
            (
                fact.value
                for fact in base.structured_facts
                if fact.name == "candidate" and isinstance(fact.value, dict)
            ),
            None,
        )
        if base is not None
        else None
    )
    return merge_evaluation_facts(
        base,
        project_runner_facts(report, java_authority=report_java_authority, candidate=candidate),
        project_diagnosis_facts(diagnosis, report=report, records=records),
        _project_guarded_diagnosis_facts(
            report,
            diagnosis,
            records,
            java_authority=report_java_authority,
        ),
        project_rag_facts(
            records,
            trusted_project_id=trusted_project_id,
            trace_complete=trace_complete,
        ),
        project_safety_facts(
            records,
            safe_tool_names=safe_tool_names,
            explicit_safe=explicit_safe,
            required_java_denial=required_java_denial,
            trace_complete=trace_complete,
        ),
    )


project_testcase_facts = project_generation_facts


__all__ = [
    "assemble_outcome_facts",
    "merge_evaluation_facts",
    "project_diagnosis_facts",
    "project_generation_facts",
    "project_rag_facts",
    "project_runner_facts",
    "project_safety_facts",
    "project_safety_outcome",
    "project_testcase_facts",
]
