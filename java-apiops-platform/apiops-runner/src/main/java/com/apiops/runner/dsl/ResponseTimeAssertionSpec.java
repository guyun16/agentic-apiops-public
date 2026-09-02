package com.apiops.runner.dsl;

import com.fasterxml.jackson.annotation.JsonIgnore;
import com.fasterxml.jackson.annotation.JsonInclude;
import com.fasterxml.jackson.annotation.JsonIgnoreProperties;

@JsonInclude(JsonInclude.Include.NON_NULL)
@JsonIgnoreProperties(ignoreUnknown = false)
public record ResponseTimeAssertionSpec(int maxMs) implements AssertionSpec {
    @Override
    @JsonIgnore
    public AssertionType type() {
        return AssertionType.RESPONSE_TIME;
    }
}
