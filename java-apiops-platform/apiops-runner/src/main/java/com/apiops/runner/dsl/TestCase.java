package com.apiops.runner.dsl;

import com.fasterxml.jackson.annotation.JsonInclude;
import com.fasterxml.jackson.annotation.JsonIgnoreProperties;

import java.util.List;
import java.util.Objects;

@JsonInclude(JsonInclude.Include.NON_NULL)
@JsonIgnoreProperties(ignoreUnknown = false)
public record TestCase(
        String schemaVersion,
        String caseId,
        long projectId,
        String apiId,
        String name,
        EnvironmentSpec environment,
        String description,
        List<String> tags,
        List<TestStep> steps
) {
    public TestCase {
        Objects.requireNonNull(schemaVersion, "schemaVersion must not be null");
        Objects.requireNonNull(caseId, "caseId must not be null");
        Objects.requireNonNull(apiId, "apiId must not be null");
        Objects.requireNonNull(name, "name must not be null");
        Objects.requireNonNull(environment, "environment must not be null");
        steps = List.copyOf(Objects.requireNonNull(steps, "steps must not be null"));
        tags = tags == null ? null : List.copyOf(tags);
    }
}
