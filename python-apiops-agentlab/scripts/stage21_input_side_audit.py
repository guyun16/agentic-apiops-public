"""Run the read-only Stage 21 v3 input-side audit and write its artifacts."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

AGENTLAB_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = AGENTLAB_ROOT.parent
if str(AGENTLAB_ROOT) not in sys.path:
    sys.path.insert(0, str(AGENTLAB_ROOT))

from app.input_side_audit import (  # noqa: E402
    assert_result_invariants,
    result_digest,
    run_input_side_audit,
    run_validator_self_tests,
)

FIXTURE_ROOT = AGENTLAB_ROOT / "tests" / "benchmark" / "fixtures"
MANIFEST_PATH = FIXTURE_ROOT / "dataset-manifest.json"
SIDECAR_PATH = FIXTURE_ROOT / "stage21-execution-prerequisites.json"
RECIPE_DIR = FIXTURE_ROOT / "support"


def _write_json(path: Path, payload: object) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _find_original_54_matrix() -> Path | None:
    root = AGENTLAB_ROOT / "artifacts" / "stage21" / "input-side-audit-v3"
    candidates = sorted(root.glob("*/input-side-audit-matrix.json"))
    for candidate in candidates:
        try:
            payload = json.loads(candidate.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        counts = payload.get("metadata", {}).get("classificationCounts", {})
        if counts.get("TASK_INPUT_CONTRACT_GAP") == 54:
            return candidate
    return None


def _reclassification_54(
    previous_matrix_path: Path, current_rows: tuple[dict[str, object], ...]
) -> list[dict[str, object]]:
    previous = json.loads(previous_matrix_path.read_text(encoding="utf-8"))
    previous_rows = previous.get("rows", [])
    current_by_id = {row["taskId"]: row for row in current_rows}
    records: list[dict[str, object]] = []
    for old in previous_rows:
        if old.get("classification") != "TASK_INPUT_CONTRACT_GAP":
            continue
        task_id = old["taskId"]
        current = current_by_id[task_id]
        contract_status = str(old.get("contractStatus", ""))
        if "requiredAuthorities_missing_for_java_operation" in contract_status:
            field = "requiredAuthorities"
            why_required = (
                "The old validator inferred requiredness from javaRequired alone. "
                "The input-side sidecar permits an empty requiredAuthorities declaration; "
                "category/strategy/typed reference require the Java boundary, not a non-empty "
                "authority override."
            )
            evidence_reason = (
                "requiredAuthorities is empty/optional in the sidecar; no semantic "
                "field requirement was proven."
            )
        elif "targetProjectId_not_present_in_task_input" in contract_status:
            field = "targetProjectId"
            semantic = current.get("semanticRequiredness", {}).get("targetProjectId", {})
            if semantic.get("required") and semantic.get("provided"):
                why_required = (
                    "Cross-project scope is semantically present, but the target is already "
                    "carried "
                    "by an input literal or typed resource; a duplicated task-root targetProjectId "
                    "is not required."
                )
                evidence_reason = (
                    "semantic target required=true and provided=true; no missing field remains."
                )
            else:
                why_required = (
                    "The current category/strategy/typed reference does not make a task-root "
                    "targetProjectId required. The sidecar target is an input-side execution "
                    "prerequisite, and no task-root duplication is required."
                )
                evidence_reason = (
                    "semantic target required=false; missing optional target is not a contract gap."
                )
        else:
            field = "<validator-field-unresolved>"
            why_required = (
                "The original validator did not record a recognized semantic requirement."
            )
            evidence_reason = "fail closed for reclassification review."

        typed_refs = [
            item.get("ref")
            for item in old.get("inputReferences", [])
            if item.get("kind") in {"JAVA_RESOURCE", "PYTHON_FIXTURE"}
        ]
        literal_inputs = {
            item.get("key"): item.get("value")
            for item in old.get("inputReferences", [])
            if item.get("kind") == "LITERAL" and item.get("key") != "taskFocus"
        }
        records.append(
            {
                "taskId": task_id,
                "category": old.get("category"),
                "executionStrategy": old.get("executionStrategy"),
                "fieldCurrentlyConsideredMissing": field,
                "whyFieldIsRequired": why_required,
                "inputEvidence": {
                    "inputReferenceType": old.get("inputReferenceType"),
                    "typedReferences": typed_refs,
                    "literalInputsExcludingTaskFocus": literal_inputs,
                    "currentProjectId": old.get("currentProjectId"),
                    "targetProjectIdFromSidecar": old.get("targetProjectId"),
                    "newSemanticRequiredness": current.get("semanticRequiredness"),
                    "reason": evidence_reason,
                },
                "reclassification": {
                    "previousClassification": "TASK_INPUT_CONTRACT_GAP",
                    "newClassification": current.get("classification"),
                    "newContractStatus": current.get("contractStatus"),
                    "newResourceStatus": current.get("resourceStatus"),
                    "newAuthStatus": current.get("authStatus"),
                    "rootCause": (
                        "Validator self-false-positive removed; any remaining classification comes "
                        "from an independent input-side mapping, recipe, runtime-resource or "
                        "auth check."
                    ),
                },
            }
        )
    if len(records) != 54:
        raise RuntimeError(f"expected to reclassify the original 54 rows, got {len(records)}")
    return records


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        type=Path,
        help="Explicit artifact directory; defaults to a UTC timestamped Stage 21 directory.",
    )
    parser.add_argument(
        "--previous-matrix",
        type=Path,
        help="Original matrix used for the required 54-row validator reclassification review.",
    )
    args = parser.parse_args()

    validator_self_tests = run_validator_self_tests()
    first = run_input_side_audit(
        manifest_path=MANIFEST_PATH,
        sidecar_path=SIDECAR_PATH,
        recipe_dir=RECIPE_DIR,
        repo_root=REPO_ROOT,
        probe_runtime=True,
    )
    second = run_input_side_audit(
        manifest_path=MANIFEST_PATH,
        sidecar_path=SIDECAR_PATH,
        recipe_dir=RECIPE_DIR,
        repo_root=REPO_ROOT,
        probe_runtime=True,
    )
    assert_result_invariants(first)
    assert_result_invariants(second)
    first_digest = result_digest(first)
    second_digest = result_digest(second)
    deterministic_passed = first_digest == second_digest

    metadata = dict(first.metadata)
    verification = dict(first.verification)
    verification["deterministicValidation"] = {
        "status": "PASS" if deterministic_passed else "FAIL",
        "repeatRuns": 2,
        "firstDigest": first_digest,
        "secondDigest": second_digest,
        "sameCanonicalProjection": deterministic_passed,
    }
    verification["validatorSelfTests"] = validator_self_tests
    metadata["deterministicValidation"] = "PASS" if deterministic_passed else "FAIL"
    metadata["status"] = (
        "STAGE21_ALL_105_INPUT_AUDIT_COMPLETE"
        if deterministic_passed
        else "STAGE21_ALL_105_INPUT_AUDIT_BLOCKED"
    )

    if args.output_dir is None:
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        output_dir = AGENTLAB_ROOT / "artifacts" / "stage21" / "input-side-audit-v3" / stamp
    else:
        output_dir = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=False)

    previous_matrix = args.previous_matrix or _find_original_54_matrix()
    if previous_matrix is None:
        raise RuntimeError("could not locate the original 54-row matrix for reclassification")
    reclassification = _reclassification_54(previous_matrix, first.rows)

    matrix = {"metadata": metadata, "rows": list(first.rows)}
    _write_json(output_dir / "input-side-audit-matrix.json", matrix)
    (output_dir / "input-side-audit-matrix.jsonl").write_text(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in first.rows),
        encoding="utf-8",
    )
    _write_json(output_dir / "input-side-audit-verification.json", verification)
    _write_json(
        output_dir / "input-only-projection-proof.json",
        {
            "status": "PASS" if deterministic_passed else "FAIL",
            "projection": verification["expectedSideProjectionProof"],
            "expectedSideLoadedCount": verification["expectedSideLoadedCount"],
            "skippedExpectedSideFieldNames": verification["expectedSideForbiddenKeysEncountered"],
        },
    )
    _write_json(
        output_dir / "run.json",
        {
            "status": metadata["status"],
            "auditMode": metadata["auditMode"],
            "datasetId": metadata["datasetId"],
            "datasetVersion": metadata["datasetVersion"],
            "taskCount": metadata["taskCount"],
            "splitCounts": metadata["splitCounts"],
            "classificationCounts": metadata["classificationCounts"],
            "nonReadyTaskIds": [
                row["taskId"] for row in first.rows if row["classification"] != "READY"
            ],
            "verification": verification,
            "validatorSelfTests": validator_self_tests,
            "artifactFiles": [
                "input-side-audit-matrix.json",
                "input-side-audit-matrix.jsonl",
                "input-side-audit-verification.json",
                "input-only-projection-proof.json",
                "input-side-audit-reclassification-54.json",
                "run.json",
            ],
        },
    )
    _write_json(
        output_dir / "input-side-audit-reclassification-54.json",
        {
            "schemaVersion": "stage21-input-side-audit-reclassification/v1",
            "sourceMatrix": str(previous_matrix.resolve()),
            "originalRowCount": 54,
            "rows": reclassification,
        },
    )

    print(
        json.dumps(
            {
                "status": metadata["status"],
                "artifactDir": str(output_dir.resolve()),
                "matrix": str((output_dir / "input-side-audit-matrix.json").resolve()),
                "taskCount": metadata["taskCount"],
                "splitCounts": metadata["splitCounts"],
                "classificationCounts": metadata["classificationCounts"],
                "nonReadyTaskIds": [
                    row["taskId"] for row in first.rows if row["classification"] != "READY"
                ],
                "expectedSideLoadedCount": verification["expectedSideLoadedCount"],
                "modelCallCount": verification["modelCallCount"],
                "fixtureFallbackCount": verification["fixtureFallbackCount"],
                "pythonBypassCount": verification["pythonBypassCount"],
                "deterministicValidation": verification["deterministicValidation"],
                "validatorSelfTests": validator_self_tests,
                "reclassification54": str(
                    (output_dir / "input-side-audit-reclassification-54.json").resolve()
                ),
                "reclassification54Count": len(reclassification),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if deterministic_passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
