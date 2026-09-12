"""Acceptance-side RAG relevance tests."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType


def _acceptance_module() -> ModuleType:
    path = Path(__file__).resolve().parents[2] / "scripts" / "stage21_rag_v2_acceptance.py"
    spec = importlib.util.spec_from_file_location("stage21_rag_v2_acceptance", path)
    if spec is None or spec.loader is None:
        raise AssertionError(f"could not load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _row(
    task_id: str,
    source_scores: list[tuple[str, float]],
) -> dict[str, object]:
    citations = [
        {
            "sourceId": source,
            "projectId": 41,
            "documentId": f"doc-{index}",
            "chunkId": f"chunk-{index}",
        }
        for index, (source, _) in enumerate(source_scores)
    ]
    return {
        "taskId": task_id,
        "profile": "NORMAL",
        "currentProjectId": 41,
        "targetProjectId": None,
        "query": "test query",
        "topK": 3,
        "toolName": "rag.search",
        "httpStatus": 200,
        "toolCallId": "tool-call",
        "ragQueryId": "rag-query",
        "gatewayStatus": "SUCCESS",
        "resultCount": len(source_scores),
        "scores": [score for _, score in source_scores],
        "sourceIds": [source for source, _ in source_scores],
        "citations": citations,
        "raw": {},
    }


def test_zero_hit_uses_empty_accepted_evidence_not_empty_raw_results() -> None:
    module = _acceptance_module()
    row = _row(
        "bench_task_rag_zero_hit",
        [(module.SOURCE_KEYS["payment"], 0.99)],
    )

    result = module.acceptance_report([row], 0.5)

    assert result["statusCounts"] == {"ZERO_HIT": 1}
    recipe = result["recipes"][0]
    assert recipe["rawResultCount"] == 1
    assert recipe["scoreQualifiedSourceIds"] == [module.SOURCE_KEYS["payment"]]
    assert recipe["acceptedResultCount"] == 0
    assert recipe["acceptedRelevantEvidence"] == []


def test_high_score_distractor_is_not_accepted_without_relevant_identity() -> None:
    module = _acceptance_module()
    row = _row(
        "bench_task_formal_rag_distractor_filter",
        [
            (module.SOURCE_KEYS["catalog"], 0.99),
            (module.SOURCE_KEYS["index"], 0.52),
        ],
    )

    result = module.acceptance_report([row], 0.5)

    recipe = result["recipes"][0]
    assert recipe["acceptanceStatus"] == "SUCCESS_WITH_RESULTS"
    assert recipe["acceptedSourceIds"] == [module.SOURCE_KEYS["index"]]
    assert module.SOURCE_KEYS["catalog"] not in recipe["acceptedSourceIds"]


def test_required_positive_below_policy_is_not_promoted_to_evidence() -> None:
    module = _acceptance_module()
    row = _row(
        "bench_task_formal_rag_single_constraint",
        [(module.SOURCE_KEYS["orders"], 0.49)],
    )

    result = module.acceptance_report([row], 0.5)

    assert result["statusCounts"] == {"FAILED": 1}
    assert result["recipes"][0]["acceptedResultCount"] == 0
