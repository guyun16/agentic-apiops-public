"""Stage 19 tabular and Markdown reporting over existing evaluation facts."""

from .reporting import (
    MISSING_METRIC_STATE,
    ComparisonRun,
    ReportArtifacts,
    ReportMetadata,
    evaluation_results_to_dataframe,
    export_evaluation_csv,
    generate_report_bundle,
    read_evaluation_csv,
    render_ablation_report,
    render_evaluation_report,
)

__all__ = [
    "MISSING_METRIC_STATE",
    "ComparisonRun",
    "ReportArtifacts",
    "ReportMetadata",
    "evaluation_results_to_dataframe",
    "export_evaluation_csv",
    "generate_report_bundle",
    "read_evaluation_csv",
    "render_ablation_report",
    "render_evaluation_report",
]
