package com.apiops.runner.dsl;

import com.fasterxml.jackson.annotation.JsonInclude;
import com.fasterxml.jackson.annotation.JsonIgnoreProperties;

import java.util.Objects;

@JsonInclude(JsonInclude.Include.NON_NULL)
@JsonIgnoreProperties(ignoreUnknown = false)
public record ExtractorSpec(
        String name,
        String expression
) {
    public ExtractorSpec {
        Objects.requireNonNull(name, "name must not be null");
        Objects.requireNonNull(expression, "expression must not be null");
    }
}
