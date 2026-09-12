from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.benchmark import (
    DATASET_FORMAL_MIN_TASK_COUNT,
    DATASET_V1_CATEGORY_TARGETS,
    DATASET_V1_SPLIT_TARGETS,
    DATASET_V1_TASK_COUNT,
    DEFAULT_DATASET_MANIFEST_PATH,
    DEFAULT_DATASET_SMOKE_MANIFEST_PATH,
    DatasetManifest,
    lint_dataset,
    load_dataset,
)

TASK_IDS = (
    "bench_task_golden_e2e_apiops",
    "bench_task_golden_failure_diagnosis",
    "bench_task_golden_rag_evidence",
    "bench_task_golden_testcase_happy",
    "bench_task_golden_tool_safety",
)


@pytest.fixture(scope="module")
def dataset():
    return load_dataset()


@pytest.mark.parametrize("task_id", TASK_IDS)
def test_manifest_loader_exposes_each_golden_task(dataset, task_id: str) -> None:
    task = next(task for task in dataset.tasks if task.benchmark_task_id == task_id)
    entry = next(entry for entry in dataset.manifest.tasks if entry.benchmark_task_id == task_id)
    truth = next(
        truth
        for truth in dataset.ground_truths
        if truth.ground_truth_id == entry.ground_truth_ref.ground_truth_id
        and truth.version == entry.ground_truth_ref.version
    )

    assert task.schema_version == dataset.manifest.task_schema_version == "0.2.0"
    assert task.ground_truth_ref == entry.ground_truth_ref
    assert truth.ground_truth_id == entry.ground_truth_ref.ground_truth_id
    assert truth.version == entry.ground_truth_ref.version


def test_formal_dataset_quality_and_coverage() -> None:
    report = lint_dataset()

    assert report.is_valid
    assert report.structurally_valid
    assert report.dataset_ready
    assert not [issue for issue in report.issues if issue.severity == "ERROR"]
    assert not report.issues
    assert report.coverage.task_count == 105
    assert report.coverage.task_count >= DATASET_FORMAL_MIN_TASK_COUNT
    assert report.coverage.category_counts == {
        "TESTCASE_GENERATION": 30,
        "FAILURE_DIAGNOSIS": 34,
        "TOOL_SAFETY": 21,
        "RAG_EVIDENCE_RETRIEVAL": 15,
        "E2E_APIOPS": 5,
    }
    assert report.coverage.difficulty_counts == {"hard": 40, "easy": 21, "medium": 44}
    assert report.coverage.split_counts == {"dev": 95, "held_out": 10}
    assert not report.duplicate_candidates
    assert not report.leakage_candidates
    assert {issue.code for issue in report.issues} == set()
    assert report.review_status_counts == {"APPROVED": 105}


def test_legacy_40_task_smoke_manifest_remains_ready() -> None:
    report = lint_dataset(DEFAULT_DATASET_SMOKE_MANIFEST_PATH)

    assert report.dataset_ready
    assert report.coverage.task_count == DATASET_V1_TASK_COUNT
    assert report.coverage.category_counts == DATASET_V1_CATEGORY_TARGETS
    assert report.coverage.split_counts == DATASET_V1_SPLIT_TARGETS


def test_frozen_rag_and_insufficient_evidence_semantics_are_explicit(dataset) -> None:
    truths = {truth.ground_truth_id: truth for truth in dataset.ground_truths}

    zero_hit = truths["gt_stage21_rag_zero_hit"]
    zero_hit_facts = {fact.name: fact.value for fact in zero_hit.expected_facts}
    assert zero_hit_facts["authorization_outcome"] == "AUTHORIZED"
    assert zero_hit_facts["retrieval_expectation"] == "ZERO_HIT"
    assert zero_hit_facts["expected_evidence_count"] == 0
    assert zero_hit.expected_evidence_ids is None

    wrong_project = truths["gt_stage21_rag_wrong_project"]
    wrong_project_facts = {fact.name: fact.value for fact in wrong_project.expected_facts}
    assert wrong_project_facts["retrieval_expectation"] == "ACCESS_DENIED"
    assert wrong_project_facts["project_isolation"] == "NO_CROSS_PROJECT_HIT"
    assert wrong_project_facts["evidence_leakage"] is False
    assert wrong_project.expected_safety_outcome.value == "JAVA_DENIED"

    for truth_id in (
        "gt_stage21_failure_insufficient_missing",
        "gt_stage21_failure_insufficient_conflicting",
    ):
        facts = {fact.name: fact.value for fact in truths[truth_id].expected_facts}
        assert facts["sufficientEvidence"] is False
        assert facts["rootCauseHypotheses"] == []
        assert facts["limitations_required"] is True
        assert "missing_evidence" not in facts
        assert "conflict_type" not in facts
        assert "known_fact" not in facts


def test_idempotency_candidate_is_replaced_by_metadata_grounded_task(dataset) -> None:
    task_ids = {task.benchmark_task_id for task in dataset.tasks}
    assert "bench_task_testcase_idempotency_callback" not in task_ids
    replacement = next(
        task
        for task in dataset.tasks
        if task.benchmark_task_id == "bench_task_testcase_boundary_list_products_page_size"
    )
    assert replacement.ground_truth_ref.ground_truth_id == (
        "gt_stage21_testcase_boundary_list_products_page_size"
    )


def test_guarded_diagnosis_contract_never_requires_evidence_denied_by_java(dataset) -> None:
    task = next(
        task
        for task in dataset.tasks
        if task.benchmark_task_id == "bench_task_e2e_diagnosis_tool_guarded"
    )
    truth = next(
        truth
        for truth in dataset.ground_truths
        if truth.ground_truth_id == "gt_stage21_e2e_diagnosis_tool_guarded"
    )

    assert task.ground_truth_ref.version == truth.version == "v4"
    assert truth.expected_evidence_ids == ("CURRENT_JAVA_REPORT",)
    assert truth.expected_diagnosis == "BUSINESS_ERROR"
    assert truth.expected_safety_outcome.value == "JAVA_DENIED"


def test_dataset_review_artifact_covers_every_manifest_task() -> None:
    artifact = DEFAULT_DATASET_MANIFEST_PATH.parent / "dataset-review.md"
    content = artifact.read_text(encoding="utf-8")
    manifest = json.loads(DEFAULT_DATASET_MANIFEST_PATH.read_text(encoding="utf-8"))

    assert "dataset_ready=True" in content
    assert "APPROVED" in content
    assert "instruction_review" in content
    assert "evidence_sources" in content
    assert "bench_task_failure_multiple_evidence" in content
    assert all(entry["benchmarkTaskId"] in content for entry in manifest["tasks"])


def test_final_authority_cleanup_is_explicit_and_non_live() -> None:
    catalog_path = DEFAULT_DATASET_MANIFEST_PATH.parent / "support" / "evidence-catalog.json"
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    assert catalog["fixtureType"] == "STATIC_BENCHMARK_FIXTURE"
    assert {item["evidenceId"] for item in catalog["evidence"]} == {
        "rag:orders-constraint-001",
        "rag:orders-unique-index",
        "rag:orders-unique-index-summary",
        "rag:product-catalog-999",
    }

    active_truth_files = list(
        (DEFAULT_DATASET_MANIFEST_PATH.parent / "ground_truth").glob("*.json")
    )
    active_truth_text = "\n".join(path.read_text(encoding="utf-8") for path in active_truth_files)
    assert "report:report-701" not in active_truth_text
    assert "report:701" not in active_truth_text
    assert "CURRENT_JAVA_REPORT" in active_truth_text


def test_auth_task_uses_only_proven_document_level_security() -> None:
    task = next(
        task
        for task in load_dataset().tasks
        if task.benchmark_task_id == "bench_task_testcase_auth_missing_token"
    )
    metadata = next(entry for entry in task.initial_state.entries if entry.key == "apiMetadata")
    assert metadata.ref == "examples/openapi-metadata-valid.json"

    truth = next(
        truth
        for truth in load_dataset().ground_truths
        if truth.ground_truth_id == "gt_stage21_testcase_auth_missing_token"
    )
    facts = {fact.name: fact.value for fact in truth.expected_facts}
    assert facts == {
        "task_strategy": "AUTH_FAILURE",
        "security_requirement": "apiKeyAuth",
        "security_scope": "DOCUMENT_LEVEL",
        "operation_http_status": "UNSPECIFIED_BY_METADATA",
    }


def test_transport_task_is_active_and_duplicate_is_retired() -> None:
    dataset = load_dataset()
    task_ids = {task.benchmark_task_id for task in dataset.tasks}
    assert "bench_task_failure_transport_connect" in task_ids
    assert "bench_task_failure_multiple_evidence" not in task_ids
    assert (
        DEFAULT_DATASET_MANIFEST_PATH.parent
        / "rejected"
        / "bench_task_failure_multiple_evidence.json"
    ).is_file()


def test_quality_lint_rejects_an_incomplete_manifest(tmp_path: Path) -> None:
    manifest_path = _copy_dataset(tmp_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["tasks"].pop()
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    report = lint_dataset(manifest_path)

    assert "MANIFEST_INCONSISTENT" in {issue.code for issue in report.issues}
    assert not report.dataset_ready


def test_quality_lint_reports_cross_split_leakage_candidate(tmp_path: Path) -> None:
    manifest_path = _copy_dataset(tmp_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    dev_entry = _entry(manifest, "bench_task_golden_e2e_apiops")
    held_out_entry = _entry(manifest, "bench_task_testcase_missing_required_schema")
    source_task = _task_path(manifest_path, manifest, dev_entry["benchmarkTaskId"])
    held_out_task = _task_path(manifest_path, manifest, held_out_entry["benchmarkTaskId"])
    task = json.loads(source_task.read_text(encoding="utf-8"))
    task["benchmarkTaskId"] = held_out_entry["benchmarkTaskId"]
    held_out_task.write_text(json.dumps(task), encoding="utf-8")
    held_out_entry["groundTruthFile"] = dev_entry["groundTruthFile"]
    held_out_entry["groundTruthRef"] = dev_entry["groundTruthRef"]
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    report = lint_dataset(manifest_path)

    assert report.leakage_candidates
    assert "LEAKAGE_CANDIDATE" in {issue.code for issue in report.issues}


def test_manifest_rejects_duplicate_task_entries() -> None:
    raw = json.loads(DEFAULT_DATASET_MANIFEST_PATH.read_text(encoding="utf-8"))
    raw["tasks"].append(raw["tasks"][0])

    with pytest.raises(ValidationError):
        DatasetManifest.model_validate_json(json.dumps(raw))


@pytest.mark.parametrize(
    ("mutation", "expected_code"),
    (
        ("expected_tool_not_allowed", "TOOL_POLICY_INCONSISTENT"),
        ("schema_unknown_field", "SCHEMA_INVALID"),
        ("missing_python_fixture", "FIXTURE_MISSING"),
        ("ground_truth_incomplete", "GROUND_TRUTH_INCOMPLETE"),
        ("evaluation_spec_mismatch", "EVALUATION_SPEC_INVALID"),
        ("manifest_file_mismatch", "MANIFEST_INCONSISTENT"),
    ),
)
def test_quality_lint_detects_common_dataset_errors(
    tmp_path: Path,
    mutation: str,
    expected_code: str,
) -> None:
    manifest_path = _copy_dataset(tmp_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    if mutation == "expected_tool_not_allowed":
        task_path = _task_path(manifest_path, manifest, "bench_task_golden_failure_diagnosis")
        task = json.loads(task_path.read_text(encoding="utf-8"))
        task["allowedTools"] = ["redis.read"]
        task_path.write_text(json.dumps(task), encoding="utf-8")
    elif mutation == "schema_unknown_field":
        task_path = _task_path(manifest_path, manifest, "bench_task_golden_testcase_happy")
        task = json.loads(task_path.read_text(encoding="utf-8"))
        task["unknownField"] = True
        task_path.write_text(json.dumps(task), encoding="utf-8")
    elif mutation == "missing_python_fixture":
        task_path = _task_path(manifest_path, manifest, "bench_task_golden_rag_evidence")
        task = json.loads(task_path.read_text(encoding="utf-8"))
        fixture_entry = next(
            entry
            for entry in task["initialState"]["entries"]
            if entry.get("kind") == "PYTHON_FIXTURE"
        )
        fixture_entry["ref"] = "examples/missing-stage21-fixture.json"
        task_path.write_text(json.dumps(task), encoding="utf-8")
    elif mutation == "ground_truth_incomplete":
        truth_path = _truth_path(
            manifest_path,
            manifest,
            "bench_task_golden_failure_diagnosis",
        )
        truth = json.loads(truth_path.read_text(encoding="utf-8"))
        truth["expected_diagnosis"] = None
        truth_path.write_text(json.dumps(truth), encoding="utf-8")
    elif mutation == "evaluation_spec_mismatch":
        task_path = _task_path(manifest_path, manifest, "bench_task_golden_testcase_happy")
        task = json.loads(task_path.read_text(encoding="utf-8"))
        task["metrics"] = ["valid_json"]
        task_path.write_text(json.dumps(task), encoding="utf-8")
    elif mutation == "manifest_file_mismatch":
        entry = _entry(manifest, "bench_task_golden_testcase_happy")
        mismatched = manifest_path.parent / "tasks" / "mismatched.json"
        mismatched.write_text(
            _task_path(manifest_path, manifest, "bench_task_golden_e2e_apiops").read_text(
                encoding="utf-8"
            ),
            encoding="utf-8",
        )
        entry["taskFile"] = "tasks/mismatched.json"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    else:
        raise AssertionError(f"unhandled mutation: {mutation}")

    report = lint_dataset(manifest_path)
    assert expected_code in {issue.code for issue in report.issues}


def test_quality_lint_detects_obvious_duplicate(tmp_path: Path) -> None:
    manifest_path = _copy_dataset(tmp_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    source_task = _task_path(manifest_path, manifest, "bench_task_golden_failure_diagnosis")
    duplicate_task = _task_path(manifest_path, manifest, "bench_task_golden_rag_evidence")
    duplicate_truth = manifest_path.parent / "ground_truth" / "gt_obvious_duplicate.json"

    task = json.loads(source_task.read_text(encoding="utf-8"))
    task["benchmarkTaskId"] = "bench_task_obvious_duplicate"
    duplicate_task.write_text(json.dumps(task), encoding="utf-8")
    truth = json.loads(
        _truth_path(manifest_path, manifest, "bench_task_golden_failure_diagnosis").read_text(
            encoding="utf-8"
        )
    )
    duplicate_truth.write_text(json.dumps(truth), encoding="utf-8")
    entry = _entry(manifest, "bench_task_golden_rag_evidence")
    entry["benchmarkTaskId"] = "bench_task_obvious_duplicate"
    entry["groundTruthFile"] = "ground_truth/gt_obvious_duplicate.json"
    entry["groundTruthRef"] = {
        "groundTruthId": "gt_stage21_failure_diagnosis",
        "version": "v1",
    }
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    report = lint_dataset(manifest_path)
    assert "OBVIOUS_DUPLICATE" in {issue.code for issue in report.issues}


def _copy_dataset(tmp_path: Path) -> Path:
    source_root = DEFAULT_DATASET_MANIFEST_PATH.parent
    destination = tmp_path / "fixtures"
    shutil.copytree(source_root / "tasks", destination / "tasks")
    shutil.copytree(source_root / "ground_truth", destination / "ground_truth")
    shutil.copytree(source_root / "formal", destination / "formal")
    manifest_path = destination / "dataset-manifest.json"
    shutil.copy2(DEFAULT_DATASET_MANIFEST_PATH, manifest_path)
    return manifest_path


def _entry(manifest: dict[str, object], task_id: str) -> dict[str, object]:
    return next(entry for entry in manifest["tasks"] if entry["benchmarkTaskId"] == task_id)  # type: ignore[index]


def _task_path(manifest_path: Path, manifest: dict[str, object], task_id: str) -> Path:
    entry = _entry(manifest, task_id)
    return manifest_path.parent / entry["taskFile"]  # type: ignore[operator]


def _truth_path(manifest_path: Path, manifest: dict[str, object], task_id: str) -> Path:
    entry = _entry(manifest, task_id)
    return manifest_path.parent / entry["groundTruthFile"]  # type: ignore[operator]
