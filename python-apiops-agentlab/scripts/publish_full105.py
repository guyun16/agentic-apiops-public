"""Publish complete persisted Full105 runs; never execute or rescore tasks.

Run from python-apiops-agentlab with: python scripts/publish_full105.py
Selected immutable JSON bundles are copied into artifacts/benchmark/runs.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.benchmark.runner import BenchmarkRun
from app.services.benchmark_results import is_complete_full105


def main() -> None:
    root = Path(__file__).resolve().parents[2]
    manifest_path = root / "artifacts/benchmark/portfolio-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    previous = {entry["evaluationRunId"]: entry for entry in manifest["publications"]}
    found: dict[str, tuple[Path, BenchmarkRun]] = {}
    for directory in ("artifacts/stage21", "f105r", "python-apiops-agentlab/artifacts"):
        for path in sorted((root / directory).rglob("run.json")):
            try:
                run = BenchmarkRun.model_validate_json(path.read_text(encoding="utf-8"))
            except (ValueError, OSError):
                continue
            if is_complete_full105(run):
                found.setdefault(run.evaluation_run_id, (path, run))
    publications = []
    evidence = []
    for index, (run_id, (source, run)) in enumerate(
        sorted(found.items(), key=lambda entry: entry[1][1].started_at), 1
    ):
        destination = (
            root / "artifacts/benchmark/runs" / hashlib.sha256(run_id.encode()).hexdigest()[:24]
        )
        destination.mkdir(parents=True, exist_ok=True)
        # Copy the persisted run and companion JSON only, never credentials or logs.
        for companion in source.parent.glob("*.json"):
            if not companion.is_file():
                continue
            target = destination / companion.name
            if target.exists() and target.read_bytes() != companion.read_bytes():
                raise ValueError(f"Immutable publication conflict: {target}")
            if not target.exists():
                shutil.copyfile(companion, target)
        old = previous.get(run_id, {})
        publications.append(
            {
                "evaluationRunId": run_id,
                "displayName": old.get(
                    "displayName", f"Full105 · {run.started_at.isoformat()} · {run.dataset_version}"
                ),
                "role": old.get("role", "HISTORY"),
                "artifactLocation": (destination / "run.json").relative_to(root).as_posix(),
                "displayOrder": index,
            }
        )
        evidence.append(
            {
                "evaluationRunId": run_id,
                "source": source.relative_to(root).as_posix(),
                "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                "taskCount": 105,
            }
        )
    manifest["publications"] = publications
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (manifest_path.parent / "full105-selection.json").write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"Published {len(publications)} complete Full105 runs.")


if __name__ == "__main__":
    main()
