package com.apiops.agent.diagnosis;

import com.apiops.agent.structured.StructuredOutputException;
import org.junit.jupiter.api.Test;

import java.util.List;

import static com.apiops.agent.diagnosis.DiagnosisTestSupport.API_ID;
import static com.apiops.agent.diagnosis.DiagnosisTestSupport.PROJECT_ID;
import static com.apiops.agent.diagnosis.DiagnosisTestSupport.RUN_ID;
import static com.apiops.agent.diagnosis.DiagnosisTestSupport.mapper;
import static com.apiops.agent.diagnosis.DiagnosisTestSupport.packWithRag;
import static com.apiops.agent.diagnosis.DiagnosisTestSupport.validJson;
import static org.junit.jupiter.api.Assertions.assertDoesNotThrow;
import static org.junit.jupiter.api.Assertions.assertThrows;

class DiagnosisCitationValidatorTest {

    private final DiagnosisCitationValidator validator = new DiagnosisCitationValidator();

    @Test
    void acceptsIndependentHypothesisCitationsPresentInContextPack() {
        DiagnosisReport report = mapper().parse(validJson(
                true, Long.toString(PROJECT_ID), Long.toString(RUN_ID),
                "{\"itemId\":\"run:" + RUN_ID + "\"},{\"itemId\":\"chunk:chunk-1\"}"));
        assertDoesNotThrow(() -> validator.validate(report, packWithRag()));
    }

    @Test
    void rejectsFabricatedChunkAndMixedValidFabricatedReferences() {
        DiagnosisReport fabricated = mapper().parse(validJson(
                true, Long.toString(PROJECT_ID), Long.toString(RUN_ID),
                "{\"itemId\":\"chunk:not-in-pack\"}"));
        assertThrows(StructuredOutputException.class,
                () -> validator.validate(fabricated, packWithRag()));

        DiagnosisReport mixed = mapper().parse(validJson(
                true, Long.toString(PROJECT_ID), Long.toString(RUN_ID),
                "{\"itemId\":\"run:" + RUN_ID + "\"},{\"itemId\":\"source:fake\"}"));
        assertThrows(StructuredOutputException.class,
                () -> validator.validate(mixed, packWithRag()));
    }

    @Test
    void rejectsProjectScopeMismatch() {
        DiagnosisReport report = mapper().parse(validJson(
                true, "9999", Long.toString(RUN_ID),
                "{\"itemId\":\"run:" + RUN_ID + "\"}"));
        assertThrows(StructuredOutputException.class,
                () -> validator.validate(report, packWithRag()));
    }
}
