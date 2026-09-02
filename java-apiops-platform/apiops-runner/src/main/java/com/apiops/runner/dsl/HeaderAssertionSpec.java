package com.apiops.runner.dsl;

import com.fasterxml.jackson.annotation.JsonIgnore;
import com.fasterxml.jackson.annotation.JsonInclude;
import com.fasterxml.jackson.annotation.JsonIgnoreProperties;

import java.util.Objects;

@JsonInclude(JsonInclude.Include.NON_NULL)
@JsonIgnoreProperties(ignoreUnknown = false)
public record HeaderAssertionSpec(
        String name,
        HeaderOperator operator,
        String expected
) implements AssertionSpec {
    public HeaderAssertionSpec {
        Objects.requireNonNull(name, "name must not be null");
        Objects.requireNonNull(operator, "operator must not be null");
        Objects.requireNonNull(expected, "expected must not be null");
    }

    @Override
    @JsonIgnore
    public AssertionType type() {
        return AssertionType.HEADER;
    }
}
