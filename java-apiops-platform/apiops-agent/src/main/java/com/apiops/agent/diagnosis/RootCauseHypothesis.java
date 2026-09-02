package com.apiops.agent.diagnosis;

import java.util.List;
import java.util.Objects;

public record RootCauseHypothesis(
        String statement,
        Confidence confidence,
        List<EvidenceRef> evidenceRefs
) {

    public RootCauseHypothesis {
        statement = requireText(statement, "statement");
        Objects.requireNonNull(confidence, "confidence must not be null");
        evidenceRefs = List.copyOf(Objects.requireNonNull(
                evidenceRefs, "evidenceRefs must not be null"));
        if (evidenceRefs.isEmpty()) {
            throw new IllegalArgumentException("evidenceRefs must not be empty");
        }
    }

    private static String requireText(String value, String field) {
        Objects.requireNonNull(value, field + " must not be null");
        if (value.isBlank()) {
            throw new IllegalArgumentException(field + " must not be blank");
        }
        return value;
    }
}
