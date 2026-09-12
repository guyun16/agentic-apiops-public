"""Offline publication acceptance, independent of historical Stage21 gates."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
SPEC = importlib.util.spec_from_file_location(
    "portfolio_freeze", ROOT / "python-apiops-agentlab/scripts/freeze_benchmark_portfolio.py"
)
assert SPEC is not None and SPEC.loader is not None
freeze = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(freeze)


def test_repository_portfolio_source_freeze() -> None:
    evidence = freeze.verify()
    assert evidence["purpose"] == "PORTFOLIO_PUBLICATION_ACCEPTANCE"
    assert evidence["benchmarkExecuted"] is False
    assert evidence["modelCalled"] is False
    assert not any(
        path.startswith(("artifacts/stage21/", "f105r/", "python-apiops-agentlab/artifacts/"))
        for path in freeze.SOURCES
    )


def test_source_drift_and_duplicate_write_are_rejected(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "viewer.ts"
    source.write_bytes(b"original\n")
    monkeypatch.setattr(freeze, "ROOT", tmp_path)
    monkeypatch.setattr(freeze, "SOURCES", ("viewer.ts",))
    output = tmp_path / "freeze.json"
    freeze.write(output)
    source.write_bytes(b"original\r\n")
    freeze.verify(output)
    with pytest.raises(RuntimeError, match="ALREADY_EXISTS"):
        freeze.write(output)
    source.write_bytes(b"changed\n")
    with pytest.raises(RuntimeError, match="SOURCE_DRIFT"):
        freeze.verify(output)


@pytest.mark.parametrize(
    ("field", "value", "error"),
    [
        ("schemaVersion", "other", "SCHEMA_MISMATCH"),
        ("purpose", "HISTORICAL_ACCEPTANCE", "SCOPE_MISMATCH"),
        ("benchmarkExecuted", True, "SCOPE_MISMATCH"),
        ("modelCalled", True, "SCOPE_MISMATCH"),
    ],
)
def test_freeze_scope_is_enforced(tmp_path: Path, field: str, value: object, error: str) -> None:
    output = tmp_path / "freeze.json"
    freeze.write(output)
    payload = json.loads(output.read_text(encoding="utf-8"))
    payload[field] = value
    output.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(RuntimeError, match=error):
        freeze.verify(output)
