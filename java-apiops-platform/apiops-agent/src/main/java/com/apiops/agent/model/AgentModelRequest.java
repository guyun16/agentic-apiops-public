package com.apiops.agent.model;

import java.util.Objects;

public record AgentModelRequest(
        String promptName,
        String promptVersion,
        String system,
        String user,
        String context
) {
    public AgentModelRequest {
        promptName = requireText(promptName, "promptName");
        promptVersion = requireText(promptVersion, "promptVersion");
        system = requireText(system, "system");
        user = requireText(user, "user");
        context = Objects.requireNonNull(context, "context must not be null");
    }

    private static String requireText(String value, String name) {
        Objects.requireNonNull(value, name + " must not be null");
        if (value.isBlank()) {
            throw new IllegalArgumentException(name + " must not be blank");
        }
        return value;
    }
}
