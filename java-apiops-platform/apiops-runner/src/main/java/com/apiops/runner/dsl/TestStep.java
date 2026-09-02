package com.apiops.runner.dsl;

import com.fasterxml.jackson.annotation.JsonInclude;
import com.fasterxml.jackson.annotation.JsonIgnoreProperties;

import java.util.List;
import java.util.Objects;

@JsonInclude(JsonInclude.Include.NON_NULL)
@JsonIgnoreProperties(ignoreUnknown = false)
public record TestStep(
        String stepId,
        String name,
        RequestSpec request,
        List<AssertionSpec> assertions,
        List<ExtractorSpec> extractors
) {
    public TestStep {
        Objects.requireNonNull(stepId, "stepId must not be null");
        Objects.requireNonNull(name, "name must not be null");
        Objects.requireNonNull(request, "request must not be null");
        assertions = List.copyOf(Objects.requireNonNull(assertions, "assertions must not be null"));
        extractors = List.copyOf(Objects.requireNonNull(extractors, "extractors must not be null"));
    }
}
