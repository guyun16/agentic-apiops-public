package com.apiops.agent.diagnosis;

import com.apiops.agent.structured.StructuredOutputException;
import com.apiops.agent.structured.StructuredOutputFailureType;
import com.apiops.rag.context.ContextItem;
import com.apiops.rag.context.ContextPack;

import java.util.HashSet;
import java.util.Objects;
import java.util.Set;

/** Deterministically checks that every hypothesis cites an input ContextPack item. */
public final class DiagnosisCitationValidator {

    public void validate(DiagnosisReport report, ContextPack contextPack) {
        Objects.requireNonNull(report, "report");
        Objects.requireNonNull(contextPack, "contextPack");
        if (report.projectId() != contextPack.projectId()) {
            throw new StructuredOutputException(
                    StructuredOutputFailureType.CONTRACT_INVALID,
                    java.util.List.of("/projectId PROJECT_SCOPE_MISMATCH"));
        }
        Set<String> allowedItemIds = new HashSet<>();
        for (ContextItem item : contextPack.items()) {
            if (item.projectId() != contextPack.projectId()
                    || !allowedItemIds.add(item.itemId())) {
                throw new IllegalArgumentException(
                        "ContextPack contains an invalid or duplicate item identity");
            }
        }
        for (int hypothesisIndex = 0;
                hypothesisIndex < report.rootCauseHypotheses().size();
                hypothesisIndex++) {
            RootCauseHypothesis hypothesis = report.rootCauseHypotheses().get(hypothesisIndex);
            for (int refIndex = 0; refIndex < hypothesis.evidenceRefs().size(); refIndex++) {
                EvidenceRef ref = hypothesis.evidenceRefs().get(refIndex);
                if (!allowedItemIds.contains(ref.itemId())) {
                    throw new StructuredOutputException(
                            StructuredOutputFailureType.CONTRACT_INVALID,
                            java.util.List.of("/rootCauseHypotheses/" + hypothesisIndex
                                    + "/evidenceRefs/" + refIndex
                                    + " UNKNOWN_CONTEXT_ITEM_ID"));
                }
                ContextItem item = contextPack.items().stream()
                        .filter(value -> value.itemId().equals(ref.itemId()))
                        .findFirst().orElseThrow();
                if (item.projectId() != report.projectId()) {
                    throw new StructuredOutputException(
                            StructuredOutputFailureType.CONTRACT_INVALID,
                            java.util.List.of("/rootCauseHypotheses/" + hypothesisIndex
                                    + "/evidenceRefs/" + refIndex
                                    + " PROJECT_SCOPE_MISMATCH"));
                }
            }
        }
    }
}
