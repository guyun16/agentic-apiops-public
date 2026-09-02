package com.apiops.agent.tool;

import com.apiops.runner.dsl.AssertionType;

import java.util.Arrays;

/** Pure in-memory Stage 11 tool for checking the existing Stage 7 assertion vocabulary. */
public final class AssertionTypeTool {

    public Result isAllowedAssertionType(Request request) {
        String type = request == null ? null : request.type();
        return new Result(type, isAllowedAssertionType(type));
    }

    public boolean isAllowedAssertionType(String type) {
        return type != null
                && Arrays.stream(AssertionType.values())
                        .anyMatch(allowed -> allowed.name().equals(type));
    }

    public record Request(String type) {
    }

    public record Result(String type, boolean allowed) {
    }
}
