package com.apiops.runner.dsl;

import com.fasterxml.jackson.annotation.JsonIgnore;
import com.fasterxml.jackson.annotation.JsonInclude;
import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.fasterxml.jackson.databind.JsonNode;

import java.util.Objects;

@JsonInclude(JsonInclude.Include.NON_NULL)
@JsonIgnoreProperties(ignoreUnknown = false)
public record JsonPathAssertionSpec(
        String expression,
        JsonPathOperator operator,
        JsonNode expected
) implements AssertionSpec {
    public JsonPathAssertionSpec {
        Objects.requireNonNull(expression, "expression must not be null");
        Objects.requireNonNull(operator, "operator must not be null");
    }

    @Override
    @JsonIgnore
    public AssertionType type() {
        return AssertionType.JSON_PATH;
    }
}
