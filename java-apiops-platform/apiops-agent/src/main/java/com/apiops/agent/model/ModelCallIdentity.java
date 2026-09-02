package com.apiops.agent.model;

import java.util.Objects;

/** Identity returned by the provider for one actual model call. */
public record ModelCallIdentity(String modelCallId, String repairOfModelCallId) {

    public ModelCallIdentity {
        Objects.requireNonNull(modelCallId, "modelCallId must not be null");
        if (modelCallId.isBlank()) {
            throw new IllegalArgumentException("modelCallId must not be blank");
        }
        if (modelCallId.equals(repairOfModelCallId)) {
            throw new IllegalArgumentException("repair call cannot reference itself");
        }
    }
}
