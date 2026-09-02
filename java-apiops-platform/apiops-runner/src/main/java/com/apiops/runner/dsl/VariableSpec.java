package com.apiops.runner.dsl;

import com.fasterxml.jackson.annotation.JsonCreator;
import com.fasterxml.jackson.annotation.JsonValue;

import java.util.Objects;

/** A named environment variable value; substitution is outside Stage 7.2. */
public record VariableSpec(String value) {
    public VariableSpec {
        Objects.requireNonNull(value, "value must not be null");
    }

    @JsonCreator(mode = JsonCreator.Mode.DELEGATING)
    public static VariableSpec fromJson(String value) {
        return new VariableSpec(value);
    }

    @JsonValue
    public String toJson() {
        return value;
    }
}
