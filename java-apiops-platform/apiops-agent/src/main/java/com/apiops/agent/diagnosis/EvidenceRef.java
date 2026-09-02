package com.apiops.agent.diagnosis;

import java.util.Objects;

/** Reference to one stable ContextPack item identity. */
public record EvidenceRef(String itemId) {

    public EvidenceRef {
        Objects.requireNonNull(itemId, "itemId must not be null");
        if (itemId.isBlank()) {
            throw new IllegalArgumentException("itemId must not be blank");
        }
    }
}
