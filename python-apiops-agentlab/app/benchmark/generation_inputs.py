"""Input-side metadata resolution for generation-only benchmark tasks."""

from __future__ import annotations

import json
from dataclasses import dataclass
from json import JSONDecodeError
from pathlib import Path

from pydantic import ValidationError

from app.schemas.openapi_metadata import OpenApiMetadataDetail
from app.workflows.generation_context import documented_business_boundaries

from .golden import GOLDEN_FIXTURE_ROOT
from .models import BenchmarkTask, JavaResourceReference, TaskType

DEFAULT_GENERATION_METADATA_FIXTURE = (
    GOLDEN_FIXTURE_ROOT / "support" / "generation-openapi-metadata.json"
)
LIVE_RUNNER_GENERATION_METADATA_FIXTURE = (
    GOLDEN_FIXTURE_ROOT / "support" / "generation-live-runner-openapi-metadata.json"
)
_LOCAL_GENERATION_KEYS = frozenset({"runnerFixture", "authorityFixture"})
_LOCAL_GENERATION_PREFIX = "java://runner-testcase-dsl/"
_LIVE_RUNNER_GENERATION_TASK_IDS = frozenset(
    {
        "bench_task_testcase_happy_create_order_runner",
        "bench_task_testcase_business_inventory_runner",
        "bench_task_formal_testcase_inventory_conflict_runner",
    }
)
_LIVE_RUNNER_BASE_URL = "http://127.0.0.1:8080"
_LIVE_ORDER_SOURCE_REFERENCES = frozenset(
    {"java://runner-testcase-dsl/e2e/create-order-insufficient-inventory.json"}
)


class GenerationInputResolutionError(ValueError):
    """A declared generation input could not be resolved safely."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class ResolvedGenerationMetadata:
    """Typed metadata plus the input reference it replaced."""

    source_reference: str
    fixture_path: Path
    metadata: OpenApiMetadataDetail


def resolve_generation_metadata_input(
    task: BenchmarkTask,
    *,
    fixture_path: Path | None = None,
) -> ResolvedGenerationMetadata | None:
    """Resolve only declared local generation inputs; never inspect expected-side data."""

    if task.task_type is not TaskType.TESTCASE_GENERATION:
        return None
    local_entries = tuple(
        entry
        for entry in task.initial_state.entries
        if isinstance(entry, JavaResourceReference)
        and entry.key in _LOCAL_GENERATION_KEYS
        and entry.ref.startswith(_LOCAL_GENERATION_PREFIX)
    )
    if not local_entries:
        return None
    if len(local_entries) != 1:
        raise GenerationInputResolutionError(
            "GENERATION_INPUT_REFERENCE_AMBIGUOUS",
            "generation task must declare exactly one benchmark-local metadata input",
        )

    source_reference = local_entries[0].ref
    live_order_contract = (
        source_reference in _LIVE_ORDER_SOURCE_REFERENCES
        or task.benchmark_task_id in _LIVE_RUNNER_GENERATION_TASK_IDS
    )
    default_fixture = (
        LIVE_RUNNER_GENERATION_METADATA_FIXTURE
        if live_order_contract
        else DEFAULT_GENERATION_METADATA_FIXTURE
    )
    candidate = (fixture_path or default_fixture).resolve()
    if not candidate.is_file():
        raise GenerationInputResolutionError(
            "GENERATION_LOCAL_INPUT_MISSING",
            f"benchmark-local generation metadata is missing: {candidate}",
        )
    try:
        payload = json.loads(candidate.read_text(encoding="utf-8"))
    except (OSError, JSONDecodeError) as exc:
        raise GenerationInputResolutionError(
            "GENERATION_LOCAL_INPUT_INVALID_JSON",
            "benchmark-local generation metadata is not valid JSON",
        ) from exc
    if not isinstance(payload, dict):
        raise GenerationInputResolutionError(
            "GENERATION_LOCAL_INPUT_INVALID_SHAPE",
            "benchmark-local generation metadata must be a JSON object",
        )
    try:
        metadata = OpenApiMetadataDetail.model_validate(payload)
    except ValidationError as exc:
        raise GenerationInputResolutionError(
            "GENERATION_LOCAL_INPUT_INVALID_METADATA",
            "benchmark-local generation metadata does not satisfy OpenApiMetadataDetail",
        ) from exc
    if live_order_contract:
        _validate_live_runner_contract(metadata)
    return ResolvedGenerationMetadata(
        source_reference=source_reference,
        fixture_path=candidate,
        metadata=metadata,
    )


def _validate_live_runner_contract(metadata: OpenApiMetadataDetail) -> None:
    """Fail closed when Runner-bound generation input drifts from the live order API."""

    server_urls = tuple(
        server.get("url") for server in (metadata.servers or ()) if isinstance(server, dict)
    )
    response_codes = {response.status_code for response in metadata.response_schemas}
    request_schema = metadata.request_schemas[0].schema_ if metadata.request_schemas else None
    properties = request_schema.get("properties") if isinstance(request_schema, dict) else None
    items = properties.get("items") if isinstance(properties, dict) else None
    item_schema = items.get("items") if isinstance(items, dict) else None
    item_properties = (
        item_schema.get("properties") if isinstance(item_schema, dict) else None
    )
    product_id = (
        item_properties.get("productId") if isinstance(item_properties, dict) else None
    )
    quantity = item_properties.get("quantity") if isinstance(item_properties, dict) else None
    required = request_schema.get("required") if isinstance(request_schema, dict) else None
    item_required = item_schema.get("required") if isinstance(item_schema, dict) else None
    valid = (
        metadata.method == "POST"
        and metadata.path == "/orders"
        and server_urls == (_LIVE_RUNNER_BASE_URL,)
        and metadata.security == []
        and not metadata.parameters
        and isinstance(request_schema, dict)
        and required == ["userId", "items"]
        and isinstance(item_properties, dict)
        and item_required == ["productId", "quantity"]
        and isinstance(product_id, dict)
        and product_id.get("type") == "integer"
        and isinstance(quantity, dict)
        and quantity.get("type") == "integer"
        and {"200", "409"}.issubset(response_codes)
    )
    if not valid:
        raise GenerationInputResolutionError(
            "GENERATION_RUNNER_CONTRACT_MISMATCH",
            "benchmark-local generation metadata does not match the live Runner order contract",
        )
    try:
        boundaries = documented_business_boundaries(metadata)
    except ValueError as exc:
        raise GenerationInputResolutionError(
            "GENERATION_RUNNER_CONTRACT_MISMATCH",
            "live Runner business-boundary authority is invalid",
        ) from exc
    if len(boundaries) != 1 or boundaries[0][1].model_dump(by_alias=True) != {
        "name": "inventory.available_quantity",
        "requestPath": "items[].quantity",
        "selector": {"path": "items[].productId", "value": 2},
        "limit": 2,
        "operator": "GT",
        "statusCode": 409,
    }:
        raise GenerationInputResolutionError(
            "GENERATION_RUNNER_CONTRACT_MISMATCH",
            "live Runner metadata must retain its documented inventory rejection boundary",
        )


def is_local_generation_reference(task: BenchmarkTask) -> bool:
    """Return whether a generation task uses the local-input contract."""

    return task.task_type is TaskType.TESTCASE_GENERATION and any(
        isinstance(entry, JavaResourceReference)
        and entry.key in _LOCAL_GENERATION_KEYS
        and entry.ref.startswith(_LOCAL_GENERATION_PREFIX)
        for entry in task.initial_state.entries
    )


__all__ = [
    "DEFAULT_GENERATION_METADATA_FIXTURE",
    "LIVE_RUNNER_GENERATION_METADATA_FIXTURE",
    "GenerationInputResolutionError",
    "ResolvedGenerationMetadata",
    "is_local_generation_reference",
    "resolve_generation_metadata_input",
]
