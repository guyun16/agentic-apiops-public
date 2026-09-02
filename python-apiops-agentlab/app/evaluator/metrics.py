"""Aggregation of already-computed deterministic EvaluationResults."""

from __future__ import annotations

from collections.abc import Sequence
from statistics import fmean

from .models import (
    AggregatedMetric,
    AggregatedMetrics,
    EvaluationResult,
    MetricName,
    MetricStatus,
)

_RATE_METRICS = {
    MetricName.VALID_JSON,
    MetricName.SCHEMA_VALID,
    MetricName.CONTRACT_ACCEPTED,
    MetricName.EXACT_MATCH,
    MetricName.TOOL_PRECISION,
    MetricName.TOOL_RECALL,
    MetricName.TOOL_EXACT_SET_MATCH,
    MetricName.PARAMETER_ACCURACY,
    MetricName.EVIDENCE_HIT,
    MetricName.DIAGNOSIS_ACCURACY,
    MetricName.SAFETY_ACCURACY,
}


class MetricsCalculator:
    """Aggregate MetricResults without re-reading Trace or rejudging a case."""

    def calculate(self, results: Sequence[EvaluationResult]) -> AggregatedMetrics:
        if not results:
            return AggregatedMetrics(evaluator_version=None, case_count=0, metrics=())
        versions = {result.evaluator_version for result in results}
        if len(versions) != 1:
            raise ValueError("cannot aggregate mixed evaluator versions")

        aggregated: list[AggregatedMetric] = []
        for metric in MetricName:
            samples = [
                sample for result in results for sample in result.metrics if sample.metric is metric
            ]
            if not samples:
                continue
            values = [
                float(sample.value) for sample in samples if sample.status is MetricStatus.VALUE
            ]
            not_applicable = sum(sample.status is MetricStatus.NOT_APPLICABLE for sample in samples)
            unknown = sum(sample.status is MetricStatus.UNKNOWN for sample in samples)
            errors = sum(sample.status is MetricStatus.ERROR for sample in samples)
            units = {
                sample.unit
                for sample in samples
                if sample.status is MetricStatus.VALUE and sample.unit is not None
            }
            if len(units) > 1:
                raise ValueError(f"cannot aggregate mixed units for metric {metric.value}")
            mean = fmean(values) if values else None
            aggregated.append(
                AggregatedMetric(
                    metric=metric,
                    total_count=len(samples),
                    applicable_count=len(samples) - not_applicable,
                    value_count=len(values),
                    not_applicable_count=not_applicable,
                    unknown_count=unknown,
                    error_count=errors,
                    unit=next(iter(units)) if units else None,
                    mean=mean,
                    rate=mean if metric in _RATE_METRICS else None,
                )
            )
        return AggregatedMetrics(
            evaluator_version=next(iter(versions)),
            case_count=len(results),
            metrics=tuple(aggregated),
        )


__all__ = ["MetricsCalculator"]
