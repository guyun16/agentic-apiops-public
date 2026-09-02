"""Central, conservative normalization for deterministic evaluation."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from app.tracing import canonical_json

from .models import ExpectedToolArguments, ParameterMatchPolicy


def _normalize_scalar(value: object, *, case_insensitive: bool, trim: bool) -> object:
    if not isinstance(value, str):
        return value
    normalized = value.strip() if trim else value
    return normalized.casefold() if case_insensitive else normalized


def _normalize_value(value: object, *, case_insensitive: bool, trim: bool) -> object:
    if isinstance(value, Mapping):
        return {
            str(key): _normalize_value(item, case_insensitive=case_insensitive, trim=trim)
            for key, item in value.items()
        }
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray, str)):
        return [
            _normalize_value(item, case_insensitive=case_insensitive, trim=trim) for item in value
        ]
    return _normalize_scalar(value, case_insensitive=case_insensitive, trim=trim)


def exact_match(
    expected: object,
    actual: object,
    *,
    case_insensitive: bool = False,
    trim: bool = False,
    order_insensitive: bool = False,
) -> bool:
    """Compare frozen semantics, applying only explicitly allowed normalization."""

    expected_normalized = _normalize_value(
        expected,
        case_insensitive=case_insensitive,
        trim=trim,
    )
    actual_normalized = _normalize_value(
        actual,
        case_insensitive=case_insensitive,
        trim=trim,
    )
    if order_insensitive:
        if not (isinstance(expected_normalized, list) and isinstance(actual_normalized, list)):
            return False
        return Counter(map(canonical_json, expected_normalized)) == Counter(
            map(canonical_json, actual_normalized)
        )
    return expected_normalized == actual_normalized


@dataclass(frozen=True)
class ParameterComparison:
    matched_count: int
    compared_count: int
    missing_required: tuple[str, ...]
    extra_fields: tuple[str, ...]
    mismatched_fields: tuple[str, ...]

    @property
    def score(self) -> float | None:
        if self.compared_count == 0:
            return None
        return self.matched_count / self.compared_count


def compare_parameters(
    expected: ExpectedToolArguments,
    actual: Mapping[str, object],
) -> ParameterComparison:
    """Compare one Tool argument object without repairing either side."""

    expected_fields = set(expected.arguments)
    optional_fields = set(expected.optional_fields)
    required_fields = expected_fields - optional_fields
    actual_fields = set(actual)
    missing_required = tuple(sorted(required_fields - actual_fields))
    extra_fields = tuple(sorted(actual_fields - expected_fields))
    mismatched: list[str] = []
    matched = 0

    fields_to_compare = sorted(expected_fields & actual_fields)
    for field in fields_to_compare:
        if exact_match(
            expected.arguments[field],
            actual[field],
            case_insensitive=field in expected.case_insensitive_fields,
            trim=field in expected.trim_fields,
            order_insensitive=field in expected.order_insensitive_fields,
        ):
            matched += 1
        else:
            mismatched.append(field)

    compared = len(fields_to_compare) + len(missing_required)
    if expected.match_policy is ParameterMatchPolicy.EXACT:
        compared += len(extra_fields)
    return ParameterComparison(
        matched_count=matched,
        compared_count=compared,
        missing_required=missing_required,
        extra_fields=extra_fields,
        mismatched_fields=tuple(mismatched),
    )


__all__ = ["ParameterComparison", "compare_parameters", "exact_match"]
