from __future__ import annotations

from pathlib import Path

import pandas as pd

from app.evaluator import MetricName
from app.reports import (
    MISSING_METRIC_STATE,
    evaluation_results_to_dataframe,
    export_evaluation_csv,
    generate_report_bundle,
    read_evaluation_csv,
    render_ablation_report,
    render_evaluation_report,
)
from tests.reports.fixtures import (
    FIXED_LIMITATIONS,
    SELECTED_COMPARISON_METRICS,
    fixed_judge_results,
    fixed_metadata,
    fixed_runs,
)


def test_dataframe_is_case_level_and_preserves_state_separately_from_value() -> None:
    _, run_b = fixed_runs()

    frame = evaluation_results_to_dataframe(run_b.results)

    assert list(frame["case_id"]) == ["case-1", "case-2", "case-3"]
    assert frame.loc[1, "contract_accepted__state"] == "VALUE"
    assert frame.loc[1, "contract_accepted__value"] == 0
    assert frame.loc[0, "total_tokens__state"] == "UNKNOWN"
    assert pd.isna(frame.loc[0, "total_tokens__value"])
    assert frame.loc[2, "total_tokens__state"] == MISSING_METRIC_STATE
    assert pd.isna(frame.loc[2, "total_tokens__value"])
    assert frame.loc[2, "diagnosis_accuracy__state"] == "NOT_APPLICABLE"
    assert pd.isna(frame.loc[2, "diagnosis_accuracy__value"])


def test_csv_export_and_readback_preserve_identity_state_and_nullable_values(
    tmp_path: Path,
) -> None:
    _, run_b = fixed_runs()
    path = export_evaluation_csv(run_b.results, tmp_path / "evaluation_result.csv")

    restored = read_evaluation_csv(path)

    assert list(restored["evaluation_id"]) == [
        "evaluation-b-1",
        "evaluation-b-2",
        "evaluation-b-3",
    ]
    assert restored.loc[0, "trace_id"] == "trace-b-1"
    assert restored.loc[0, "agent_run_id"] == "agent-run-b-1"
    assert restored.loc[0, "total_tokens__state"] == "UNKNOWN"
    assert restored.loc[2, "total_tokens__state"] == "MISSING"
    assert pd.isna(restored.loc[0, "total_tokens__value"])
    assert pd.isna(restored.loc[2, "cost__value"])


def test_evaluation_report_uses_existing_aggregation_and_contains_required_sections() -> None:
    _, run_b = fixed_runs()

    report = render_evaluation_report(
        run_b.results,
        fixed_metadata(),
        judge_results=fixed_judge_results(),
        limitations=FIXED_LIMITATIONS,
    )

    assert "## Evaluation setup" in report
    assert "## Sample counts and denominator context" in report
    assert "## Metric definitions" in report
    assert "## Results" in report
    assert "## Failure cases" in report
    assert "## Cost and latency" in report
    assert "## Safety observations" in report
    assert "## Reproducibility metadata" in report
    assert "| diagnosis_accuracy | 3 | 2 | 2 | 1 | 0 | 0 | 0 |" in report
    assert "| case-2 | contract_accepted | VALUE | the existing Validator rejected" in report
    assert "| total_tokens | UNKNOWN | 0 | 2 | 1 |" in report
    assert "diagnosis-semantic-quality@v1" in report
    assert "fake-provider/deterministic-judge@fixture-v1" in report


def test_minimal_comparison_uses_matched_cases_and_never_claims_causality() -> None:
    run_a, run_b = fixed_runs()

    report = render_ablation_report(run_a, run_b, SELECTED_COMPARISON_METRICS)

    assert "Matched case count: 3" in report
    assert "| diagnosis_accuracy | 0.5 | 1 | 0.5 | 2 | 2 |" in report
    assert "| total_tokens | UNKNOWN | UNKNOWN | UNKNOWN | 0 | 0 |" in report
    assert "does not claim that a configuration difference caused" in report
    assert "not evidence of causal improvement" in report


def test_report_bundle_writes_and_reads_all_artifacts(tmp_path: Path) -> None:
    run_a, run_b = fixed_runs()

    artifacts = generate_report_bundle(
        tmp_path,
        primary_run=run_b,
        comparison_run=run_a,
        metadata=fixed_metadata(),
        selected_metrics=SELECTED_COMPARISON_METRICS,
        judge_results=fixed_judge_results(),
        limitations=FIXED_LIMITATIONS,
    )

    restored = read_evaluation_csv(artifacts.evaluation_csv)
    assert len(restored) == 3
    assert artifacts.evaluation_report.read_text(encoding="utf-8").startswith(
        "# Evaluation Report: Run B"
    )
    assert "# Minimal Run A / Run B Comparison" in artifacts.ablation_report.read_text(
        encoding="utf-8"
    )


def test_checked_in_fixed_artifacts_match_deterministic_generation(tmp_path: Path) -> None:
    run_a, run_b = fixed_runs()
    generated = generate_report_bundle(
        tmp_path,
        primary_run=run_b,
        comparison_run=run_a,
        metadata=fixed_metadata(),
        selected_metrics=SELECTED_COMPARISON_METRICS,
        judge_results=fixed_judge_results(),
        limitations=FIXED_LIMITATIONS,
    )
    artifact_dir = Path(__file__).parents[2] / "app" / "reports" / "artifacts"

    expected_paths = {
        "evaluation_result.csv": generated.evaluation_csv,
        "evaluation_report.md": generated.evaluation_report,
        "ablation_report.md": generated.ablation_report,
    }
    for name, generated_path in expected_paths.items():
        checked_in = artifact_dir / name
        assert checked_in.read_bytes() == generated_path.read_bytes()

    restored = read_evaluation_csv(artifact_dir / "evaluation_result.csv")
    assert restored.loc[2, f"{MetricName.TOTAL_TOKENS.value}__state"] == "MISSING"
