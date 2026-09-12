from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from app.input_side_audit import (
    assert_result_invariants,
    run_input_side_audit,
    run_validator_self_tests,
)

AGENTLAB_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = AGENTLAB_ROOT.parent
FIXTURE_ROOT = AGENTLAB_ROOT / "tests" / "benchmark" / "fixtures"


def test_requiredness_self_tests_are_deterministic() -> None:
    first = run_validator_self_tests()
    second = run_validator_self_tests()
    assert first == second
    assert all(value == "PASS" for value in first.values())


def test_optional_null_field_does_not_create_gap() -> None:
    assert run_validator_self_tests()["optionalNullField"] == "PASS"


def test_required_field_missing_creates_gap() -> None:
    assert run_validator_self_tests()["requiredFieldMissing"] == "PASS"


def test_category_and_strategy_change_requiredness() -> None:
    assert run_validator_self_tests()["categoryStrategySensitiveRequiredness"] == "PASS"


def test_expected_side_changes_do_not_change_requiredness() -> None:
    assert run_validator_self_tests()["expectedSideInvariant"] == "PASS"


def test_task_id_rename_does_not_change_requiredness() -> None:
    assert run_validator_self_tests()["taskIdInvariant"] == "PASS"


def test_unknown_typed_contract_fails_closed() -> None:
    assert run_validator_self_tests()["unknownTypedContractFailClosed"] == "PASS"


def test_v3_projection_audits_all_105_without_expected_side() -> None:
    result = run_input_side_audit(
        manifest_path=FIXTURE_ROOT / "dataset-manifest.json",
        sidecar_path=FIXTURE_ROOT / "stage21-execution-prerequisites.json",
        recipe_dir=FIXTURE_ROOT / "support",
        repo_root=REPO_ROOT,
        probe_runtime=False,
    )
    assert_result_invariants(result)
    assert result.verification["expectedSideLoadedCount"] == 0
    assert result.verification["modelCallCount"] == 0
    assert result.verification["fixtureFallbackCount"] == 0
    assert result.verification["pythonBypassCount"] == 0


def test_audit_module_imports_no_benchmark_expected_side_modules() -> None:
    environment = dict(os.environ)
    environment["PYTHONPATH"] = str(AGENTLAB_ROOT)
    probe = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import sys; import app.input_side_audit; "
                "print(' '.join(str(name in sys.modules) for name in "
                "('app.evaluator','app.benchmark.dataset','app.benchmark.models')) )"
            ),
        ],
        cwd=AGENTLAB_ROOT,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )
    assert probe.stdout.strip() == "False False False"
