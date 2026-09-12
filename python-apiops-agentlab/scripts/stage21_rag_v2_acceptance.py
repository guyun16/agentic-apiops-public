"""Run the Stage 21 RAG V2 probes through the Java Tool Gateway.

This script deliberately has no database, Redis, RabbitMQ, or Qdrant client.  It
only logs in through the Java HTTP API and invokes the public ``rag.search``
Tool Gateway contract.  The two output modes are:

* ``calibration``: collect raw scores and derive a documented threshold from
  the observed positive/non-positive separation.
* ``acceptance``: rerun the same recipes and qualify raw candidates in the
  evaluation-only acceptance layer using the calibrated relevance policy.

The Java response remains the raw retrieval authority.  ``resultCount`` and
the score/source arrays record the complete candidate set; acceptance derives
``acceptedRelevantEvidence`` separately and never changes the runtime query,
tool route, or project authorization behavior.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
RECIPE_PATH = (
    REPOSITORY_ROOT
    / "python-apiops-agentlab/tests/benchmark/fixtures/support/"
    / "stage21-remaining-rag-recipes.json"
)
PREREQUISITE_PATH = (
    REPOSITORY_ROOT
    / "python-apiops-agentlab/tests/benchmark/fixtures/"
    / "stage21-execution-prerequisites.json"
)
MANIFEST_PATH = (
    REPOSITORY_ROOT
    / "java-apiops-platform/apiops-web/src/test/resources/stage21/"
    / "rag-corpus-v2/corpus-manifest.json"
)
SETUP_REPORT_PATH = (
    REPOSITORY_ROOT / "artifacts/stage21/rag-v2-corpus-setup/setup-report.json"
)
PROFILE_ENV = {
    "NORMAL": ("stage21-normal", "STAGE21_NORMAL_PASSWORD"),
    "SAFETY_41_ISOLATED": ("stage21-safety41", "STAGE21_SAFETY41_PASSWORD"),
    "SAFETY_42_ISOLATED": ("stage21-safety42", "STAGE21_SAFETY42_PASSWORD"),
}

SOURCE_KEYS = {
    "orders": "stage21-rag-v2/project-41/orders-api-constraints",
    "incident": "stage21-rag-v2/project-41/orders-incident-report",
    "index": "stage21-rag-v2/project-41/orders-constraint-index",
    "catalog": "stage21-rag-v2/project-41/catalog-distractor",
    "payment": "stage21-rag-v2/project-41/payment-near-match",
    "api": "stage21-rag-v2/project-41/api-contract-and-testcase-runbook",
    "runner": "stage21-rag-v2/project-41/runner-reliability-runbook",
    "data": "stage21-rag-v2/project-41/data-integrity-constraints",
    "inventory": "stage21-rag-v2/project-42/inventory-service-runbook",
    "payments": "stage21-rag-v2/project-42/payments-incident-report",
    "protected": "stage21-rag-v2/project-42/protected-service-notes",
    "gateway": "stage21-rag-v2/project-42/tool-gateway-and-rag-operations",
    "security": "stage21-rag-v2/project-42/inventory-security-and-evidence-runbook",
}

REQUIRED_KNOWLEDGE_TYPES = {
    "OPENAPI_ENDPOINT_CONSTRAINTS",
    "REQUEST_RESPONSE_CONSTRAINTS",
    "TESTCASE_DSL_SEMANTICS",
    "ASSERTION_MISMATCH",
    "HTTP_STATUS_MISMATCH",
    "DATABASE_UNIQUE_CONSTRAINT",
    "FOREIGN_KEY_DATA_CONSTRAINT",
    "TIMEOUT_RETRY_SEMANTICS",
    "RUNNER_LIFECYCLE",
    "FAILURE_TAXONOMY",
    "AUTHORIZATION_PROJECT_ISOLATION",
    "TOOL_GATEWAY_RULES",
    "RAG_USAGE",
    "ZERO_HIT_SEMANTICS",
    "CITATION_RULES",
    "REPORT_INDEX_CORRELATION",
    "MULTI_EVIDENCE_DIAGNOSIS",
    "NEAR_MATCH_INCIDENTS",
    "SIMILAR_WRONG_DISTRACTORS",
}

EXPECTED_SOURCES = {
    "bench_task_formal_rag_citation_report": [SOURCE_KEYS["incident"]],
    "bench_task_formal_rag_distractor_filter": [SOURCE_KEYS["index"]],
    "bench_task_formal_rag_multi_constraint_summary": [
        SOURCE_KEYS["orders"],
        SOURCE_KEYS["index"],
    ],
    "bench_task_formal_rag_multi_report_index": [
        SOURCE_KEYS["incident"],
        SOURCE_KEYS["index"],
    ],
    "bench_task_formal_rag_near_match_exact": [
        SOURCE_KEYS["orders"],
        SOURCE_KEYS["index"],
    ],
    "bench_task_formal_rag_single_constraint": [SOURCE_KEYS["orders"]],
    "bench_task_rag_near_match": [SOURCE_KEYS["index"]],
}

ZERO_TASKS = {
    "bench_task_formal_rag_zero_hit_authorized",
    "bench_task_rag_zero_hit",
}
FORBIDDEN_TASKS = {
    "bench_task_formal_rag_wrong_project_isolation",
    "bench_task_rag_wrong_project",
}


@dataclass(frozen=True)
class Recipe:
    task_id: str
    query: str
    top_k: int
    profile: str
    current_project_id: int
    target_project_id: int | None


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise RuntimeError(f"cannot read JSON fixture {path}: {error}") from error
    if not isinstance(value, dict):
        raise RuntimeError(f"JSON fixture must be an object: {path}")
    return value


def load_recipes() -> list[Recipe]:
    catalog = read_json(RECIPE_PATH)
    prerequisite = read_json(PREREQUISITE_PATH)
    catalog_rows = {
        str(row["benchmarkTaskId"]): row
        for row in catalog.get("recipes", [])
        if isinstance(row, dict)
    }
    rows: list[Recipe] = []
    for row in prerequisite.get("tasks", []):
        if not isinstance(row, dict):
            continue
        operations = set(row.get("requiredOperations", []))
        if (
            row.get("resourceSetupType") != "RUNTIME_RECIPE"
            or "RAG_SEARCH" not in operations
            or "RUNNER_SUBMIT" in operations
        ):
            continue
        task_id = str(row["benchmarkTaskId"])
        recipe = catalog_rows.get(task_id)
        if recipe is None:
            raise RuntimeError(f"missing RAG recipe for prerequisite {task_id}")
        target = row.get("targetProjectId")
        rows.append(
            Recipe(
                task_id=task_id,
                query=str(recipe["query"]),
                top_k=int(recipe["topK"]),
                profile=str(row["authProfile"]),
                current_project_id=int(row["currentProjectId"]),
                target_project_id=None if target is None else int(target),
            )
        )
    if len(rows) != 11:
        raise RuntimeError(f"expected 11 RAG recipes, found {len(rows)}")
    if {row.task_id for row in rows} != set(catalog_rows):
        raise RuntimeError("recipe catalog and prerequisite recipe set are not aligned")
    return rows


def require_password(profile: str) -> str:
    try:
        _, variable = PROFILE_ENV[profile]
    except KeyError as error:
        raise RuntimeError(f"unsupported Stage 21 profile: {profile}") from error
    value = os.environ.get(variable)
    if not value:
        raise RuntimeError(f"{variable} must be set for {profile}")
    return value


def login(client: httpx.Client, base_url: str, profile: str) -> str:
    username, _ = PROFILE_ENV[profile]
    response = client.post(
        f"{base_url}/api/v1/auth/login",
        json={"username": username, "password": require_password(profile)},
    )
    body = response.json()
    token = body.get("data", {}).get("accessToken")
    if response.status_code != 200 or not body.get("success") or not token:
        raise RuntimeError(f"Java login failed for {profile}: HTTP {response.status_code}")
    return str(token)


def invoke(
    client: httpx.Client,
    base_url: str,
    recipe: Recipe,
    token: str,
    mode: str,
) -> dict[str, Any]:
    params: dict[str, Any] = {"query": recipe.query, "topK": recipe.top_k}
    if recipe.target_project_id is not None:
        params["targetProjectId"] = recipe.target_project_id
    trace_id = f"stage21-rag-v2-{mode}-{recipe.task_id}"
    request = {
        "schemaVersion": "0.2.0",
        "agentRunId": f"stage21-rag-v2-{mode}-{recipe.task_id}",
        "projectId": str(recipe.current_project_id),
        "toolName": "rag.search",
        "params": params,
        "traceId": trace_id,
    }
    response = client.post(
        f"{base_url}/api/v1/projects/{recipe.current_project_id}/tool-calls",
        headers={"Authorization": f"Bearer {token}", "X-Trace-Id": trace_id},
        json=request,
    )
    try:
        body = response.json()
    except ValueError:
        body = {"status": "FAILED", "error": "non-json Java response"}
    if not isinstance(body, dict):
        body = {"status": "FAILED", "error": "malformed Java response"}
    data = body.get("data")
    result_rows = data.get("results", []) if isinstance(data, dict) else []
    if not isinstance(result_rows, list):
        result_rows = []
    # ResultLimiter may append a string marker or a partial map after the last
    # complete row. Those values are transport metadata, not evidence rows.
    result_rows = [
        row
        for row in result_rows
        if isinstance(row, dict)
        and isinstance(row.get("citation"), dict)
        and not row["citation"].get("_resultTruncated", False)
        and isinstance(row.get("relevanceScore"), (int, float))
    ]
    sources: list[str] = []
    scores: list[float] = []
    citations: list[dict[str, Any]] = []
    for row in result_rows:
        citation = row.get("citation")
        if isinstance(citation, dict):
            citations.append(citation)
            source = citation.get("sourceId")
            if isinstance(source, str):
                sources.append(source)
        score = row.get("relevanceScore")
        if isinstance(score, (int, float)):
            scores.append(float(score))
    response_status = str(body.get("status", "FAILED"))
    if response.status_code != 200:
        response_status = "FAILED"
    return {
        "taskId": recipe.task_id,
        "profile": recipe.profile,
        "currentProjectId": recipe.current_project_id,
        "targetProjectId": recipe.target_project_id,
        "query": recipe.query,
        "topK": recipe.top_k,
        "toolName": "rag.search",
        "httpStatus": response.status_code,
        "toolCallId": body.get("toolCallId"),
        "ragQueryId": data.get("ragQueryId") if isinstance(data, dict) else None,
        "gatewayStatus": response_status,
        "resultCount": len(result_rows),
        "scores": scores,
        "sourceIds": sources,
        "citations": citations,
        "raw": body,
    }


def run_probes(base_url: str, mode: str, timeout: float) -> list[dict[str, Any]]:
    recipes = load_recipes()
    profiles = {recipe.profile for recipe in recipes}
    base_url = base_url.rstrip("/")
    with httpx.Client(timeout=timeout, trust_env=False) as client:
        tokens = {profile: login(client, base_url, profile) for profile in profiles}
        return [
            invoke(client, base_url, recipe, tokens[recipe.profile], mode)
            for recipe in recipes
        ]


def finite_scores(rows: list[dict[str, Any]]) -> list[float]:
    return [score for row in rows for score in row["scores"] if 0.0 <= score <= 1.0]


def score_summary(scores: list[float]) -> dict[str, Any]:
    if not scores:
        return {"count": 0, "min": None, "max": None, "mean": None}
    return {
        "count": len(scores),
        "min": min(scores),
        "max": max(scores),
        "mean": sum(scores) / len(scores),
    }


def non_positive_scores(rows: list[dict[str, Any]]) -> dict[str, list[float]]:
    zero = [row for row in rows if row["taskId"] in ZERO_TASKS]
    zero_scores = finite_scores(zero)
    distractor_scores: list[float] = []
    near_match_scores: list[float] = []
    out_of_corpus_scores: list[float] = []
    known_sources = set(SOURCE_KEYS.values())
    for row in rows:
        if row["taskId"] in ZERO_TASKS or row["taskId"] in FORBIDDEN_TASKS:
            continue
        for source, score in zip(row["sourceIds"], row["scores"]):
            if source == SOURCE_KEYS["catalog"]:
                distractor_scores.append(score)
            if source == SOURCE_KEYS["payment"]:
                near_match_scores.append(score)
            if source not in known_sources:
                out_of_corpus_scores.append(score)
    return {
        "zeroHitQuery": zero_scores,
        "distractor": distractor_scores,
        "nearMatch": near_match_scores,
        "outOfCorpus": out_of_corpus_scores,
    }


def positive_scores(rows: list[dict[str, Any]]) -> list[float]:
    values: list[float] = []
    for row in rows:
        expected = EXPECTED_SOURCES.get(row["taskId"])
        if not expected:
            continue
        for source, score in zip(row["sourceIds"], row["scores"]):
            if source in expected:
                values.append(score)
    return values


def positive_scenario_scores(
    rows: list[dict[str, Any]],
) -> tuple[list[float], list[str]]:
    """Return the best expected citation score for each positive scenario."""
    values: list[float] = []
    misses: list[str] = []
    for row in rows:
        expected = EXPECTED_SOURCES.get(row["taskId"])
        if not expected:
            continue
        matches = [
            score
            for source, score in zip(row["sourceIds"], row["scores"])
            if source in expected
        ]
        if matches:
            values.append(max(matches))
        else:
            misses.append(row["taskId"])
    return values, misses


def accepted_relevant_evidence(
    row: dict[str, Any], threshold: float,
) -> list[dict[str, Any]]:
    """Return evaluation-side relevant evidence without changing raw results.

    The expected source contract is used only by this deterministic acceptance
    report.  It is not loaded by the agent, prompt, query builder, or Tool
    Planning path.  A score alone is insufficient: a distractor remains
    unaccepted when its identity is outside the scenario's relevant set.
    """
    expected = set(EXPECTED_SOURCES.get(row["taskId"], []))
    if row["gatewayStatus"] != "SUCCESS" or not expected:
        return []
    accepted: list[dict[str, Any]] = []
    for source, score, citation in zip(
        row["sourceIds"], row["scores"], row["citations"], strict=False
    ):
        if score < threshold or source not in expected:
            continue
        if (
            citation.get("sourceId") != source
            or citation.get("projectId") != row["currentProjectId"]
        ):
            continue
        accepted.append(
            {
                "sourceId": source,
                "score": score,
                "documentId": citation.get("documentId"),
                "chunkId": citation.get("chunkId"),
            }
        )
    return accepted


def score_qualified_source_ids(row: dict[str, Any], threshold: float) -> list[str]:
    """Return raw candidate identities that meet the score policy."""
    return [
        source
        for source, score in zip(
            row["sourceIds"], row["scores"], strict=False
        )
        if score >= threshold
    ]


def qualified_rank(row: dict[str, Any], expected: set[str], threshold: float) -> int | None:
    """Return the raw-result rank of the first score-qualified relevant row."""
    for index, (source, score) in enumerate(
        zip(row["sourceIds"], row["scores"], strict=False), start=1
    ):
        if score >= threshold and source in expected:
            return index
    return None


def threshold_from_distribution(
    rows: list[dict[str, Any]],
) -> tuple[float | None, dict[str, Any]]:
    positive_expected = positive_scores(rows)
    positive, positive_misses = positive_scenario_scores(rows)
    negatives = non_positive_scores(rows)
    # Every non-positive class is eligible for the boundary. A near-match or
    # distractor is not relevant merely because its score is high; the
    # acceptance layer also checks the scenario's relevant identity.
    negative_values = [
        score
        for name, values in negatives.items()
        for score in values
    ]
    min_positive = min(positive) if positive else None
    max_negative = max(negative_values) if negative_values else None
    separated = (
        min_positive is not None
        and max_negative is not None
        and not positive_misses
        and min_positive > max_negative
    )
    threshold = None
    if separated:
        threshold = round((min_positive + max_negative) / 2.0, 6)
        if not max_negative < threshold <= min_positive:
            threshold = None
            separated = False
    evidence = {
        "positiveExpectedScores": score_summary(positive_expected),
        "positiveScenarioMaxScores": score_summary(positive),
        "positiveScenarioMisses": positive_misses,
        "nonPositiveScores": {
            name: score_summary(values) for name, values in negatives.items()
        },
        "minPositiveScenarioScore": min_positive,
        "maxNonPositiveScore": max_negative,
        "thresholdNegativeClasses": [
            "zeroHitQuery", "distractor", "nearMatch", "outOfCorpus"
        ],
        "strictSeparation": separated,
        "threshold": threshold,
        "decision": "SET_STAGE21_THRESHOLD" if separated else "STOP_SEPARATION_GAP",
    }
    return threshold, evidence


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content.rstrip() + "\n", encoding="utf-8")


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def calibration_report(
    rows: list[dict[str, Any]], output_dir: Path,
) -> tuple[float | None, dict[str, Any]]:
    threshold, decision = threshold_from_distribution(rows)
    by_recipe = {
        row["taskId"]: {
            "category": category(row["taskId"]),
            "query": row["query"],
            "gatewayStatus": row["gatewayStatus"],
            "resultCount": row["resultCount"],
            "sourceIds": row["sourceIds"],
            "scores": row["scores"],
        }
        for row in rows
    }
    distribution = {
        "generatedAt": datetime.now(UTC).isoformat(),
        "mode": "calibration",
        "recipeCount": len(rows),
        "byRecipe": by_recipe,
        "positiveExpectedScores": score_summary(positive_scores(rows)),
        "positiveScenarioMaxScores": score_summary(positive_scenario_scores(rows)[0]),
        "nonPositiveScores": {
            name: score_summary(values)
            for name, values in non_positive_scores(rows).items()
        },
        "thresholdDecision": decision,
    }
    write_json(output_dir / "score-distribution.json", distribution)
    markdown = [
        "# Stage21 RAG V2 threshold decision",
        "",
        (
            "Raw scores were collected through the Java public Tool Gateway "
            "with the default-compatible retrieval setting."
        ),
        (
            "The decision uses expected V2 source citations from the recipe "
            "evaluation matrix; it does not call a model or access Qdrant "
            "directly."
        ),
        "",
        f"- Recipes: {len(rows)}",
        f"- Minimum per-scenario best expected score: {decision['minPositiveScenarioScore']}",
        f"- Maximum non-positive score: {decision['maxNonPositiveScore']}",
        f"- Positive scenarios without expected evidence: {decision['positiveScenarioMisses']}",
        f"- Strict separation: {decision['strictSeparation']}",
        f"- Decision: `{decision['decision']}`",
        f"- Proposed threshold: `{decision['threshold']}`",
        "",
        (
            "The threshold is the midpoint between the observed maximum "
            "non-positive score and the minimum per-scenario best expected "
            "score. It is applied inclusively by the acceptance-side relevance "
            "policy; Java raw candidates remain observable. All expected "
            "citation scores remain in score-distribution.json; the threshold "
            "uses the best expected citation per scenario because one "
            "retrievable evidence result keeps the scenario actionable."
        ),
    ]
    if not decision["strictSeparation"]:
        markdown.extend(
            [
                "",
                (
                    "STOP: RAG_EMBEDDING_OR_RETRIEVAL_SEPARATION_GAP. Do not "
                    "set a Stage21 threshold until corpus or retrieval "
                    "evidence establishes a stable separation."
                ),
            ]
        )
    write_text(output_dir / "threshold-decision.md", "\n".join(markdown))
    return threshold, distribution


def category(task_id: str) -> str:
    if task_id in FORBIDDEN_TASKS:
        return "CROSS_PROJECT_ISOLATION"
    if task_id in ZERO_TASKS:
        return "AUTHORIZED_ZERO_HIT"
    if "citation" in task_id:
        return "CITATION"
    if "distractor" in task_id:
        return "RELEVANT_OVER_DISTRACTOR"
    if "multi_constraint" in task_id:
        return "MULTI_CONSTRAINT"
    if "multi_report" in task_id:
        return "MULTI_REPORT_INDEX"
    if "near_match" in task_id:
        return "EXACT_OVER_NEAR_MATCH"
    if "single_constraint" in task_id:
        return "SINGLE_EXACT"
    return "AUTHORIZED_EVIDENCE"


def validate_citations(row: dict[str, Any]) -> tuple[int, int, list[str]]:
    mismatches = 0
    isolation_violations = 0
    unexpected_sources: list[str] = []
    known_sources = set(SOURCE_KEYS.values())
    for citation in row["citations"]:
        if citation.get("sourceId") not in known_sources:
            unexpected_sources.append(str(citation.get("sourceId")))
        if (
            citation.get("projectId") != row["currentProjectId"]
            or citation.get("documentId") is None
            or citation.get("chunkId") is None
            or citation.get("sourceId") is None
        ):
            mismatches += 1
        if citation.get("projectId") != row["currentProjectId"]:
            isolation_violations += 1
    if row["targetProjectId"] is None:
        for citation in row["citations"]:
            if citation.get("projectId") != row["currentProjectId"]:
                isolation_violations += 1
    return mismatches, isolation_violations, unexpected_sources


def reciprocal_rank(sources: list[str], expected: list[str]) -> float:
    for index, source in enumerate(sources, start=1):
        if source in expected:
            return 1.0 / index
    return 0.0


def acceptance_report(rows: list[dict[str, Any]], threshold: float | None) -> dict[str, Any]:
    if threshold is None or not 0.0 <= threshold <= 1.0:
        raise RuntimeError(
            "acceptance threshold must be finite and between 0.0 and 1.0"
        )
    status_counts: Counter[str] = Counter()
    citation_mismatches = 0
    isolation_violations = 0
    unexpected_sources: list[str] = []
    positive_rows: list[dict[str, Any]] = []
    normalized_rows: list[dict[str, Any]] = []
    for row in rows:
        accepted = accepted_relevant_evidence(row, threshold)
        accepted_sources = [item["sourceId"] for item in accepted]
        qualified_sources = score_qualified_source_ids(row, threshold)
        mismatch, isolation, unexpected = validate_citations(row)
        citation_mismatches += mismatch
        isolation_violations += isolation
        unexpected_sources.extend(unexpected)
        if row["taskId"] in FORBIDDEN_TASKS:
            status = "FORBIDDEN" if row["gatewayStatus"] == "FORBIDDEN" else "FAILED"
        elif row["taskId"] in ZERO_TASKS:
            status = (
                "ZERO_HIT"
                if row["gatewayStatus"] == "SUCCESS" and not accepted
                else "FAILED"
            )
        else:
            status = (
                "SUCCESS_WITH_RESULTS"
                if row["gatewayStatus"] == "SUCCESS" and accepted
                else "FAILED"
            )
            positive_rows.append(row)
        status_counts[status] += 1
        normalized_rows.append(
            {
                key: row[key]
                for key in (
                    "taskId",
                    "profile",
                    "currentProjectId",
                    "targetProjectId",
                    "query",
                    "topK",
                    "toolCallId",
                    "ragQueryId",
                    "gatewayStatus",
                    "resultCount",
                    "scores",
                    "sourceIds",
                )
            }
            | {
                "category": category(row["taskId"]),
                "acceptanceStatus": status,
                "rawResultCount": row["resultCount"],
                "rawScores": row["scores"],
                "rawSourceIds": row["sourceIds"],
                "scoreQualifiedSourceIds": qualified_sources,
                "acceptedResultCount": len(accepted),
                "acceptedSourceIds": accepted_sources,
                "acceptedRelevantEvidence": accepted,
            }
        )

    hit_at_1: list[float] = []
    hit_at_k: list[float] = []
    recall_at_k: list[float] = []
    mrr: list[float] = []
    scenario_misses: list[str] = []
    for row in positive_rows:
        expected = EXPECTED_SOURCES.get(row["taskId"], [])
        expected_set = set(expected)
        accepted = accepted_relevant_evidence(row, threshold)
        qualified = [
            (source, score)
            for source, score in zip(
                row["sourceIds"], row["scores"], strict=False
            )
        ]
        hit_at_1.append(
            1.0
            if qualified
            and qualified[0][1] >= threshold
            and qualified[0][0] in expected_set
            else 0.0
        )
        hit_at_k.append(
            1.0
            if any(
                score >= threshold and source in expected_set
                for source, score in qualified[: row["topK"]]
            )
            else 0.0
        )
        found = {
            source
            for source, score in qualified[: row["topK"]]
            if score >= threshold and source in expected_set
        }
        recall_at_k.append(len(found) / len(expected) if expected else 0.0)
        rank = qualified_rank(row, expected_set, threshold)
        mrr.append(1.0 / rank if rank is not None else 0.0)
        if not accepted:
            scenario_misses.append(row["taskId"])
        if (
            category(row["taskId"]) == "RELEVANT_OVER_DISTRACTOR"
            and SOURCE_KEYS["catalog"] in [item["sourceId"] for item in accepted]
        ):
            scenario_misses.append(f"{row['taskId']}:catalog-distractor-leak")

    setup = read_json(SETUP_REPORT_PATH)
    manifest = read_json(MANIFEST_PATH)
    coverage = list(manifest.get("coverage", []))
    manifest_knowledge_types = {
        str(value) for value in manifest.get("knowledgeTypes", [])
    }
    missing_knowledge_types = sorted(
        REQUIRED_KNOWLEDGE_TYPES - manifest_knowledge_types
    )
    accepted_by_task = {
        row["taskId"]: accepted_relevant_evidence(row, threshold)
        for row in rows
    }
    covered = {
        "single exact evidence": any(
            category(row["taskId"]) == "SINGLE_EXACT"
            and accepted_by_task[row["taskId"]]
            for row in rows
        ),
        "multi constraint": any(
            category(row["taskId"]) == "MULTI_CONSTRAINT"
            and accepted_by_task[row["taskId"]]
            for row in rows
        ),
        "multi hit": any(
            category(row["taskId"]) in {"MULTI_CONSTRAINT", "MULTI_REPORT_INDEX"}
            and len(accepted_by_task[row["taskId"]]) > 1
            for row in rows
        ),
        "report plus index": any(
            category(row["taskId"]) == "MULTI_REPORT_INDEX"
            and accepted_by_task[row["taskId"]]
            for row in rows
        ),
        "citation identity": any(
            category(row["taskId"]) == "CITATION"
            and accepted_by_task[row["taskId"]]
            for row in rows
        ),
        "relevant versus distractor": any(
            category(row["taskId"]) == "RELEVANT_OVER_DISTRACTOR"
            and accepted_by_task[row["taskId"]]
            and SOURCE_KEYS["catalog"]
            not in [item["sourceId"] for item in accepted_by_task[row["taskId"]]]
            for row in rows
        ),
        "exact versus near match": any(
            category(row["taskId"]) == "EXACT_OVER_NEAR_MATCH"
            and accepted_by_task[row["taskId"]]
            for row in rows
        ),
        "authorized zero hit": all(
            row["taskId"] in ZERO_TASKS
            and not accepted_by_task[row["taskId"]]
            for row in rows
            if row["taskId"] in ZERO_TASKS
        ),
        "cross-project isolation": all(
            row["taskId"] in FORBIDDEN_TASKS
            and row["gatewayStatus"] == "FORBIDDEN"
            for row in rows
            if row["taskId"] in FORBIDDEN_TASKS
        ),
    }
    not_covered = [item for item in coverage if not covered.get(item, False)]
    positive_success = all(
        accepted_by_task[row["taskId"]] for row in positive_rows
    )
    scenario_counts = {
        "positive": len(positive_rows),
        "multi": sum(
            1
            for row in positive_rows
            if category(row["taskId"]) in {"MULTI_CONSTRAINT", "MULTI_REPORT_INDEX"}
        ),
        "nearMatch": sum(
            1 for row in positive_rows if category(row["taskId"]) == "EXACT_OVER_NEAR_MATCH"
        ),
        "distractor": sum(
            1
            for row in positive_rows
            if category(row["taskId"]) == "RELEVANT_OVER_DISTRACTOR"
        ),
        "zeroHit": sum(1 for row in rows if row["taskId"] in ZERO_TASKS),
        "crossProjectDeny": sum(
            1 for row in rows if row["taskId"] in FORBIDDEN_TASKS
        ),
    }
    hard_gate = {
        "corpusNotCoveredZero": len(not_covered) == 0,
        "requiredKnowledgeTypesCovered": not missing_knowledge_types,
        "failedZero": status_counts["FAILED"] == 0,
        "twoZeroHitScenarios": status_counts["ZERO_HIT"] == 2,
        "crossProjectDenyForbidden": status_counts["FORBIDDEN"] == 2,
        "citationMismatchZero": citation_mismatches == 0,
        "projectIsolationViolationZero": isolation_violations == 0,
        "positiveEvidenceRetrieves": positive_success,
        "noUnexpectedSources": not unexpected_sources,
    }
    result = {
        "generatedAt": datetime.now(UTC).isoformat(),
        "mode": "acceptance",
        "recipeCount": len(rows),
        "threshold": threshold,
        "corpus": {
            "corpusVersion": setup.get("corpusVersion"),
            "documents": setup.get("documents"),
            "chunks": setup.get("chunks"),
            "qdrantPoints": setup.get("qdrantPoints"),
            "project41": {
                "documents": setup.get("project41Documents"),
                "chunks": sum(
                    item.get("chunks", 0)
                    for item in setup.get("ingestedDocuments", [])
                    if item.get("projectId") == 41
                ),
                "qdrantPoints": sum(
                    item.get("qdrantPoints", 0)
                    for item in setup.get("ingestedDocuments", [])
                    if item.get("projectId") == 41
                ),
            },
            "project42": {
                "documents": setup.get("project42Documents"),
                "chunks": sum(
                    item.get("chunks", 0)
                    for item in setup.get("ingestedDocuments", [])
                    if item.get("projectId") == 42
                ),
                "qdrantPoints": sum(
                    item.get("qdrantPoints", 0)
                    for item in setup.get("ingestedDocuments", [])
                    if item.get("projectId") == 42
                ),
            },
        },
        "coverageNotCovered": not_covered,
        "knowledgeTypes": {
            "declared": sorted(manifest_knowledge_types),
            "required": sorted(REQUIRED_KNOWLEDGE_TYPES),
            "missing": missing_knowledge_types,
        },
        "scenarioCounts": scenario_counts,
        "statusCounts": dict(status_counts),
        "metrics": {
            "Hit@1": sum(hit_at_1) / len(hit_at_1) if hit_at_1 else 0.0,
            "Hit@K": sum(hit_at_k) / len(hit_at_k) if hit_at_k else 0.0,
            "Recall@K": sum(recall_at_k) / len(recall_at_k) if recall_at_k else 0.0,
            "MRR": sum(mrr) / len(mrr) if mrr else 0.0,
            "positiveScenarioCount": len(positive_rows),
        },
        "citationMismatches": citation_mismatches,
        "projectIsolationViolations": isolation_violations,
        "unexpectedSources": sorted(set(unexpected_sources)),
        "scenarioMisses": sorted(set(scenario_misses)),
        "relevancePolicy": {
            "kind": "score_and_evaluation_side_identity",
            "threshold": threshold,
            "comparison": "inclusive",
            "rawCandidatesPreserved": True,
            "runtimeGroundTruthLoaded": False,
        },
        "hardGate": hard_gate,
        "readiness": "PASS" if all(hard_gate.values()) else "FAIL",
        "recipes": normalized_rows,
    }
    return result


def acceptance_summary(result: dict[str, Any]) -> str:
    counts = result["statusCounts"]
    metrics = result["metrics"]
    gate = result["hardGate"]
    lines = [
        "# Stage21 RAG V2 deterministic acceptance",
        "",
        f"Readiness: **{result['readiness']}**",
        "",
        (
            f"- Corpus: `{result['corpus']['corpusVersion']}`; "
            f"{result['corpus']['documents']} documents, "
            f"{result['corpus']['chunks']} chunks, "
            f"{result['corpus']['qdrantPoints']} Qdrant points."
        ),
        (
            f"- Project 41: {result['corpus']['project41']['documents']} "
            f"documents / {result['corpus']['project41']['chunks']} chunks / "
            f"{result['corpus']['project41']['qdrantPoints']} points."
        ),
        (
            f"- Project 42: {result['corpus']['project42']['documents']} "
            f"documents / {result['corpus']['project42']['chunks']} chunks / "
            f"{result['corpus']['project42']['qdrantPoints']} points."
        ),
        f"- Relevance policy threshold: `{result['threshold']}` "
        "(acceptance-side; raw candidates are retained)",
        (
            f"- Statuses: SUCCESS_WITH_RESULTS="
            f"{counts.get('SUCCESS_WITH_RESULTS', 0)}, "
            f"ZERO_HIT={counts.get('ZERO_HIT', 0)}, "
            f"FORBIDDEN={counts.get('FORBIDDEN', 0)}, "
            f"FAILED={counts.get('FAILED', 0)}."
        ),
        (
            f"- Scenarios: positive={result['scenarioCounts']['positive']}, "
            f"multi={result['scenarioCounts']['multi']}, "
            f"near-match={result['scenarioCounts']['nearMatch']}, "
            f"distractor={result['scenarioCounts']['distractor']}, "
            f"zero-hit={result['scenarioCounts']['zeroHit']}, "
            f"cross-project-deny={result['scenarioCounts']['crossProjectDeny']}."
        ),
        (
            f"- Knowledge types: {len(result['knowledgeTypes']['declared'])} "
            f"declared; missing={result['knowledgeTypes']['missing'] or 'none'}."
        ),
        (
            f"- Hit@1={metrics['Hit@1']:.4f}, Hit@K={metrics['Hit@K']:.4f}, "
            f"Recall@K={metrics['Recall@K']:.4f}, MRR={metrics['MRR']:.4f}."
        ),
        f"- Citation mismatches: {result['citationMismatches']}; "
        f"isolation violations: {result['projectIsolationViolations']}.",
        "- Zero-hit semantics: accepted relevant evidence is empty even when "
        "raw candidates are present; raw/accepted counts are persisted per "
        "recipe.",
        "",
        "## Hard gate",
        "",
    ]
    for name, passed in gate.items():
        lines.append(f"- {'PASS' if passed else 'FAIL'}: `{name}`")
    if result["coverageNotCovered"]:
        lines.extend(
            ["", "Not covered:", "", *[f"- {item}" for item in result["coverageNotCovered"]]]
        )
    if result["scenarioMisses"]:
        lines.extend(
            ["", "Scenario misses:", "", *[f"- {item}" for item in result["scenarioMisses"]]]
        )
    if result["unexpectedSources"]:
        lines.extend(
            [
                "",
                "Unexpected citation sources:",
                "",
                *[f"- {item}" for item in result["unexpectedSources"]],
            ]
        )
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("calibration", "acceptance"), required=True)
    parser.add_argument("--base-url", default="http://127.0.0.1:19091")
    parser.add_argument("--threshold", type=float)
    parser.add_argument(
        "--output-dir",
        type=Path,
        help="unique evidence directory; defaults to a new pre-formal105 directory",
    )
    parser.add_argument("--timeout", type=float, default=30.0)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    rows = run_probes(args.base_url, args.mode, args.timeout)
    output_dir = args.output_dir
    if output_dir is None:
        output_dir = (
            REPOSITORY_ROOT
            / "artifacts/stage21"
            / f"pre-formal105-rag-{datetime.now(UTC):%Y%m%dT%H%M%SZ}"
        )
    if args.mode == "calibration":
        threshold, _ = calibration_report(rows, output_dir)
        print(
            json.dumps(
                {
                    "mode": args.mode,
                    "threshold": threshold,
                    "outputDir": str(output_dir),
                },
                ensure_ascii=False,
            )
        )
        return 0 if threshold is not None else 2
    if args.threshold is None:
        raise RuntimeError("--threshold is required for acceptance mode")
    result = acceptance_report(rows, args.threshold)
    write_json(output_dir / "acceptance.json", result)
    write_text(output_dir / "acceptance-summary.md", acceptance_summary(result))
    print(
        json.dumps(
            {
                "mode": args.mode,
                "readiness": result["readiness"],
                "hardGate": result["hardGate"],
                "outputDir": str(output_dir),
            },
            ensure_ascii=False,
        )
    )
    return 0 if result["readiness"] == "PASS" else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (RuntimeError, httpx.HTTPError) as error:
        print(f"STAGE21_RAG_V2_ACCEPTANCE_ERROR {error}", file=sys.stderr)
        raise SystemExit(2)
