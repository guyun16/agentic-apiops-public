"""Isolated Stage 16 real-provider and real-metadata verification commands."""

from __future__ import annotations

import argparse
import asyncio
import json
from typing import Any

import httpx
from pydantic import ValidationError

from app.agents.testcase_generator import TestCaseGenerator
from app.clients.java_apiops import JavaApiOpsClient
from app.clients.llm_provider import build_llm
from app.core.settings import AppSettings
from app.schemas.openapi_metadata import OpenApiMetadataDetail
from app.schemas.testcase_dsl import TestCaseDSL
from app.workflows.candidate_validation import validate_candidate
from app.workflows.generation_context import TestStrategy, build_generation_context
from app.workflows.state import APIOpsAgentState, WorkflowPhase
from app.workflows.testcase_generation_graph import build_testcase_generation_graph


def _secret(settings: AppSettings, name: str) -> str:
    value = getattr(settings, name)
    if value is None or not value.get_secret_value().strip():
        raise RuntimeError(f"missing environment variable: {name.upper()}")
    return value.get_secret_value()


def _emit(evidence: dict[str, Any]) -> None:
    print(json.dumps(evidence, ensure_ascii=False, sort_keys=True))


def _provider(
    http_client: httpx.AsyncClient,
    settings: AppSettings,
    provider: str,
) -> object:
    return build_llm(
        http_client,
        settings,
        provider=provider,
    )


def _java(http_client: httpx.AsyncClient, settings: AppSettings) -> JavaApiOpsClient:
    return JavaApiOpsClient(
        http_client,
        base_url=settings.java_apiops_base_url,
        timeout_seconds=settings.java_apiops_timeout_seconds,
    )


async def smoke(settings: AppSettings, provider: str = "deepseek") -> bool:
    async with httpx.AsyncClient(trust_env=False) as http_client:
        client = _provider(http_client, settings, provider)
        response = await client.complete(
            'Return exactly one non-empty JSON object: {"status":"ok"}.'
        )
    passed = bool(response.strip())
    _emit(
        {
            "provider": client.provider,
            "model": client.model,
            "non_empty_response": passed,
            "result": "PASS" if passed else "FAIL",
        }
    )
    return passed


async def metadata(
    settings: AppSettings,
    *,
    project_id: int,
    api_id: str,
) -> OpenApiMetadataDetail:
    async with httpx.AsyncClient(trust_env=False) as http_client:
        value = await _java(http_client, settings).get_api_metadata(
            project_id=project_id,
            api_id=api_id,
            token=_secret(settings, "java_apiops_token"),
            trace_id="stage16-real-e2e",
        )
    _emit(
        {
            "apiId": value.api_id,
            "method": value.method,
            "operationId": value.operation_id,
            "path": value.path,
            "projectId": project_id,
            "result": "PASS" if value.api_id == api_id else "FAIL",
            "typed_metadata": isinstance(value, OpenApiMetadataDetail),
        }
    )
    return value


def _state(
    *,
    project_id: int,
    api_id: str,
    intent: TestStrategy,
    value: OpenApiMetadataDetail,
) -> APIOpsAgentState:
    return {
        "trace_id": "stage16-real-e2e",
        "phase": WorkflowPhase.INITIAL,
        "route": None,
        "error": None,
        "attempt_count": 0,
        "max_attempts": 0,
        "project_id": project_id,
        "api_id": api_id,
        "generation_intent": intent.value,
        "api_metadata": value,
        "generation_context": build_generation_context(value, intent),
        "candidate": None,
        "validation_result": None,
        "repair_attempts": 0,
        "max_repair_attempts": 1,
        "generation_status": None,
    }


async def e2e(
    settings: AppSettings,
    *,
    project_id: int,
    api_id: str,
    intent: TestStrategy,
    provider: str = "deepseek",
) -> bool:
    async with httpx.AsyncClient(trust_env=False) as http_client:
        java = _java(http_client, settings)
        value = await java.get_api_metadata(
            project_id=project_id,
            api_id=api_id,
            token=_secret(settings, "java_apiops_token"),
            trace_id="stage16-real-e2e",
        )
        if value.api_id != api_id:
            raise RuntimeError("Java metadata apiId does not match the request")
        state = _state(
            project_id=project_id,
            api_id=api_id,
            intent=intent,
            value=value,
        )
        llm = _provider(http_client, settings, provider)
        graph = build_testcase_generation_graph(TestCaseGenerator(llm))
        result = await graph.ainvoke(state)

    context = state["generation_context"]
    candidate = result["candidate"]
    revalidation = None
    typed_parse = False
    if candidate is not None and context is not None:
        revalidation = validate_candidate(
            candidate,
            project_id=project_id,
            generation_context=context,
        )
        try:
            TestCaseDSL.model_validate(candidate.structured)
        except ValidationError:
            pass
        else:
            typed_parse = True

    issues = () if revalidation is None else revalidation.issues
    shared_schema_valid = revalidation is not None and not any(
        issue.layer == "SCHEMA" for issue in issues
    )
    semantic_valid = typed_parse and not any(issue.layer == "SEMANTIC" for issue in issues)
    final_exists = bool(
        candidate is not None
        and revalidation is not None
        and revalidation.valid
        and result["route"].value == "READY"
    )
    evidence = {
        "apiId": api_id,
        "final_route": None if result["route"] is None else result["route"].value,
        "final_testcase_exists": final_exists,
        "generation_intent": intent.value,
        "generation_status": (
            None if result["generation_status"] is None else result["generation_status"].value
        ),
        "initial_generation_occurred": True,
        "method": value.method,
        "model": llm.model,
        "operationId": value.operation_id,
        "path": value.path,
        "projectId": project_id,
        "provider": llm.provider,
        "repair_count": result["repair_attempts"],
        "selected_strategy": context.strategy.value if context is not None else None,
        "semantic_validation_result": semantic_valid,
        "shared_schema_validation_result": shared_schema_valid,
        "traceability_result": bool(
            typed_parse
            and candidate.structured.get("projectId") == project_id
            and candidate.structured.get("apiId") == api_id
        ),
        "typed_metadata_result": isinstance(value, OpenApiMetadataDetail),
        "typed_parse_result": typed_parse,
        "validation_issues": [
            {"code": issue.code, "layer": issue.layer, "path": issue.path} for issue in issues
        ],
    }
    _emit(evidence)
    return final_exists


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description=__doc__)
    subcommands = value.add_subparsers(dest="command", required=True)
    smoke_command = subcommands.add_parser("smoke")
    smoke_command.add_argument("--provider", choices=("deepseek", "qwen"), default="deepseek")
    for name in ("metadata", "e2e"):
        command = subcommands.add_parser(name)
        command.add_argument("--project-id", type=int, required=True)
        command.add_argument("--api-id", required=True)
        if name == "e2e":
            command.add_argument(
                "--provider",
                choices=("deepseek", "qwen"),
                default="deepseek",
            )
            command.add_argument(
                "--intent",
                choices=[strategy.value for strategy in TestStrategy],
                default=TestStrategy.HAPPY_PATH.value,
            )
    return value


async def _main() -> bool:
    args = parser().parse_args()
    settings = AppSettings()
    if args.command == "smoke":
        return await smoke(settings, provider=args.provider)
    if args.command == "metadata":
        value = await metadata(
            settings,
            project_id=args.project_id,
            api_id=args.api_id,
        )
        return value.api_id == args.api_id
    return await e2e(
        settings,
        project_id=args.project_id,
        api_id=args.api_id,
        intent=TestStrategy(args.intent),
        provider=args.provider,
    )


def main() -> None:
    try:
        passed = asyncio.run(_main())
    except Exception as exc:
        _emit({"error_type": type(exc).__name__, "result": "FAIL"})
        raise SystemExit(1) from None
    raise SystemExit(0 if passed else 1)


if __name__ == "__main__":
    main()
