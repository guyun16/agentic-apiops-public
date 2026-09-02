package com.apiops.web.agent.controller;

import com.apiops.agent.generation.GenerationIntent;
import com.fasterxml.jackson.annotation.JsonIgnoreProperties;

/** Request contract shared by the Java and Python generator entry points. */
@JsonIgnoreProperties(ignoreUnknown = false)
public record GenerateTestCaseRequest(
        GenerationIntent strategy
) {

    public GenerateTestCaseRequest {
        strategy = strategy == null ? GenerationIntent.HAPPY_PATH : strategy;
    }

    public static GenerateTestCaseRequest defaults() {
        return new GenerateTestCaseRequest(GenerationIntent.HAPPY_PATH);
    }
}
