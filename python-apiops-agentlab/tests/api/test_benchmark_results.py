from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.api import routes as api_routes
from app.main import app as application
from app.services import benchmark_results as benchmark_service
from app.services.benchmark_results import BenchmarkArtifactStore
from tests.api.test_api_boundary import asgi_request

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
ARTIFACT_ROOT = REPOSITORY_ROOT / "artifacts"
RESULT_DIRECTORY = ARTIFACT_ROOT / "benchmark/runs/0ba27cd41f411892b1d44af2"

EVALUATION_RUN_ID = "evaluation_run:stage21-real-model-full-105-20260826T171200Z"


def _publication_manifest(tmp_path: Path, publications: list[dict[str, object]]) -> Path:
    path = tmp_path / "portfolio-manifest.json"
    path.write_text(
        json.dumps(
            {
                "schemaVersion": "apiops-bench-publication/v1",
                "publications": publications,
            }
        ),
        encoding="utf-8",
    )
    return path


def _publication(
    run_id: str = EVALUATION_RUN_ID,
    location: Path = RESULT_DIRECTORY / "run.json",
    *,
    name: str = "Baseline · APIOps-Bench 105",
    role: str = "BASELINE",
    order: int = 1,
) -> dict[str, object]:
    return {
        "evaluationRunId": run_id,
        "displayName": name,
        "role": role,
        "artifactLocation": str(location),
        "displayOrder": order,
    }


def test_real_completed_artifact_is_exposed_without_mock_fallback(
    monkeypatch,
    tmp_path: Path,
) -> None:
    manifest = _publication_manifest(tmp_path, [_publication()])
    store = BenchmarkArtifactStore((ARTIFACT_ROOT,), manifest_path=manifest)
    detail = store.get(EVALUATION_RUN_ID)

    assert detail is not None
    assert detail.display_name == "Baseline · APIOps-Bench 105"
    assert detail.role == "BASELINE"
    assert detail.evaluation_run_id == EVALUATION_RUN_ID
    assert len(detail.aggregate_metrics) == 20
    assert detail.selected_task_count == 105
    assert detail.completed_task_count == 105
    assert detail.failed_task_count == 0
    assert detail.task_success.pass_count == 3
    assert detail.task_success.fail_count == 69
    assert detail.task_success.unknown_count == 33

    baseline = json.loads((RESULT_DIRECTORY / "baseline-run.json").read_text(encoding="utf-8"))
    expected_metrics = {item["metric"]: item for item in baseline["overallMetrics"]["metrics"]}
    exposed_metrics = {item.metric.value: item for item in detail.aggregate_metrics}
    assert (
        exposed_metrics["diagnosis_accuracy"].rate == expected_metrics["diagnosis_accuracy"]["rate"]
    )
    assert exposed_metrics["tool_recall"].rate == expected_metrics["tool_recall"]["rate"]
    assert exposed_metrics["tool_precision"].state == "NOT_APPLICABLE"
    assert exposed_metrics["exact_match"].state == "UNKNOWN"
    assert all("DEMO" not in json.dumps(item.model_dump()) for item in detail.aggregate_metrics)

    monkeypatch.setattr(api_routes, "_benchmark_results_store", store)
    status, body, caught = asgi_request(
        application,
        "GET",
        "/api/v1/benchmark/results",
    )
    assert caught is None
    assert status == 200
    assert any(item["evaluationRunId"] == EVALUATION_RUN_ID for item in body)

    status, body, caught = asgi_request(
        application,
        "GET",
        "/api/v1/benchmark/results/" + EVALUATION_RUN_ID,
    )
    assert caught is None
    assert status == 200
    assert len(body["aggregateMetrics"]) == 20
    assert body["taskSuccess"]["passCount"] == 3
    assert "DEMO DATA" not in json.dumps(body)

    status, body, caught = asgi_request(
        application,
        "GET",
        "/api/v1/benchmark/results/" + EVALUATION_RUN_ID + "/tasks",
    )
    assert caught is None
    assert status == 200
    assert len(body) == 105
    assert body[0]["evaluationRunId"] == EVALUATION_RUN_ID
    assert body[0]["benchmarkTaskId"]


def test_only_manifest_publications_are_listed_and_smoke_is_not_discovered(
    monkeypatch,
    tmp_path: Path,
) -> None:
    smoke = tmp_path / "smoke" / "run.json"
    smoke.parent.mkdir()
    smoke.write_text((RESULT_DIRECTORY / "run.json").read_text(encoding="utf-8"), encoding="utf-8")
    manifest = _publication_manifest(tmp_path, [_publication()])

    store = BenchmarkArtifactStore((tmp_path, ARTIFACT_ROOT), manifest_path=manifest)
    listed = store.list()

    assert [item.evaluation_run_id for item in listed] == [EVALUATION_RUN_ID]
    assert all(item.selected_task_count == 105 for item in listed)
    monkeypatch.setattr(api_routes, "_benchmark_results_store", store)
    status, _, caught = asgi_request(
        application,
        "GET",
        "/api/v1/benchmark/results/evaluation_run:unpublished-smoke",
    )
    assert caught is None
    assert status == 404


def test_missing_or_identity_mismatched_publication_fails_closed(tmp_path: Path) -> None:
    manifest = _publication_manifest(
        tmp_path,
        [
            _publication(location=tmp_path / "missing" / "run.json"),
            _publication(run_id="evaluation_run:not-the-artifact", order=2),
        ],
    )
    store = BenchmarkArtifactStore((tmp_path, ARTIFACT_ROOT), manifest_path=manifest)

    assert store.list() == []
    assert store.get(EVALUATION_RUN_ID) is None
    assert store.tasks(EVALUATION_RUN_ID) is None


def test_duplicate_publication_identity_is_rejected(tmp_path: Path) -> None:
    manifest = _publication_manifest(
        tmp_path,
        [
            _publication(name="Current · APIOps-Bench 105", role="CURRENT", order=3),
            _publication(name="Baseline · APIOps-Bench 105", role="BASELINE", order=1),
        ],
    )

    listed = BenchmarkArtifactStore((ARTIFACT_ROOT,), manifest_path=manifest).list()

    assert listed == []


def test_publication_outside_approved_artifact_roots_fails_closed(tmp_path: Path) -> None:
    manifest_root = tmp_path / "manifest-root"
    manifest_root.mkdir()
    outside = tmp_path / "outside" / "run.json"
    outside.parent.mkdir()
    outside.write_text(
        (RESULT_DIRECTORY / "run.json").read_text(encoding="utf-8"), encoding="utf-8"
    )
    manifest = _publication_manifest(manifest_root, [_publication(location=outside)])

    assert BenchmarkArtifactStore((manifest_root,), manifest_path=manifest).list() == []


def test_corrupt_published_artifact_fails_closed(tmp_path: Path) -> None:
    artifact = tmp_path / "artifact-root" / "run.json"
    artifact.parent.mkdir()
    artifact.write_text("{not-json", encoding="utf-8")
    manifest = _publication_manifest(tmp_path, [_publication(location=artifact)])

    assert BenchmarkArtifactStore((artifact.parent,), manifest_path=manifest).list() == []


def test_repository_publication_contains_only_clean_clone_durable_runs() -> None:
    listed = BenchmarkArtifactStore().list()
    manifest = json.loads(
        (REPOSITORY_ROOT / "artifacts/benchmark/portfolio-manifest.json").read_text(
            encoding="utf-8"
        )
    )
    assert len(listed) == len(manifest["publications"])
    assert len(listed) >= 2
    assert all(item.selected_task_count == item.executed_task_count == 105 for item in listed)
    assert len({item.evaluation_run_id for item in listed}) == len(listed)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("role", []),
        ("role", "OTHER"),
        ("displayOrder", True),
        ("displayName", ""),
        ("evaluationRunId", ""),
        ("artifactLocation", "bad\x00path"),
        ("artifactLocation", ""),
    ],
)
def test_malformed_publication_fails_closed(tmp_path: Path, field: str, value: object) -> None:
    entry = _publication()
    entry[field] = value
    manifest = _publication_manifest(tmp_path, [entry])
    assert BenchmarkArtifactStore((ARTIFACT_ROOT,), manifest).list() == []


def test_malformed_duplicate_cannot_select_an_identity(tmp_path: Path) -> None:
    manifest = _publication_manifest(tmp_path, [_publication(), _publication(role="INVALID")])
    assert BenchmarkArtifactStore((ARTIFACT_ROOT,), manifest).list() == []


def test_manifest_order_overrides_dates_without_changing_run_identity(tmp_path: Path) -> None:
    entries = json.loads(
        (REPOSITORY_ROOT / "artifacts/benchmark/portfolio-manifest.json").read_text(
            encoding="utf-8"
        )
    )["publications"]
    for order, entry in enumerate(reversed(entries), start=1):
        entry["displayOrder"] = order
    manifest = _publication_manifest(tmp_path, entries)
    store = BenchmarkArtifactStore((REPOSITORY_ROOT / "artifacts",), manifest)
    assert [item.evaluation_run_id for item in store.list()] == [
        entry["evaluationRunId"] for entry in reversed(entries)
    ]


@pytest.mark.parametrize("contents", ["{invalid", "[]", '{"schemaVersion":"other"}'])
def test_invalid_manifest_fails_closed(tmp_path: Path, contents: str) -> None:
    manifest = tmp_path / "manifest.json"
    store = BenchmarkArtifactStore((ARTIFACT_ROOT,), manifest)
    assert store.list() == []
    manifest.write_text(contents, encoding="utf-8")
    assert store.list() == []


def test_path_traversal_outside_artifact_root_fails_closed(tmp_path: Path) -> None:
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    outside = tmp_path / "run.json"
    outside.write_bytes((RESULT_DIRECTORY / "run.json").read_bytes())
    manifest = _publication_manifest(tmp_path, [_publication(location=allowed / ".." / "run.json")])
    assert BenchmarkArtifactStore((allowed,), manifest).list() == []


def test_full105_publication_rejects_partial_duplicate_and_aborted_runs(tmp_path: Path) -> None:
    original = json.loads((RESULT_DIRECTORY / "run.json").read_text(encoding="utf-8"))
    path = tmp_path / "run.json"
    manifest = _publication_manifest(tmp_path, [_publication(location=path)])
    for change in ("partial", "duplicate", "aborted", "wrong_run"):
        run = json.loads(json.dumps(original))
        if change == "partial":
            run["results"].pop()
        elif change == "duplicate":
            run["results"][-1] = run["results"][0]
        elif change == "aborted":
            run["aborted"] = True
        else:
            run["results"][0]["evaluationRunId"] = "evaluation_run:other"
        path.write_text(json.dumps(run), encoding="utf-8")
        assert BenchmarkArtifactStore((tmp_path,), manifest_path=manifest).list() == [], change


def test_task_artifact_references_are_parsed_once_per_request(tmp_path: Path, monkeypatch) -> None:
    run = json.loads((RESULT_DIRECTORY / "run.json").read_text(encoding="utf-8"))
    path = tmp_path / "run.json"
    path.write_text(json.dumps(run), encoding="utf-8")
    references = {}
    for index in (0, 104):
        task_path = tmp_path / f"task-{index}.json"
        task_path.write_text(json.dumps(run["results"][index]), encoding="utf-8")
        references[run["results"][index]["benchmarkTaskId"]] = task_path.name
    (tmp_path / "baseline-run.json").write_text(
        json.dumps({"taskResultArtifacts": list(references.values())}), encoding="utf-8"
    )
    manifest = _publication_manifest(tmp_path, [_publication(location=path)])
    reads = []
    original_read = benchmark_service._read_model

    def counted_read(path, model):
        reads.append(path.name)
        return original_read(path, model)

    monkeypatch.setattr(benchmark_service, "_read_model", counted_read)
    tasks = BenchmarkArtifactStore((tmp_path,), manifest).tasks(EVALUATION_RUN_ID)
    assert tasks is not None and len(tasks) == 105
    assert {
        task.benchmark_task_id: task.artifact_ref for task in tasks if task.artifact_ref
    } == references
    assert reads.count("task-0.json") == reads.count("task-104.json") == 1


@pytest.mark.parametrize("method", ["get", "tasks"])
def test_single_run_view_does_not_parse_unrelated_publications(tmp_path: Path, monkeypatch, method):
    unrelated = tmp_path / "unrelated.json"
    unrelated.write_text("{}", encoding="utf-8")
    manifest = _publication_manifest(
        tmp_path,
        [_publication(), _publication(run_id="evaluation_run:unrelated", location=unrelated)],
    )
    original_read = benchmark_service._read_model

    def guarded_read(path, model):
        assert path != unrelated, "A single-run view must not deserialize unrelated artifacts"
        return original_read(path, model)

    monkeypatch.setattr(benchmark_service, "_read_model", guarded_read)
    store = BenchmarkArtifactStore((tmp_path, ARTIFACT_ROOT), manifest)
    assert getattr(store, method)(EVALUATION_RUN_ID) is not None
