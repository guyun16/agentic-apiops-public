package com.apiops.agent.generation;

public enum GenerationIntent {
    HAPPY_PATH("Generate one normal happy-path TestCase"),
    MISSING_REQUIRED("Generate one TestCase that omits one documented required request field"),
    BOUNDARY("Generate one TestCase that exercises a documented request boundary"),
    AUTH_FAILURE("Generate one TestCase that exercises the documented authentication failure path"),
    IDEMPOTENCY("Generate one TestCase that exercises the documented idempotency behavior"),
    BUSINESS_ERROR("Generate one TestCase that exercises one documented business-error response");

    private final String promptTask;

    GenerationIntent(String promptTask) {
        this.promptTask = promptTask;
    }

    String promptTask() {
        return promptTask;
    }
}
