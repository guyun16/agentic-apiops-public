package com.apiops.agent.model;

import java.util.Objects;

/** Provider response identity plus candidate output; consumers must validate the content. */
public record AgentModelResponse(String modelCallId, String content) {

    public AgentModelResponse {
        Objects.requireNonNull(modelCallId, "modelCallId must not be null");
        if (modelCallId.isBlank()) {
            throw new IllegalArgumentException("modelCallId must not be blank");
        }
        Objects.requireNonNull(content, "content must not be null");
    }
}
