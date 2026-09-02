package com.apiops.runner.dsl;

import com.fasterxml.jackson.annotation.JsonInclude;
import com.fasterxml.jackson.annotation.JsonIgnoreProperties;

import java.util.Map;
import java.util.Objects;

@JsonInclude(JsonInclude.Include.NON_NULL)
@JsonIgnoreProperties(ignoreUnknown = false)
public record EnvironmentSpec(
        String baseUrl,
        Map<String, VariableSpec> variables
) {
    public EnvironmentSpec {
        Objects.requireNonNull(baseUrl, "baseUrl must not be null");
        variables = Map.copyOf(Objects.requireNonNull(variables, "variables must not be null"));
    }
}
