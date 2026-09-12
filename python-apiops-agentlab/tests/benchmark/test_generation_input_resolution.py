from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.benchmark import (
    DEFAULT_GENERATION_METADATA_FIXTURE,
    LIVE_RUNNER_GENERATION_METADATA_FIXTURE,
    BenchmarkExecutionMode,
    GenerationInputResolutionError,
    JavaExecutionStatus,
    RealModelStage20WorkflowAdapter,
    StaticFixtureAdapter,
    is_local_generation_reference,
    load_dataset,
    resolve_generation_metadata_input,
)
from app.workflows.generation_context import TestStrategy, build_generation_context

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
FIXTURE_ROOT = Path(__file__).parent / "fixtures"
MANIFEST_PATH = FIXTURE_ROOT / "dataset-manifest.json"
SIDECAR_PATH = FIXTURE_ROOT / "stage21-execution-prerequisites.json"


def _local_generation_tasks():
    return tuple(task for task in load_dataset().tasks if is_local_generation_reference(task))


def test_remaining_symbolic_generation_inputs_resolve() -> None:
    tasks = _local_generation_tasks()

    assert len(tasks) == 15
    resolved = [resolve_generation_metadata_input(task) for task in tasks]

    assert all(value is not None for value in resolved)
    assert {value.source_reference for value in resolved if value is not None} == {
        next(
            entry.ref
            for entry in task.initial_state.entries
            if entry.kind == "JAVA_RESOURCE" and entry.ref.startswith("java://runner-testcase-dsl/")
        )
        for task in tasks
    }
    assert all(
        value is not None
        and value.metadata.api_id == "api-stage21-generation"
        and value.metadata.operation_id == "createOrder"
        for value in resolved
    )
    assert sum(
        value is not None
        and value.fixture_path == LIVE_RUNNER_GENERATION_METADATA_FIXTURE.resolve()
        for value in resolved
    ) == 4
    assert sum(
        value is not None
        and value.fixture_path == DEFAULT_GENERATION_METADATA_FIXTURE.resolve()
        for value in resolved
    ) == 11


def test_generation_resolver_uses_only_input_side_data() -> None:
    task = _local_generation_tasks()[0]
    altered = task.model_copy(
        update={
            "expected_output": {
                "metadataFixture": "this-must-never-be-read",
                "groundTruth": "this-must-never-be-read",
            }
        }
    )

    resolved = resolve_generation_metadata_input(altered)

    assert resolved is not None
    assert resolved.metadata.api_id == "api-stage21-generation"


@pytest.mark.parametrize(
    ("task_id", "strategy", "expected_status"),
    (
        ("bench_task_testcase_happy_create_order_runner", TestStrategy.HAPPY_PATH, "200"),
        (
            "bench_task_formal_testcase_inventory_conflict_runner",
            TestStrategy.BUSINESS_ERROR,
            "409",
        ),
        (
            "bench_task_testcase_business_inventory_runner",
            TestStrategy.BUSINESS_ERROR,
            "409",
        ),
    ),
)
def test_runner_required_generation_metadata_matches_live_order_contract(
    task_id: str,
    strategy: TestStrategy,
    expected_status: str,
) -> None:
    task = next(task for task in _local_generation_tasks() if task.benchmark_task_id == task_id)

    resolved = resolve_generation_metadata_input(task)

    assert resolved is not None
    context = build_generation_context(resolved.metadata, strategy)
    assert context.base_url == "http://127.0.0.1:8080"
    assert context.method == "POST"
    assert context.path == "/orders"
    assert context.request_facts[0].schema_ is not None
    request_schema = context.request_facts[0].schema_
    assert request_schema["required"] == ["userId", "items"]
    item_schema = request_schema["properties"]["items"]["items"]
    assert item_schema["required"] == ["productId", "quantity"]
    assert item_schema["properties"]["productId"]["type"] == "integer"
    assert [response.status_code for response in context.documented_responses] == [
        expected_status
    ]


def test_runner_required_generation_metadata_drift_fails_closed(tmp_path: Path) -> None:
    task = next(
        task
        for task in _local_generation_tasks()
        if task.benchmark_task_id == "bench_task_testcase_happy_create_order_runner"
    )
    payload = json.loads(
        LIVE_RUNNER_GENERATION_METADATA_FIXTURE.read_text(encoding="utf-8")
    )
    payload["servers"] = [{"url": "http://localhost"}]
    drifted = tmp_path / "drifted-runner-metadata.json"
    drifted.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(GenerationInputResolutionError) as exc_info:
        resolve_generation_metadata_input(task, fixture_path=drifted)

    assert exc_info.value.code == "GENERATION_RUNNER_CONTRACT_MISMATCH"


def test_inventory_source_resolves_live_contract_without_task_identity() -> None:
    task = next(
        task for task in _local_generation_tasks()
        if task.benchmark_task_id == "bench_task_testcase_boundary_inventory_limit"
    ).model_copy(update={"benchmark_task_id": "independent_inventory_boundary"})

    resolved = resolve_generation_metadata_input(task)

    assert resolved is not None
    assert resolved.fixture_path == LIVE_RUNNER_GENERATION_METADATA_FIXTURE.resolve()
    context = build_generation_context(resolved.metadata, TestStrategy.BOUNDARY)
    assert not resolved.metadata.parameters
    schema = context.request_facts[0].schema_
    assert schema is not None
    assert schema["required"] == ["userId", "items"]
    quantity = schema["properties"]["items"]["items"]["properties"]["quantity"]
    assert "maximum" not in quantity
    assert {response.status_code for response in context.documented_responses} == {"200", "409"}
    response = next(item for item in context.documented_responses if item.status_code == "409")
    assert response.schema_["properties"]["code"]["enum"] == ["ORDER_BUSINESS_CONFLICT"]


def test_inventory_source_rejects_generic_metadata_substitution() -> None:
    task = next(
        task for task in _local_generation_tasks()
        if task.benchmark_task_id == "bench_task_testcase_boundary_inventory_limit"
    ).model_copy(update={"benchmark_task_id": "independent_inventory_boundary"})

    with pytest.raises(GenerationInputResolutionError) as exc_info:
        resolve_generation_metadata_input(task, fixture_path=DEFAULT_GENERATION_METADATA_FIXTURE)

    assert exc_info.value.code == "GENERATION_RUNNER_CONTRACT_MISMATCH"


def test_inventory_source_rejects_missing_business_boundary_authority(tmp_path: Path) -> None:
    task = next(
        task for task in _local_generation_tasks()
        if task.benchmark_task_id == "bench_task_testcase_boundary_inventory_limit"
    )
    payload = json.loads(LIVE_RUNNER_GENERATION_METADATA_FIXTURE.read_text(encoding="utf-8"))
    payload["requestSchemas"][0]["schema"].pop("x-business-boundaries")
    drifted = tmp_path / "missing-business-boundary.json"
    drifted.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(GenerationInputResolutionError) as exc_info:
        resolve_generation_metadata_input(task, fixture_path=drifted)

    assert exc_info.value.code == "GENERATION_RUNNER_CONTRACT_MISMATCH"


@pytest.mark.parametrize(
    ("fixture_contents", "error_code"),
    ((None, "GENERATION_LOCAL_INPUT_MISSING"), ("{}", "GENERATION_LOCAL_INPUT_INVALID_METADATA")),
)
def test_invalid_or_missing_local_metadata_fails_closed(
    tmp_path: Path,
    fixture_contents: str | None,
    error_code: str,
) -> None:
    task = _local_generation_tasks()[0]
    candidate = tmp_path / "metadata.json"
    if fixture_contents is not None:
        candidate.write_text(fixture_contents, encoding="utf-8")

    with pytest.raises(GenerationInputResolutionError) as exc_info:
        resolve_generation_metadata_input(task, fixture_path=candidate)

    assert exc_info.value.code == error_code


@pytest.mark.anyio
async def test_existing_stage16_generation_graph_consumes_local_metadata() -> None:
    task = next(
        task
        for task in _local_generation_tasks()
        if task.benchmark_task_id
        == "bench_task_formal_testcase_happy_create_order_contract"
    )
    setup = await StaticFixtureAdapter().setup(task)
    candidate = json.loads(
        (REPOSITORY_ROOT / "examples" / "testcase-valid.json").read_text(encoding="utf-8")
    )
    candidate["projectId"] = 41
    candidate["apiId"] = "api-stage21-generation"
    candidate["steps"][0]["request"]["path"] = "/orders"

    class CapturingLLM:
        async def complete(self, prompt: str) -> str:
            self.prompt = prompt
            return json.dumps(candidate)

    llm = CapturingLLM()
    outcome = await RealModelStage20WorkflowAdapter(
        llm,
        repository_root=REPOSITORY_ROOT,
    ).execute(
        task,
        setup,
        trace_id="trace:local-generation-input",
        agent_run_id="agent_run:local-generation-input",
    )

    assert outcome.execution_mode is BenchmarkExecutionMode.REAL_MODEL
    assert outcome.java_execution_status is JavaExecutionStatus.NOT_APPLICABLE
    assert outcome.model_call_ids
    assert "api-stage21-generation" in llm.prompt
    assert "createOrder" in llm.prompt
    assert "/orders" in llm.prompt


def test_dataset_and_prerequisite_sidecar_remain_complete() -> None:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    sidecar = json.loads(SIDECAR_PATH.read_text(encoding="utf-8"))
    manifest_ids = [entry["benchmarkTaskId"] for entry in manifest["tasks"]]
    sidecar_ids = [entry["benchmarkTaskId"] for entry in sidecar["tasks"]]

    assert len(manifest_ids) == 105
    assert len(set(manifest_ids)) == 105
    assert len(sidecar_ids) == 105
    assert len(set(sidecar_ids)) == 105
    assert sidecar_ids == manifest_ids


@pytest.mark.parametrize(
    ("task_id", "api_id"),
    (
        ("bench_task_formal_testcase_boundary_inventory_zero", "formal-final-acceptance"),
        ("bench_task_formal_testcase_get_orders_limit", "stage21-get-orders"),
        ("bench_task_formal_testcase_happy_get_orders_metadata", "stage21-get-orders"),
        ("bench_task_formal_testcase_list_products_page_size_one", "stage21-list-products"),
        ("bench_task_testcase_boundary_list_products_page_size", "stage21-list-products"),
    ),
)
def test_java_generation_metadata_reference_has_exact_operation_identity(
    task_id: str,
    api_id: str,
) -> None:
    class NoopLLM:
        async def complete(self, prompt: str) -> str:
            del prompt
            return "{}"

    task = next(task for task in load_dataset().tasks if task.benchmark_task_id == task_id)
    adapter = RealModelStage20WorkflowAdapter(NoopLLM(), repository_root=REPOSITORY_ROOT)

    assert adapter._api_id(task) == api_id
