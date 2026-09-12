"""Freeze or verify APIOps Bench publication sources without running evaluation."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PREVIOUS_OUTPUT = ROOT / "artifacts" / "benchmark" / "portfolio-source-freeze-v5.json"
DEFAULT_OUTPUT = ROOT / "artifacts" / "benchmark" / "portfolio-source-freeze-public-v1.json"
SOURCES = (
    "artifacts/benchmark/public-evidence-sha256.json",
    "scripts/verify-public-evidence.py",
    "zh/README.md",
    "artifacts/benchmark/portfolio-manifest.json",
    "python-apiops-agentlab/app/services/benchmark_results.py",
    "python-apiops-agentlab/tests/api/test_benchmark_results.py",
    "python-apiops-agentlab/scripts/freeze_benchmark_portfolio.py",
    "python-apiops-agentlab/tests/scripts/test_stage21_final_revision_freeze.py",
    "apiops-console/src/features/benchmark/BenchmarkPage.tsx",
    "apiops-console/src/features/benchmark/finalResultAdapter.ts",
    "apiops-console/src/features/benchmark/final-result.snapshot.json",
    "apiops-console/scripts/verify-benchmark.ts",
    "python-apiops-agentlab/tests/scripts/test_benchmark_portfolio_freeze.py",
    "apiops-console/scripts/build-benchmark.mjs",
    "apiops-console/tsconfig.benchmark.json",
    "README.md",
    "apiops-console/package.json",
    "apiops-console/src/app/ConsoleLanguage.tsx",
    "apiops-console/src/features/benchmark/benchmark.css",
    "apiops-console/src/features/benchmark/benchmarkViewModel.ts",
    "apiops-console/src/features/benchmark/components/BenchmarkDetailDialog.tsx",
    "apiops-console/src/features/benchmark/components/BenchmarkOverview.tsx",
    "apiops-console/src/features/benchmark/components/BenchmarkRuns.tsx",
    "apiops-console/src/features/benchmark/components/BenchmarkSummary.tsx",
    "apiops-console/src/features/benchmark/components/BenchmarkTabContent.tsx",
    "apiops-console/src/features/benchmark/components/CopyValue.tsx",
    "apiops-console/src/features/benchmark/components/FinalBenchmarkOverview.tsx",
    "apiops-console/src/features/benchmark/final-result.summary.json",
    "apiops-console/src/features/benchmark/types.ts",
    "docs/benchmark-design.md",
    "docs/benchmark-publication.md",
    "apiops-console/src/features/benchmark/components/Full105History.tsx",
    "docs/stage21-benchmark-authority.json",
)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def inventory() -> dict[str, str]:
    # Git checkout may convert LF to CRLF; only line endings are normalized.
    return {
        relative: hashlib.sha256((ROOT / relative).read_text(encoding="utf-8").encode()).hexdigest()
        for relative in SOURCES
    }


def verify(path: Path = DEFAULT_OUTPUT) -> dict[str, object]:
    evidence = json.loads(path.read_text(encoding="utf-8"))
    if (
        evidence.get("schemaVersion") != "apiops-bench-source-freeze/v2"
        or evidence.get("sourceNormalization") != "utf8-lf"
    ):
        raise RuntimeError("PORTFOLIO_SOURCE_FREEZE_SCHEMA_MISMATCH")
    if evidence.get("sourceInventory") != inventory():
        raise RuntimeError("PORTFOLIO_SOURCE_DRIFT")
    if evidence.get("previousFreezeSha256") != digest(PREVIOUS_OUTPUT):
        raise RuntimeError("PORTFOLIO_PREVIOUS_FREEZE_DRIFT")
    if (
        evidence.get("benchmarkExecuted") is not False
        or evidence.get("modelCalled") is not False
        or evidence.get("purpose") != "PORTFOLIO_PUBLICATION_ACCEPTANCE"
    ):
        raise RuntimeError("PORTFOLIO_SOURCE_FREEZE_SCOPE_MISMATCH")
    return evidence


def write(path: Path = DEFAULT_OUTPUT) -> None:
    if path.exists():
        raise RuntimeError("PORTFOLIO_SOURCE_FREEZE_ALREADY_EXISTS")
    payload = {
        "schemaVersion": "apiops-bench-source-freeze/v2",
        "sourceNormalization": "utf8-lf",
        "purpose": "PORTFOLIO_PUBLICATION_ACCEPTANCE",
        "benchmarkExecuted": False,
        "modelCalled": False,
        "previousFreezeSha256": digest(PREVIOUS_OUTPUT),
        "sourceInventory": inventory(),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    if args.write:
        write(args.output)
    else:
        verify(args.output)
    print("APIOPS_BENCH_PORTFOLIO_SOURCE_FREEZE_PASS")


if __name__ == "__main__":
    main()
