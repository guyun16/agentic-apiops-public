"""Deterministic TestCase runtime provider and identity regression tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import SecretStr

from app.clients.java_apiops import JavaApiOpsClient
from app.clients.llm import StructuredOutputSpec
from app.clients.qwen_structured_output import TESTCASE_CANDIDATE_SCHEMA_NAME
from app.core.settings import AppSettings
from app.schemas.openapi_metadata import OpenApiMetadataDetail
from app.schemas.testcase_generation_api import TestCaseGenerationRequest as GenerationRequest
from app.services.runtime_evaluation import runtime_evaluation_store
from app.services.testcase_generation import TestCaseGenerationService
from app.workflows.generation_context import TestStrategy

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]


class _FakeProviderLLM:
    def __init__(self, provider: str, model: str) -> None:
        self.provider = provider
        self.model = model

    async def complete(self, prompt: str) -> str:
        assert "TESTCASE DSL CONTRACT AUTHORITY" in prompt
        return json.dumps(
            {
                "schemaVersion": "1.0.0",
                "caseId": "case-provider-wiring",
                "projectId": 41,
                "apiId": "api-1",
                "name": "List orders",
                "environment": {"baseUrl": "https://api.example", "variables": {}},
                "steps": [
                    {
                        "stepId": "step-1",
                        "name": "List orders",
                        "request": {"method": "GET", "path": "/orders"},
                        "assertions": [{"type": "STATUS_CODE", "expected": 200}],
                        "extractors": [],
                    }
                ],
            }
        )


class _FakeQwenProviderLLM(_FakeProviderLLM):
    async def complete_structured(
        self,
        prompt: str,
        *,
        output_spec: StructuredOutputSpec,
    ) -> str:
        assert output_spec.schema_name == TESTCASE_CANDIDATE_SCHEMA_NAME
        assert output_spec.schema == {"type": "object", "additionalProperties": True}
        return await self.complete(prompt)


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("configured_provider", "expected_provider", "expected_model"),
    [
        ("deepseek", "DeepSeek", "deepseek-test-model"),
        ("qwen", "Qwen", "qwen-test-model"),
    ],
)
async def test_testcase_service_uses_selected_client_and_runtime_identity(
    monkeypatch: pytest.MonkeyPatch,
    configured_provider: str,
    expected_provider: str,
    expected_model: str,
) -> None:
    metadata = OpenApiMetadataDetail.model_validate_json(
        (REPOSITORY_ROOT / "examples" / "openapi-metadata-valid.json").read_text(encoding="utf-8")
    )
    selected: list[str] = []

    async def fake_metadata(
        self: JavaApiOpsClient,
        *,
        project_id: int,
        api_id: str,
        token: str,
        trace_id: str,
    ) -> OpenApiMetadataDetail:
        del self, token, trace_id
        assert (project_id, api_id) == (41, "api-1")
        return metadata

    def fake_builder(
        http_client: object,
        settings: AppSettings,
        *,
        provider: str,
    ) -> _FakeProviderLLM:
        del http_client, settings
        selected.append(provider)
        client_type = _FakeQwenProviderLLM if expected_provider == "Qwen" else _FakeProviderLLM
        return client_type(expected_provider, expected_model)

    monkeypatch.setattr(JavaApiOpsClient, "get_api_metadata", fake_metadata)
    monkeypatch.setattr("app.services.testcase_generation.build_llm", fake_builder)
    runtime_evaluation_store.clear()
    try:
        response = await TestCaseGenerationService().generate(
            project_id=41,
            api_id="api-1",
            request=GenerationRequest(strategy=TestStrategy.HAPPY_PATH),
            token="java-token",
            trace_id=f"trace:testcase-provider-{configured_provider}",
            settings=AppSettings(
                testcase_llm_provider=configured_provider,  # type: ignore[arg-type]
                deepseek_api_key=SecretStr("test-deepseek-key"),
                deepseek_model="deepseek-test-model",
                qwen_api_key=SecretStr("test-qwen-key"),
                qwen_model="qwen-test-model",
                trace_sink="memory",
            ),
        )

        assert selected == [configured_provider]
        assert response.candidate["projectId"] == 41
        detail = runtime_evaluation_store.get_detail(response.agent_run_id)
        assert detail is not None
        assert detail.provider == expected_provider
        assert detail.model == expected_model
        assert detail.status == "COMPLETED"
    finally:
        runtime_evaluation_store.clear()
