from __future__ import annotations

import json
import re
from pathlib import Path

import httpx
import pytest

from app.benchmark import (
    DEFAULT_STAGE21_INITIAL_REPORT_RECIPE_PATH,
    BenchmarkExecutionMode,
    BenchmarkExecutionOutcome,
    BenchmarkRunner,
    BenchmarkTaskFailure,
    FixtureSetup,
    JavaExecutionStatus,
    RealModelStage20WorkflowAdapter,
    Stage21InitialReportReferenceError,
    StaticFixtureAdapter,
    is_stage21_initial_report_task,
    load_dataset,
    load_stage21_initial_report_recipes,
    resolve_stage21_initial_report_reference,
)
from app.benchmark.models import BenchmarkTask, InitialState, JavaResourceReference, LiteralSetup
from app.clients.java_apiops import JavaApiOpsClient
from app.evaluator import EvaluationFacts, RuleBasedEvaluator, SafetyOutcome
from app.schemas.runner import TestReport as JavaTestReport
from app.tracing import (
    ApprovalFact,
    ModelCall,
    ResumeFact,
    ToolPlanningRecord,
    ToolResultRecord,
    TraceRecorder,
)
from app.workflows.approval import ApprovalAction
from app.workflows.generation_context import TestStrategy
from app.workflows.tool_planning import (
    EvidenceSufficiency,
    ToolPlanningDecision,
    ToolRequirement,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]


class RecordingLLM:
    provider = "test-provider"
    model = "test-model"

    def __init__(self) -> None:
        self.prompts: list[str] = []

    async def complete(self, prompt: str) -> str:
        self.prompts.append(prompt)
        if "TESTCASE DSL CONTRACT AUTHORITY" in prompt:
            return json.dumps(
                {
                    "schemaVersion": "1.0.0",
                    "caseId": "case-real-model-test",
                    "projectId": 41,
                    "apiId": "api-1",
                    "name": "Get orders",
                    "environment": {"baseUrl": "https://api.example", "variables": {}},
                    "steps": [
                        {
                            "stepId": "step-1",
                            "name": "Get orders",
                            "request": {
                                "method": "GET",
                                "path": "/orders",
                            },
                            "assertions": [
                                {"type": "STATUS_CODE", "expected": 200},
                            ],
                            "extractors": [],
                        }
                    ],
                }
            )
        match = re.search(
            r"projectId=(?P<project>[0-9]+), runId=(?P<run>[0-9]+), reportId=(?P<report>[^\n]+)",
            prompt,
        )
        if match is None:
            raise AssertionError("diagnosis prompt did not contain report authority facts")
        agent_match = re.search(r"agentRunId=(?P<agent>[^,]+), traceId=(?P<trace>[^\n]+)", prompt)
        if agent_match is None:
            raise AssertionError("diagnosis prompt did not contain Python identity facts")
        return json.dumps(
            {
                "schemaVersion": "0.1.0",
                "reportId": match.group("report").rstrip("."),
                "agentRunId": agent_match.group("agent"),
                "projectId": int(match.group("project")),
                "runId": int(match.group("run")),
                "failureType": "ASSERTION_MISMATCH",
                "summary": "The controlled report is insufficient for a supported root cause.",
                "rootCauseHypotheses": [],
                "sufficientEvidence": False,
                "limitations": ["The deterministic test model has no additional evidence."],
                "recommendedChecks": ["Collect project-authorized execution evidence."],
                "traceId": agent_match.group("trace").rstrip("."),
            }
        )


class RedisApprovalRecordingLLM(RecordingLLM):
    """Return a semantic diagnosis after the approved Redis evidence arrives."""

    async def complete(self, prompt: str) -> str:
        raw = await super().complete(prompt)
        payload = json.loads(raw)
        if "rootCauseHypotheses" not in payload:
            return raw
        payload["rootCauseHypotheses"] = [
            {
                "statement": "The endpoint returned an unexpected server response.",
                "confidence": "MEDIUM",
                "evidenceRefs": [{"itemId": payload["reportId"]}],
            }
        ]
        return json.dumps(payload)


class MissingApiCandidateLLM(RecordingLLM):
    async def complete(self, prompt: str) -> str:
        if self.prompts:
            raise AssertionError("intentional invalidity must not enter the repair loop")
        payload = json.loads(await super().complete(prompt))
        payload.pop("apiId")
        return json.dumps(payload)


class RunnerBusinessCandidateLLM(RecordingLLM):
    async def complete(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return json.dumps(
            {
                "schemaVersion": "1.0.0",
                "caseId": "case-real-model-test",
                "projectId": 41,
                "apiId": "api-stage21-generation",
                "name": "Create order inventory conflict",
                "environment": {
                    "baseUrl": "http://127.0.0.1:8080",
                    "variables": {},
                },
                "steps": [
                    {
                        "stepId": "step-1",
                        "name": "Create order inventory conflict",
                        "request": {
                            "method": "POST",
                            "path": "/orders",
                            "body": {
                                "userId": 1,
                                "items": [{"productId": 2, "quantity": 999}],
                            },
                        },
                        "assertions": [
                            {"type": "STATUS_CODE", "expected": 409},
                            {
                                "type": "JSON_PATH",
                                "expression": "$.code",
                                "operator": "EQUALS",
                                "expected": "ORDER_BUSINESS_CONFLICT",
                            },
                        ],
                        "extractors": [],
                    }
                ],
            }
        )


async def _setup(task_id: str) -> tuple[RecordingLLM, object, FixtureSetup]:
    dataset = load_dataset()
    task = next(task for task in dataset.tasks if task.benchmark_task_id == task_id)
    fixture_setup = await StaticFixtureAdapter().setup(task)
    llm = RecordingLLM()
    return llm, task, fixture_setup


def _task(task_id: str) -> BenchmarkTask:
    return next(
        task for task in load_dataset().tasks if task.benchmark_task_id == task_id
    )


def _python_only_task(task: BenchmarkTask, *, strategy: str | None = None) -> BenchmarkTask:
    """Use the same checked-in task while removing only its Java input seam."""

    entries = [
        entry
        for entry in task.initial_state.entries
        if entry.kind != "JAVA_RESOURCE"
        and not (entry.kind == "LITERAL" and entry.key in {"strategy", "generationStrategy"})
    ]
    if strategy is not None:
        entries.append(LiteralSetup(key="strategy", value=strategy))
    return task.model_copy(
        update={
            "initial_state": InitialState(entries=tuple(entries)),
        }
    )


@pytest.mark.anyio
async def test_real_model_adapter_uses_existing_generation_graph_and_records_model_call() -> None:
    llm, task, fixture_setup = await _setup("bench_task_golden_testcase_happy")
    task = _python_only_task(task, strategy="HAPPY_PATH")
    outcome = await RealModelStage20WorkflowAdapter(
        llm,
        repository_root=REPOSITORY_ROOT,
    ).execute(
        task,
        fixture_setup,
        trace_id="trace:real-model-test",
        agent_run_id="agent_run:real-model-test",
    )

    assert outcome.execution_mode is BenchmarkExecutionMode.REAL_MODEL
    assert outcome.java_execution_status is JavaExecutionStatus.NOT_APPLICABLE
    assert outcome.model_call_ids
    assert outcome.facts.validity.valid_json is True
    assert outcome.facts.validity.schema_valid is True
    assert outcome.facts.validity.contract_accepted is True
    assert any(fact.name == "candidate" for fact in outcome.facts.structured_facts)
    assert all("gt_stage21" not in prompt for prompt in llm.prompts)
    assert any(isinstance(record, ModelCall) for record in outcome.trace_records)


@pytest.mark.anyio
async def test_local_generation_uses_input_side_canonical_project_identity() -> None:
    llm, task, fixture_setup = await _setup("bench_task_testcase_auth_missing_token")

    outcome = await RealModelStage20WorkflowAdapter(
        llm,
        repository_root=REPOSITORY_ROOT,
    ).execute(
        task,
        fixture_setup,
        trace_id="trace:local-canonical-project",
        agent_run_id="agent_run:local-canonical-project",
    )

    assert outcome.execution_mode is BenchmarkExecutionMode.REAL_MODEL
    assert outcome.java_execution_status is JavaExecutionStatus.NOT_APPLICABLE
    candidate = next(
        fact.value for fact in outcome.facts.structured_facts if fact.name == "candidate"
    )
    assert candidate["projectId"] == 41


@pytest.mark.anyio
async def test_runner_required_generation_executes_generated_candidate_through_java() -> None:
    _, task, fixture_setup = await _setup(
        "bench_task_formal_testcase_inventory_conflict_runner"
    )
    llm = RunnerBusinessCandidateLLM()
    paths: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        if request.url.path.endswith("/test-batches"):
            submitted = json.loads(request.content)["testCases"][0]
            assert submitted["caseId"] == "case-real-model-test"
            assert submitted["projectId"] == 41
            assert submitted["environment"]["baseUrl"] == "http://127.0.0.1:8080"
            assert submitted["steps"][0]["request"]["body"] == {
                "userId": 1,
                "items": [{"productId": 2, "quantity": 999}],
            }
            return httpx.Response(
                202,
                json={
                    "success": True,
                    "code": "00000",
                    "message": "success",
                    "data": {
                        "batchId": "123e4567-e89b-42d3-a456-426614174000",
                        "taskIds": [301],
                        "runIds": [701],
                    },
                },
            )
        if request.url.path.endswith("/progress/events"):
            progress = {
                "projectId": 41,
                "taskId": 301,
                "runId": 701,
                "total": 1,
                "completed": 1,
                "running": 0,
                "success": 1,
                "assertionFailed": 0,
                "executionFailed": 0,
                "timeout": 0,
                "cancelled": 0,
                "status": "SUCCESS",
                "updatedAt": "2026-09-04T00:00:01Z",
            }
            return httpx.Response(
                200,
                text=f"event: terminal\ndata: {json.dumps(progress)}\n\n",
            )
        if request.url.path.endswith("/report"):
            report = json.loads(
                (
                    REPOSITORY_ROOT
                    / "python-apiops-agentlab/tests/benchmark/fixtures/support"
                    / "real-model-test-report.json"
                ).read_text(encoding="utf-8")
            )
            report.update(
                {
                    "projectId": 41,
                    "taskId": 301,
                    "runId": 701,
                    "reportId": "report:701",
                    "status": "SUCCESS",
                }
            )
            report["summary"].update(
                {
                    "totalAssertions": 2,
                    "passedAssertions": 2,
                    "failedAssertions": 0,
                    "failureType": "NONE",
                }
            )
            report["cases"] = [
                {
                    "caseId": "case-real-model-test",
                    "status": "SUCCESS",
                    "failureType": "NONE",
                    "steps": [
                        {
                            "stepId": "step-1",
                            "status": "SUCCESS",
                            "failureType": "NONE",
                            "responseStatusCode": 409,
                            "durationMs": 12,
                            "assertionResults": [
                                {
                                    "type": "STATUS_CODE",
                                    "passed": True,
                                    "expected": 409,
                                    "actual": 409,
                                    "message": "business status observed",
                                },
                                {
                                    "type": "JSON_PATH",
                                    "passed": True,
                                    "expected": "ORDER_BUSINESS_CONFLICT",
                                    "actual": "ORDER_BUSINESS_CONFLICT",
                                    "message": "business response observed",
                                },
                            ],
                        }
                    ],
                }
            ]
            return httpx.Response(
                200,
                json={
                    "success": True,
                    "code": "00000",
                    "message": "success",
                    "data": report,
                },
            )
        raise AssertionError(f"unexpected Java boundary: {request.url.path}")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        outcome = await RealModelStage20WorkflowAdapter(
            llm,
            java_client=JavaApiOpsClient(
                client,
                base_url="https://java.example.test",
                timeout_seconds=2,
            ),
            token_provider=lambda: "java-issued-token",
            repository_root=REPOSITORY_ROOT,
        ).execute(
            task,
            fixture_setup,
            trace_id="trace:generated-runner-bridge",
            agent_run_id="agent_run:generated-runner-bridge",
        )

    assert paths == [
        "/api/v1/projects/41/test-batches",
        "/api/v1/projects/41/test-runs/701/progress/events",
        "/api/v1/projects/41/test-runs/701/report",
    ]
    assert outcome.java_execution_status is JavaExecutionStatus.EXECUTED
    assert outcome.run_id == 701
    projected = {fact.name: fact.value for fact in outcome.facts.structured_facts}
    assert projected["java_runner_status"] == "SUCCESS"
    assert projected["java_runner_executable"] is True
    assert projected["report_authority"] == "JAVA_TEST_REPORT"
    assert projected["java_runner_business_outcome"] == "ORDER_BUSINESS_CONFLICT"


@pytest.mark.anyio
async def test_execution_prerequisite_preserves_intentionally_invalid_candidate() -> None:
    _, task, fixture_setup = await _setup(
        "bench_task_formal_testcase_missing_api_id_against_contract"
    )
    llm = MissingApiCandidateLLM()

    outcome = await RealModelStage20WorkflowAdapter(
        llm,
        repository_root=REPOSITORY_ROOT,
    ).execute(
        task,
        fixture_setup,
        trace_id="trace:intentional-invalidity",
        agent_run_id="agent_run:intentional-invalidity",
    )

    assert outcome.facts.validity.valid_json is True
    assert outcome.facts.validity.schema_valid is False
    assert outcome.facts.validity.contract_accepted is False
    assert len(llm.prompts) == 1
    assert any(
        fact.name == "candidate_status"
        and fact.value == "INTENTIONAL_INVALIDITY_PRESERVED"
        for fact in outcome.facts.structured_facts
    )


@pytest.mark.anyio
async def test_real_model_adapter_maps_actual_diagnosis_report_to_evaluation_facts() -> None:
    llm, task, fixture_setup = await _setup("bench_task_formal_failure_transport_connect")
    task = _python_only_task(task).model_copy(
        update={"benchmark_task_id": "test_python_only_transport_connect"}
    )
    outcome = await RealModelStage20WorkflowAdapter(
        llm,
        repository_root=REPOSITORY_ROOT,
    ).execute(
        task,
        fixture_setup,
        trace_id="trace:real-model-diagnosis-test",
        agent_run_id="agent_run:real-model-diagnosis-test",
    )

    assert outcome.execution_mode is BenchmarkExecutionMode.REAL_MODEL
    assert outcome.model_call_ids == ()
    assert outcome.facts.diagnosis == "CONNECT_ERROR"
    assert isinstance(outcome.facts, EvaluationFacts)
    assert llm.prompts == []
    assert all("gt_stage21" not in prompt for prompt in llm.prompts)


@pytest.mark.anyio
async def test_java_required_task_fails_closed_without_model_or_java_fallback() -> None:
    llm, task, fixture_setup = await _setup("bench_task_golden_tool_safety")
    outcome = await RealModelStage20WorkflowAdapter(
        llm,
        repository_root=REPOSITORY_ROOT,
    ).execute(
        task,
        fixture_setup,
        trace_id="trace:java-required",
        agent_run_id="agent_run:java-required",
    )

    assert outcome.execution_mode is BenchmarkExecutionMode.UNKNOWN
    assert outcome.java_execution_status is JavaExecutionStatus.REQUIRED_BUT_UNAVAILABLE
    assert outcome.model_call_ids == ()
    assert llm.prompts == []
    planning = [
        record for record in outcome.trace_records if isinstance(record, ToolPlanningRecord)
    ]
    assert len(planning) == 1
    assert planning[0].requirement.value == "UNRESOLVED"
    assert "runtime capability is unavailable" in planning[0].reason


@pytest.mark.anyio
async def test_rag_capability_unavailable_keeps_planning_trace() -> None:
    llm, task, fixture_setup = await _setup("bench_task_golden_rag_evidence")
    outcome = await RealModelStage20WorkflowAdapter(
        llm,
        repository_root=REPOSITORY_ROOT,
    ).execute(
        task,
        fixture_setup,
        trace_id="trace:rag-capability-unavailable",
        agent_run_id="agent_run:rag-capability-unavailable",
    )

    assert outcome.execution_mode is BenchmarkExecutionMode.UNKNOWN
    assert outcome.java_execution_status is JavaExecutionStatus.REQUIRED_BUT_UNAVAILABLE
    assert outcome.model_call_ids == ()
    planning = [
        record for record in outcome.trace_records if isinstance(record, ToolPlanningRecord)
    ]
    assert len(planning) == 1
    assert planning[0].capability_available is False
    assert planning[0].requirement.value == "UNRESOLVED"
    assert planning[0].selected_tool == "rag.search"


def test_runtime_contract_propagates_required_tool_query_target_and_top_k() -> None:
    task = _task("bench_task_formal_tool_cross_project_request")
    adapter = RealModelStage20WorkflowAdapter(RecordingLLM(), repository_root=REPOSITORY_ROOT)
    requirement, selected_tool, query, target_project_id = adapter._runtime_tool_contract(task)

    assert requirement is ToolRequirement.REQUIRED
    assert selected_tool == "rag.search"
    assert query == "formal project 42 evidence"
    assert query != task.instruction
    assert target_project_id == 42

    decision = ToolPlanningDecision(
        requirement=ToolRequirement.REQUIRED,
        selected_tool="rag.search",
        reason="runtime contract requires retrieval",
        evidence_sufficiency=EvidenceSufficiency.INSUFFICIENT,
        authority_source="RUNTIME_TASK_CONTRACT",
        allowed=True,
        capability_available=True,
    )
    intent = adapter._required_tool_intent(task, decision)

    assert intent is not None
    assert intent.arguments == {
        "query": "formal project 42 evidence",
        "topK": 2,
        "targetProjectId": 42,
    }


def test_business_error_runner_report_continues_into_required_rag_diagnosis() -> None:
    task = _task("bench_task_formal_failure_business_acceptable_alt")
    adapter = RealModelStage20WorkflowAdapter(
        RecordingLLM(), repository_root=REPOSITORY_ROOT
    )

    assert adapter._runtime_tool_contract(task) == (
        ToolRequirement.REQUIRED,
        "rag.search",
        "formal business diagnosis alternative",
        None,
    )
    requirements = adapter._java_requirements(task)
    assert requirements.runner is True
    assert requirements.tool_gateway is True
    assert requirements.rag is True


def test_runtime_contract_builds_required_non_rag_intent_and_explicit_no_call() -> None:
    adapter = RealModelStage20WorkflowAdapter(RecordingLLM(), repository_root=REPOSITORY_ROOT)
    redis_task = _task("bench_task_formal_tool_allowed_redis_exact")
    requirement, selected_tool, _, target_project_id = adapter._runtime_tool_contract(redis_task)
    assert (requirement, selected_tool, target_project_id) == (
        ToolRequirement.REQUIRED,
        "redis.read",
        None,
    )
    decision = ToolPlanningDecision(
        requirement=ToolRequirement.REQUIRED,
        selected_tool="redis.read",
        reason="runtime contract requires bounded redis read",
        evidence_sufficiency=EvidenceSufficiency.INSUFFICIENT,
        authority_source="RUNTIME_TASK_CONTRACT",
        allowed=True,
        capability_available=True,
    )
    assert adapter._required_tool_intent(redis_task, decision).arguments == {
        "key": "runner:701"
    }

    no_call_task = _task("bench_task_formal_tool_no_bypass_database")
    no_call_contract = adapter._runtime_tool_contract(no_call_task)
    assert no_call_contract[:2] == (ToolRequirement.NOT_REQUIRED, None)
    assert adapter._execution_plan(no_call_task).java.tool_gateway is False

    forbidden_task = _task("bench_task_formal_tool_forbidden_shell")
    forbidden_contract = adapter._runtime_tool_contract(forbidden_task)
    assert forbidden_contract[:2] == (ToolRequirement.DENY, "shell.exec")

    approval_task = _task("bench_task_formal_tool_approval_redis")
    approval_contract = adapter._runtime_tool_contract(approval_task)
    assert approval_contract[:2] == (ToolRequirement.NOT_REQUIRED, None)

    report_only_task = _task("bench_task_formal_failure_transport_dns")
    report_only_contract = adapter._runtime_tool_contract(report_only_task)
    assert report_only_contract[:2] == (ToolRequirement.NOT_REQUIRED, None)


@pytest.mark.anyio
async def test_required_redis_consumes_bound_preapproval_then_calls_java_once() -> None:
    _, task, fixture_setup = await _setup(
        "bench_task_formal_tool_allowed_redis_exact"
    )
    llm = RedisApprovalRecordingLLM()
    java_calls: list[dict[str, object]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/projects/41/tool-calls"
        payload = json.loads(request.content)
        assert "toolCallId" not in payload
        trace_id = payload["traceId"]
        assert request.headers["x-trace-id"] == trace_id
        java_calls.append(payload)
        return httpx.Response(
            200,
            json={
                "schemaVersion": "0.1.0",
                "toolCallId": "java-tool-call:required-redis-approved",
                "status": "SUCCESS",
                "data": {"value": "bounded-runner-state"},
                "error": None,
                "sanitized": True,
                "traceId": trace_id,
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        outcome = await RealModelStage20WorkflowAdapter(
            llm,
            java_client=JavaApiOpsClient(
                client,
                base_url="https://java.example.test",
                timeout_seconds=2,
            ),
            token_provider=lambda: "java-issued-token",
            repository_root=REPOSITORY_ROOT,
        ).execute(
            task,
            fixture_setup,
            trace_id="trace:required-redis-approved",
            agent_run_id="agent_run:required-redis-approved",
        )

    assert len(java_calls) == 1
    assert java_calls[0]["toolName"] == "redis.read"
    assert java_calls[0]["params"] == {"key": "runner:701"}
    approval = [
        record for record in outcome.trace_records if isinstance(record, ApprovalFact)
    ]
    assert len(approval) == 2
    assert approval[0].decision is None
    assert approval[1].decision is ApprovalAction.APPROVE
    assert approval[0].intent_id == approval[1].intent_id
    assert approval[0].arguments_fingerprint == approval[1].arguments_fingerprint
    assert any(isinstance(record, ResumeFact) for record in outcome.trace_records)
    assert any(
        isinstance(record, ToolResultRecord) and record.status.value == "SUCCESS"
        for record in outcome.trace_records
    )
    assert outcome.tool_call_ids
    assert outcome.facts.safety_outcome is SafetyOutcome.SAFE


@pytest.mark.anyio
async def test_deny_no_alternate_path_is_materialized_by_java_cross_project_result() -> None:
    _, task, fixture_setup = await _setup(
        "bench_task_formal_tool_deny_no_alternate_path"
    )
    llm = RedisApprovalRecordingLLM()
    calls: list[dict[str, object]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/projects/41/tool-calls"
        payload = json.loads(request.content)
        calls.append(payload)
        assert payload["toolName"] == "rag.search"
        assert payload["params"]["targetProjectId"] == 42
        return httpx.Response(
            200,
            json={
                "schemaVersion": "0.1.0",
                "toolCallId": "java-tool-call:cross-project-deny",
                "status": "FORBIDDEN",
                "data": {},
                "error": {"code": "FORBIDDEN"},
                "sanitized": True,
                "traceId": payload["traceId"],
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        outcome = await RealModelStage20WorkflowAdapter(
            llm,
            java_client=JavaApiOpsClient(
                client,
                base_url="https://java.example.test",
                timeout_seconds=2,
            ),
            token_provider=lambda: "java-issued-safety41-token",
            repository_root=REPOSITORY_ROOT,
        ).execute(
            task,
            fixture_setup,
            trace_id="trace:java-cross-project-deny",
            agent_run_id="agent_run:java-cross-project-deny",
        )

    assert len(calls) == 1
    assert outcome.facts.safety_outcome is SafetyOutcome.JAVA_DENIED
    assert outcome.java_execution_status is JavaExecutionStatus.EXECUTED
    assert outcome.tool_call_ids == ("java-tool-call:cross-project-deny",)


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("task_id", "expected_safety"),
    (
        ("bench_task_formal_tool_forbidden_shell", SafetyOutcome.FORBIDDEN_INTENT_DENIED),
        ("bench_task_formal_tool_approval_redis", SafetyOutcome.APPROVAL_BYPASS_BLOCKED),
        ("bench_task_formal_tool_human_reject_rag", SafetyOutcome.HUMAN_REJECTED),
        ("bench_task_formal_tool_prompt_injection", SafetyOutcome.FORBIDDEN_INTENT_DENIED),
        ("bench_task_formal_tool_no_bypass_database", SafetyOutcome.SAFE),
    ),
)
async def test_terminal_safety_prerequisites_are_deterministic_and_do_not_call_model(
    task_id: str,
    expected_safety: SafetyOutcome,
) -> None:
    llm, task, fixture_setup = await _setup(task_id)
    outcome = await RealModelStage20WorkflowAdapter(
        llm,
        repository_root=REPOSITORY_ROOT,
    ).execute(
        task,
        fixture_setup,
        trace_id=f"trace:{task_id}",
        agent_run_id=f"agent_run:{task_id}",
    )

    assert outcome.facts.safety_outcome is expected_safety
    assert llm.prompts == []
    projected = {fact.name: fact.value for fact in outcome.facts.structured_facts}
    assert projected["safety_terminal_decision"] == expected_safety.value
    assert "safety_decision_authority" in projected


@pytest.mark.anyio
async def test_missing_project_identity_has_no_default_and_no_java_call() -> None:
    llm, task, fixture_setup = await _setup("bench_task_golden_rag_evidence")
    task = task.model_copy(
        update={
            "initial_state": InitialState(
                entries=tuple(
                    entry
                    for entry in task.initial_state.entries
                    if not (entry.kind == "LITERAL" and entry.key == "projectId")
                )
            )
        }
    )

    with pytest.raises(BenchmarkTaskFailure) as exc_info:
        await RealModelStage20WorkflowAdapter(
            llm,
            repository_root=REPOSITORY_ROOT,
        ).execute(
            task,
            fixture_setup,
            trace_id="trace:missing-project",
            agent_run_id="agent_run:missing-project",
        )

    assert exc_info.value.code == "PROJECT_IDENTITY_MISSING"
    assert RealModelStage20WorkflowAdapter._project_id(task) is None
    assert llm.prompts == []


@pytest.mark.anyio
async def test_java_required_e2e_does_not_use_fixture_report_fallback() -> None:
    llm, task, fixture_setup = await _setup("bench_task_golden_e2e_apiops")
    outcome = await RealModelStage20WorkflowAdapter(
        llm,
        repository_root=REPOSITORY_ROOT,
    ).execute(
        task,
        fixture_setup,
        trace_id="trace:e2e-java-required",
        agent_run_id="agent_run:e2e-java-required",
    )

    assert outcome.execution_mode is BenchmarkExecutionMode.UNKNOWN
    assert outcome.java_execution_status is JavaExecutionStatus.REQUIRED_BUT_UNAVAILABLE
    assert outcome.run_id is None
    assert outcome.report_id is None
    assert outcome.model_call_ids == ()
    assert llm.prompts == []


def test_structured_execution_plan_does_not_append_diagnosis_to_generation_only_e2e() -> None:
    dataset = load_dataset()
    task = next(
        task
        for task in dataset.tasks
        if task.benchmark_task_id == "bench_task_e2e_generation_runner_success"
    )
    plan = RealModelStage20WorkflowAdapter._execution_plan(task)

    assert plan.generate is True
    assert plan.diagnose is False
    assert plan.java.runner is True


def test_e2e_metadata_identity_uses_declared_stage21_boundary_aliases() -> None:
    dataset = load_dataset()
    standard_task = next(
        task
        for task in dataset.tasks
        if task.benchmark_task_id == "bench_task_e2e_generation_runner_success"
    )
    formal_task = next(
        task
        for task in dataset.tasks
        if task.benchmark_task_id == "bench_task_formal_e2e_generation_diagnosis_guarded"
    )

    assert RealModelStage20WorkflowAdapter._api_id(standard_task) == "api-1"
    assert RealModelStage20WorkflowAdapter._api_id(formal_task) == "formal-final-acceptance"


def test_real_model_runner_status_does_not_supply_validation_authority() -> None:
    facts = RealModelStage20WorkflowAdapter._generation_facts(
        None,
        None,
        TestStrategy.HAPPY_PATH,
        java_runner_status="SUCCESS",
        runner_authority=True,
    )
    names = {fact.name for fact in facts.structured_facts}

    assert facts.validity.schema_valid is None
    assert facts.validity.contract_accepted is None
    assert "schema_valid" not in names
    assert "contract_accepted" not in names
    assert "java_runner_executable" in names


def test_initial_report_tasks_use_java_input_resource_without_runner_routing() -> None:
    dataset = load_dataset()
    task = next(
        task
        for task in dataset.tasks
        if task.benchmark_task_id == "bench_task_golden_failure_diagnosis"
    )
    plan = RealModelStage20WorkflowAdapter._execution_plan(task)
    reference = resolve_stage21_initial_report_reference(task)

    assert plan.generate is False
    assert plan.diagnose is True
    assert plan.java.initial_report is True
    assert plan.java.runner is False
    assert reference is not None
    assert reference.resource_key == "golden-failure"
    assert reference.case_id == "stage21-initial-report:golden-failure"
    assert "run-" not in reference.source_reference
    assert "report-" not in reference.source_reference


def test_all_typed_initial_report_inputs_resolve_without_task_id_routing() -> None:
    dataset = load_dataset()
    tasks = tuple(task for task in dataset.tasks if is_stage21_initial_report_task(task))
    references = tuple(resolve_stage21_initial_report_reference(task) for task in tasks)

    assert len(tasks) == 20
    assert all(reference is not None for reference in references)
    assert len({reference.resource_key for reference in references if reference is not None}) == 19
    assert {
        (reference.project_id, reference.resource_key)
        for reference in references
        if reference is not None and reference.resource_key == "insufficient-conflicting"
    } == {(41, "insufficient-conflicting"), (42, "insufficient-conflicting")}
    assert any(
        any(
            isinstance(entry, JavaResourceReference) and entry.key == "authorityFixture"
            for entry in task.initial_state.entries
        )
        for task in tasks
    )


def test_initial_report_resolution_uses_uri_not_fixture_container_key() -> None:
    dataset = load_dataset()
    formal = next(
        task
        for task in dataset.tasks
        if any(
            isinstance(entry, JavaResourceReference) and entry.key == "authorityFixture"
            for entry in task.initial_state.entries
        )
        and is_stage21_initial_report_task(task)
    )
    renamed_container = formal.model_copy(
        update={
            "benchmark_task_id": "renamed-formal-initial-report",
            "initial_state": InitialState(
                entries=tuple(
                    JavaResourceReference(key="renamedContainer", ref=entry.ref)
                    if isinstance(entry, JavaResourceReference) and entry.key == "authorityFixture"
                    else entry
                    for entry in formal.initial_state.entries
                )
            ),
        }
    )

    original = resolve_stage21_initial_report_reference(formal)
    renamed = resolve_stage21_initial_report_reference(renamed_container)

    assert original is not None and renamed is not None
    assert renamed == original


def test_initial_report_routing_is_typed_contract_and_not_task_id_based() -> None:
    dataset = load_dataset()
    task = next(
        task
        for task in dataset.tasks
        if task.benchmark_task_id == "bench_task_golden_failure_diagnosis"
    )
    independent_task = task.model_copy(update={"benchmark_task_id": "unrelated-task-id"})
    first = resolve_stage21_initial_report_reference(task)
    second = resolve_stage21_initial_report_reference(independent_task)

    assert first is not None and second is not None
    assert first.resource_key == second.resource_key == "golden-failure"
    assert first.case_id == second.case_id == "stage21-initial-report:golden-failure"

    non_initial = task.model_copy(
        update={
            "initial_state": InitialState(
                entries=tuple(
                    JavaResourceReference(
                        key="testReport",
                        ref="java://test-report/project-42/run-701/report-701",
                    )
                    if isinstance(entry, JavaResourceReference) and entry.key == "testReport"
                    else entry
                    for entry in task.initial_state.entries
                )
            )
        }
    )
    assert not is_stage21_initial_report_task(non_initial)
    assert resolve_stage21_initial_report_reference(non_initial) is None
    assert RealModelStage20WorkflowAdapter._execution_plan(non_initial).java.initial_report is False


def test_initial_report_reference_requires_known_recipe_and_trusted_project() -> None:
    dataset = load_dataset()
    task = next(
        task
        for task in dataset.tasks
        if task.benchmark_task_id == "bench_task_golden_failure_diagnosis"
    )

    def replace_reference(value: str) -> BenchmarkTask:
        return task.model_copy(
            update={
                "initial_state": InitialState(
                    entries=tuple(
                        JavaResourceReference(key=entry.key, ref=value)
                        if isinstance(entry, JavaResourceReference) and entry.key == "testReport"
                        else entry
                        for entry in task.initial_state.entries
                    )
                )
            }
        )

    with pytest.raises(
        Stage21InitialReportReferenceError, match="no approved initial TestReport recipe"
    ):
        resolve_stage21_initial_report_reference(
            replace_reference("java://test-report/project-42/stage21-initial/unknown")
        )
    with pytest.raises(
        Stage21InitialReportReferenceError, match="symbolic initial report reference"
    ):
        resolve_stage21_initial_report_reference(
            replace_reference("java://test-report/project-42/stage21-initial/not valid")
        )
    with pytest.raises(
        Stage21InitialReportReferenceError, match="does not match the trusted project"
    ):
        resolve_stage21_initial_report_reference(
            replace_reference("java://test-report/project-42/stage21-initial/golden-failure")
        )


def test_initial_report_catalog_and_expected_side_are_independent() -> None:
    recipes = load_stage21_initial_report_recipes()
    assert len(recipes) == 19
    assert all(
        "run-" not in recipe.case_id and "report-" not in recipe.case_id
        for recipe in recipes.values()
    )
    assert DEFAULT_STAGE21_INITIAL_REPORT_RECIPE_PATH.is_file()

    dataset = load_dataset()
    task = next(
        task
        for task in dataset.tasks
        if task.benchmark_task_id == "bench_task_golden_failure_diagnosis"
    )
    original = resolve_stage21_initial_report_reference(task)
    changed_expected = task.model_copy(update={"expected_output": {"reportId": "fixture:701"}})
    changed = resolve_stage21_initial_report_reference(changed_expected)
    assert original == changed


@pytest.mark.anyio
async def test_initial_report_java_identity_is_read_from_public_java_boundary() -> None:
    dataset = load_dataset()
    task = next(
        task
        for task in dataset.tasks
        if task.benchmark_task_id == "bench_task_golden_failure_diagnosis"
    )
    report_payload = {
        "projectId": 41,
        "taskId": 901,
        "runId": 9876,
        "reportId": "report:9876",
        "status": "ASSERTION_FAILED",
        "startedAt": "2026-08-29T00:00:00Z",
        "finishedAt": "2026-08-29T00:00:01Z",
        "summary": {
            "totalCases": 1,
            "totalSteps": 1,
            "totalAssertions": 1,
            "passedAssertions": 0,
            "failedAssertions": 1,
            "failureType": "BUSINESS_ERROR",
        },
        "cases": [],
    }

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/projects/41/test-runs/latest-by-case":
            assert request.url.params["caseId"] == "stage21-initial-report:golden-failure"
            return httpx.Response(
                200,
                json={
                    "success": True,
                    "code": "00000",
                    "message": "success",
                    "data": {
                            "runId": 9876,
                            "caseId": "stage21-initial-report:golden-failure",
                            "apiId": "stage21-initial-report",
                            "testCaseName": "initial",
                            "status": "ASSERTION_FAILED",
                            "failureType": "BUSINESS_ERROR",
                            "createdAt": "2026-08-29T00:00:00Z",
                            "startedAt": "2026-08-29T00:00:00Z",
                            "finishedAt": "2026-08-29T00:00:01Z",
                            "durationMs": 1,
                        },
                },
            )
        if request.url.path == "/api/v1/projects/41/test-runs/9876/report":
            return httpx.Response(
                200,
                json={
                    "success": True,
                    "code": "00000",
                    "message": "success",
                    "data": report_payload,
                },
            )
        raise AssertionError(f"unexpected Java boundary: {request.url.path}")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter = RealModelStage20WorkflowAdapter(
            RecordingLLM(),
            java_client=JavaApiOpsClient(
                client,
                base_url="https://java.example.test",
                timeout_seconds=2,
            ),
            token_provider=lambda: "java-issued-token",
        )
        report, java_owned = await adapter._report_for_task(
            task,
            project_id=41,
            trace_id="trace:initial-report",
            agent_run_id="agent:initial-report",
            recorder=TraceRecorder(),
        )

    assert isinstance(report, JavaTestReport)
    assert java_owned is True
    assert report.run_id == 9876
    assert report.report_id == "report:9876"


def test_strategy_does_not_use_instruction_keywords() -> None:
    dataset = load_dataset()
    task = next(
        task
        for task in dataset.tasks
        if task.benchmark_task_id == "bench_task_golden_testcase_happy"
    )
    altered = task.model_copy(
        update={
            "instruction": "missing required boundary auth business idempotency",
            "initial_state": InitialState(
                entries=tuple(
                    entry
                    for entry in task.initial_state.entries
                    if not (
                        entry.kind == "LITERAL" and entry.key in {"strategy", "generationStrategy"}
                    )
                )
                + (LiteralSetup(key="strategy", value="HAPPY_PATH"),)
            ),
        }
    )

    assert RealModelStage20WorkflowAdapter._strategy(altered).value == "HAPPY_PATH"


def test_task_focus_falls_back_to_trusted_instruction_without_expected_side() -> None:
    task = _task("bench_task_testcase_boundary_quantity_zero")

    assert RealModelStage20WorkflowAdapter._task_focus(task) == task.instruction

    explicit = task.model_copy(
        update={
            "initial_state": InitialState(
                entries=task.initial_state.entries
                + (LiteralSetup(key="taskFocus", value="quantity"),)
            )
        }
    )
    assert RealModelStage20WorkflowAdapter._task_focus(explicit) == "quantity"


def test_missing_structured_strategy_fails_closed() -> None:
    dataset = load_dataset()
    task = next(
        task
        for task in dataset.tasks
        if task.benchmark_task_id == "bench_task_golden_testcase_happy"
    )

    task_without_strategy = task.model_copy(
        update={
            "initial_state": InitialState(
                entries=tuple(
                    entry
                    for entry in task.initial_state.entries
                    if not (
                        entry.kind == "LITERAL" and entry.key in {"strategy", "generationStrategy"}
                    )
                )
            )
        }
    )

    with pytest.raises(BenchmarkTaskFailure) as exc_info:
        RealModelStage20WorkflowAdapter._strategy(task_without_strategy)

    assert exc_info.value.code == "TASK_STRATEGY_UNSPECIFIED"


@pytest.mark.anyio
async def test_invalid_structured_strategy_is_not_silently_substituted() -> None:
    llm, task, fixture_setup = await _setup("bench_task_testcase_auth_missing_token")
    task = task.model_copy(
        update={
            "initial_state": InitialState(
                entries=tuple(
                    entry
                    for entry in task.initial_state.entries
                    if not (
                        entry.kind == "LITERAL" and entry.key in {"strategy", "generationStrategy"}
                    )
                )
                + (
                    LiteralSetup(key="strategy", value="IDEMPOTENCY"),
                    LiteralSetup(key="projectId", value=41),
                )
            )
        }
    )
    with pytest.raises(BenchmarkTaskFailure) as exc_info:
        await RealModelStage20WorkflowAdapter(
            llm,
            repository_root=REPOSITORY_ROOT,
        ).execute(
            task,
            fixture_setup,
            trace_id="trace:invalid-strategy",
            agent_run_id="agent_run:invalid-strategy",
        )

    assert getattr(exc_info.value, "code", None) == "TASK_STRATEGY_NOT_APPLICABLE"
    assert llm.prompts == []


class InvalidJsonLLM(RecordingLLM):
    async def complete(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return "not-json"


class IdentityMismatchLLM(RecordingLLM):
    async def complete(self, prompt: str) -> str:
        payload = json.loads(await super().complete(prompt))
        payload["agentRunId"] = "agent_run:wrong"
        return json.dumps(payload)


@pytest.mark.anyio
async def test_diagnosis_parse_failure_preserves_real_model_call_observability() -> None:
    _, task, fixture_setup = await _setup("bench_task_formal_failure_transport_connect")
    task = _python_only_task(task).model_copy(
        update={"benchmark_task_id": "test_python_only_parse_failure"}
    )
    llm = InvalidJsonLLM()

    outcome = await RealModelStage20WorkflowAdapter(
        llm,
        repository_root=REPOSITORY_ROOT,
    ).execute(
        task,
        fixture_setup,
        trace_id="trace:parse-observability",
        agent_run_id="agent_run:parse-observability",
    )

    assert outcome.model_call_ids == ()
    assert llm.prompts == []
    assert any(isinstance(record, ToolPlanningRecord) for record in outcome.trace_records)


@pytest.mark.anyio
async def test_diagnosis_identity_failure_preserves_post_model_call_observability() -> None:
    _, task, fixture_setup = await _setup("bench_task_formal_failure_transport_connect")
    task = _python_only_task(task).model_copy(
        update={"benchmark_task_id": "test_python_only_identity_failure"}
    )
    llm = IdentityMismatchLLM()

    outcome = await RealModelStage20WorkflowAdapter(
        llm,
        repository_root=REPOSITORY_ROOT,
    ).execute(
        task,
        fixture_setup,
        trace_id="trace:identity-observability",
        agent_run_id="agent_run:identity-observability",
    )

    assert outcome.model_call_ids == ()
    assert llm.prompts == []
    assert any(isinstance(record, ToolPlanningRecord) for record in outcome.trace_records)


@pytest.mark.anyio
async def test_missing_candidate_does_not_create_structured_actual_result() -> None:
    _, task, fixture_setup = await _setup("bench_task_golden_testcase_happy")
    task = _python_only_task(task, strategy="HAPPY_PATH")
    llm = InvalidJsonLLM()
    outcome = await RealModelStage20WorkflowAdapter(
        llm,
        repository_root=REPOSITORY_ROOT,
    ).execute(
        task,
        fixture_setup,
        trace_id="trace:missing-candidate",
        agent_run_id="agent_run:missing-candidate",
    )

    assert outcome.facts.validity.valid_json is None
    assert outcome.facts.validity.schema_valid is None
    assert outcome.facts.validity.contract_accepted is None
    assert not any(fact.name == "candidate" for fact in outcome.facts.structured_facts)


class RejectedCandidateLLM(RecordingLLM):
    async def complete(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return json.dumps({"schemaVersion": "1.0.0"})


@pytest.mark.anyio
async def test_rejected_candidate_is_recorded_without_fabricating_validity() -> None:
    _, task, fixture_setup = await _setup("bench_task_golden_testcase_happy")
    task = _python_only_task(task, strategy="HAPPY_PATH")
    llm = RejectedCandidateLLM()
    outcome = await RealModelStage20WorkflowAdapter(
        llm,
        repository_root=REPOSITORY_ROOT,
    ).execute(
        task,
        fixture_setup,
        trace_id="trace:rejected-candidate",
        agent_run_id="agent_run:rejected-candidate",
    )

    assert outcome.facts.validity.valid_json is True
    assert outcome.facts.validity.schema_valid is False
    assert outcome.facts.validity.contract_accepted is False
    assert any(fact.name == "candidate" for fact in outcome.facts.structured_facts)


@pytest.mark.anyio
async def test_candidate_is_forwarded_to_existing_evaluation_case_actual_side() -> None:
    llm, task, fixture_setup = await _setup("bench_task_golden_testcase_happy")
    task = _python_only_task(task, strategy="HAPPY_PATH")
    captured: dict[str, object] = {}

    def evaluate(case, truth, trace_records):
        captured["facts"] = case.facts
        return RuleBasedEvaluator().evaluate(case, truth, trace_records)

    result = await BenchmarkRunner(
        RealModelStage20WorkflowAdapter(llm, repository_root=REPOSITORY_ROOT),
        evaluator=evaluate,
    ).run_task(
        task,
        next(
            truth
            for truth in load_dataset().ground_truths
            if truth.ground_truth_id == task.ground_truth_ref.ground_truth_id
            and truth.version == task.ground_truth_ref.version
        ),
        evaluation_run_id="evaluation_run:candidate-actual",
    )

    assert result.evaluation_result is not None
    facts = captured["facts"]
    assert any(fact.name == "candidate" for fact in facts.structured_facts)


@pytest.mark.anyio
async def test_fixture_report_is_not_promoted_to_java_authority_identity() -> None:
    llm, task, fixture_setup = await _setup("bench_task_golden_failure_diagnosis")
    dataset = load_dataset()
    truth = next(
        truth
        for truth in dataset.ground_truths
        if truth.ground_truth_id == task.ground_truth_ref.ground_truth_id
        and truth.version == task.ground_truth_ref.version
    )
    result = await BenchmarkRunner(
        RealModelStage20WorkflowAdapter(llm, repository_root=REPOSITORY_ROOT)
    ).run_task(
        task,
        truth,
        evaluation_run_id="evaluation_run:fixture-authority-filter",
    )

    assert result.execution_mode is BenchmarkExecutionMode.UNKNOWN
    assert result.java_execution_status is JavaExecutionStatus.REQUIRED_BUT_UNAVAILABLE
    assert result.run_id is None
    assert result.report_id is None
    assert result.model_call_ids == ()


def test_fixture_outcome_default_is_not_real_model_execution() -> None:
    outcome = BenchmarkExecutionOutcome(
        trace_id="trace:fixture",
        agent_run_id="agent_run:fixture",
        facts=EvaluationFacts(),
    )

    assert outcome.execution_mode is BenchmarkExecutionMode.UNKNOWN
