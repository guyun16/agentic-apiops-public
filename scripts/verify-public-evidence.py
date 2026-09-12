"""Verify the reviewed public evidence bytes without executing any benchmark."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INVENTORY = ROOT / "artifacts/benchmark/public-evidence-sha256.json"


def verify(root: Path = ROOT, inventory: Path = INVENTORY) -> int:
    manifest = json.loads(inventory.read_text(encoding="utf-8"))
    if (
        manifest.get("schemaVersion") != "apiops-public-evidence/v1"
        or manifest.get("benchmarkExecuted") is not False
        or manifest.get("modelCalled") is not False
        or not isinstance(manifest.get("files"), dict)
        or not manifest["files"]
    ):
        raise ValueError("Invalid public evidence inventory")
    root = root.resolve()
    for relative, expected in manifest["files"].items():
        path = (root / relative).resolve()
        if not path.is_relative_to(root) or not path.is_file():
            raise ValueError(f"Missing or outside-root evidence: {relative}")
        if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError(f"Evidence digest mismatch: {relative}")
    return len(manifest["files"])


if __name__ == "__main__":
    print(f"PASS: {verify()} public evidence files match their recorded SHA-256 hashes")
