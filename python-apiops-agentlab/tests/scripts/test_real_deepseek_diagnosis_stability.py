from __future__ import annotations

from pathlib import Path
from runpy import run_path

_MODULE = run_path(
    str(Path(__file__).resolve().parents[2] / "scripts" / "real_deepseek_diagnosis_stability.py")
)
canonical_json = _MODULE["canonical_json"]
sha256_text = _MODULE["sha256_text"]


def test_semantic_digest_is_ordered_and_runtime_independent() -> None:
    first = {"b": 2, "a": ["same", {"z": True}]}
    second = {"a": ["same", {"z": True}], "b": 2}
    assert canonical_json(first) == canonical_json(second)
    assert sha256_text(canonical_json(first)) == sha256_text(canonical_json(second))


def test_digest_does_not_retain_secret_text() -> None:
    secret = "DEEPSEEK_API_KEY=not-for-output"
    digest = sha256_text(secret)
    assert secret not in digest
    assert len(digest) == 64
