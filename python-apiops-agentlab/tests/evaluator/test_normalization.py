from __future__ import annotations

from app.evaluator import (
    ExpectedToolArguments,
    ParameterMatchPolicy,
    compare_parameters,
    exact_match,
)


def test_exact_match_ignores_json_object_key_order() -> None:
    assert exact_match({"query": "orders", "topK": 2}, {"topK": 2, "query": "orders"})


def test_exact_match_applies_only_allowed_normalization() -> None:
    assert exact_match("  READ_ONLY  ", "read_only", trim=True, case_insensitive=True)
    assert not exact_match("UPSTREAM_SCHEMA_DRIFT", "API_SCHEMA_DRIFT")
    assert not exact_match("2", 2)


def test_parameter_comparison_distinguishes_optional_missing_extra_and_mismatch() -> None:
    expectation = ExpectedToolArguments(
        tool_name="rag.search",
        arguments={"query": "orders", "topK": 2, "locale": "EN"},
        optional_fields=("locale",),
    )
    comparison = compare_parameters(
        expectation,
        {"topK": 3, "query": "orders", "unexpected": True},
    )

    assert comparison.matched_count == 1
    assert comparison.compared_count == 3
    assert comparison.missing_required == ()
    assert comparison.extra_fields == ("unexpected",)
    assert comparison.mismatched_fields == ("topK",)
    assert comparison.score == 1 / 3


def test_parameter_comparison_counts_missing_required_but_not_optional() -> None:
    expectation = ExpectedToolArguments(
        tool_name="rag.search",
        arguments={"query": "orders", "topK": 2, "locale": "en"},
        optional_fields=("locale",),
    )
    comparison = compare_parameters(expectation, {"query": "orders"})

    assert comparison.missing_required == ("topK",)
    assert comparison.compared_count == 2
    assert comparison.matched_count == 1


def test_parameter_normalization_is_per_field_and_explicit() -> None:
    expectation = ExpectedToolArguments(
        tool_name="rag.search",
        arguments={"mode": " read_only ", "ids": ["b", "a"]},
        trim_fields=("mode",),
        case_insensitive_fields=("mode",),
        order_insensitive_fields=("ids",),
    )
    comparison = compare_parameters(
        expectation,
        {"mode": "READ_ONLY", "ids": ["a", "b"]},
    )

    assert comparison.score == 1.0


def test_collection_order_remains_semantic_without_contract_permission() -> None:
    expected = ExpectedToolArguments(
        tool_name="runner.execute",
        arguments={"steps": ["first", "second"]},
    )

    assert compare_parameters(expected, {"steps": ["second", "first"]}).score == 0.0


def test_explicit_subset_policy_accepts_expected_fields_with_actual_extras() -> None:
    expected = ExpectedToolArguments(
        tool_name="rag.search",
        arguments={"query": "orders"},
        match_policy=ParameterMatchPolicy.SUBSET,
    )
    comparison = compare_parameters(expected, {"query": "orders", "topK": 5})

    assert comparison.score == 1.0
    assert comparison.compared_count == 1
    assert comparison.extra_fields == ("topK",)


def test_subset_policy_still_rejects_different_expected_field_value() -> None:
    expected = ExpectedToolArguments(
        tool_name="rag.search",
        arguments={"query": "orders"},
        match_policy=ParameterMatchPolicy.SUBSET,
    )
    comparison = compare_parameters(expected, {"query": "customers", "topK": 5})

    assert comparison.score == 0.0
    assert comparison.mismatched_fields == ("query",)


def test_default_exact_policy_still_penalizes_extra_fields() -> None:
    expected = ExpectedToolArguments(
        tool_name="rag.search",
        arguments={"query": "orders"},
    )
    comparison = compare_parameters(expected, {"query": "orders", "topK": 5})

    assert expected.match_policy is ParameterMatchPolicy.EXACT
    assert comparison.score == 0.5
    assert comparison.extra_fields == ("topK",)
