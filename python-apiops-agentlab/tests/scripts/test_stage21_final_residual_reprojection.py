"""Offline composite must retain regressions and restrict changes to the two proven gaps."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))
import stage21_final_residual_reprojection as reprojection  # noqa: E402


def test_policy_reprojection_proves_only_zero_hit_status_changes() -> None:
    zeros = {key: "UNKNOWN" for key in reprojection.closure.ZERO_HIT_TASKS}
    old = {**{f"control-{i}": "PASS" for i in range(16)}, **zeros}
    confirmed = {key: "PASS" for key in zeros}
    proof = reprojection._validate_changes(old, old, zeros, confirmed)
    assert proof["other16StatusesUnchanged"] is True
    assert proof["zeroHitProjectionClosed"] is True
    assert proof["firstRunChangedTaskIds"] == []
    assert set(proof["confirmationChangedTaskIds"]) == set(zeros)
    with pytest.raises(reprojection.closure.ClosureFailure, match="CHANGED_NON_ZERO_HIT"):
        reprojection._validate_changes(old, {**old, "control-0": "FAIL"}, zeros, confirmed)


def test_composite_preserves_source_runs_and_pass_to_fail_regressions() -> None:
    comparison = reprojection._composite_comparison(
        {"a": "PASS", "b": "UNKNOWN", "c": "FAIL"},
        {"a": "FAIL", "b": "PASS", "c": "UNKNOWN"},
        {"a": "actual-first-run", "b": "actual-confirmation-run", "c": "actual-first-run"},
    )
    assert comparison["selectedUnique"] == 3
    assert comparison["oldUnknownToPass"] == 1
    assert comparison["oldFailToPass"] == 0
    assert comparison["targetedFail"] == 1
    assert comparison["targetedUnknown"] == 1
    assert comparison["transitionCounts"]["PASS->FAIL"] == 1
    assert {row["sourceEvaluationRunId"] for row in comparison["tasks"]} == {
        "actual-first-run", "actual-confirmation-run",
    }
