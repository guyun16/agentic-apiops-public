"""Regression checks for the Stage21 v4 freeze and anti-overfit audit."""

from __future__ import annotations

import sys
from pathlib import Path
from runpy import run_path

import pytest

from app.evaluator import evaluator

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts/stage21_v4_final_freeze_audit.py"


def _module() -> dict[str, object]:
    script_dir = str(_SCRIPT.parent)
    if script_dir not in sys.path:
        sys.path.insert(0, script_dir)
    return run_path(str(_SCRIPT))


def test_current_decision_sources_have_no_identity_to_outcome_shortcuts() -> None:
    module = _module()
    findings = [
        finding
        for source in module["DECISION_SOURCES"]
        for finding in module["_outcome_specific_shortcuts"](source)
    ]

    assert findings == []


def test_identity_specific_rules_are_authority_bounded() -> None:
    module = _module()
    audit = module["_task_specific_rule_audit"]()

    assert audit["status"] == "PASS"
    assert audit["ruleGroupCount"] == 4
    assert audit["identityBindingCount"] == 19
    assert all(row["directOutcome"] is False for row in audit["rules"])


def test_final_rag_authority_registration_rejects_widened_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(
        evaluator._ACCEPTED_EVIDENCE_SOURCE_AUTHORITY,
        ("gt_stage21_formal_rag_near_match_exact", "v1"),
        (("rag:orders-unique-index",), ("stage21-rag-v2/project-42/orders-constraint-index",)),
    )
    audit = _module()["_task_specific_rule_audit"]()
    assert audit["status"] == "FAIL"
    assert audit["rules"][0]["status"] == "FAIL"


def test_residual_13_regression_remains_fully_closed() -> None:
    module = _module()
    result = module["_residual_13_regression"]()

    assert result["status"] == "PASS"
    assert result["taskCount"] == 13
    assert result["statusCounts"] == {"PASS": 13, "FAIL": 0, "UNKNOWN": 0}


def test_gt_and_evaluator_contain_no_residual_model_provenance() -> None:
    module = _module()
    result = module["_gt_model_output_leakage"]()

    assert result["status"] == "PASS"
    assert result["findingCount"] == 0
