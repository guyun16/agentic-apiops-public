"""Historical source checks work with POSIX paths and Windows manifest keys."""

from __future__ import annotations

import sys
from pathlib import Path, PurePosixPath

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import stage21_final_revision_freeze as freeze  # noqa: E402
import stage21_final_v2_formal105 as formal  # noqa: E402


def test_prompt_freeze_resolves_portable_source_paths(monkeypatch) -> None:
    monkeypatch.setattr(formal, "REPOSITORY_ROOT", PurePosixPath("/snapshot"))
    monkeypatch.setattr(
        formal,
        "PROMPT_SOURCES",
        ({"name": "fixture", "version": "v1", "files": ("app/prompts/test.txt",)},),
    )
    observed = []

    def digest(files):
        observed.extend(files)
        return "fixture-digest"

    monkeypatch.setattr(formal, "_digest_paths", digest)
    result = formal._prompt_freeze()
    assert observed == [
        ("app/prompts/test.txt", PurePosixPath("/snapshot/app/prompts/test.txt"))
    ]
    assert result[0]["files"] == ["app/prompts/test.txt"]
    assert result[0]["digest"] == "fixture-digest"


def test_windows_manifest_keys_resolve_before_source_drift_check(monkeypatch) -> None:
    monkeypatch.setattr(freeze, "ROOT", PurePosixPath("/snapshot"))
    monkeypatch.setattr(
        formal,
        "_read_json",
        lambda _: {"sourceDigestsBefore": {r"java-apiops-platform\src\Example.java": "old"}},
    )
    observed = []

    def digest(path):
        observed.append(path)
        return "changed"

    monkeypatch.setattr(freeze.gate, "digest", digest)
    with pytest.raises(RuntimeError, match="ACCEPTANCE_IMPLEMENTATION_SOURCE_DRIFT"):
        freeze.verify_prior_evidence()
    assert observed == [PurePosixPath("/snapshot/java-apiops-platform/src/Example.java")]
