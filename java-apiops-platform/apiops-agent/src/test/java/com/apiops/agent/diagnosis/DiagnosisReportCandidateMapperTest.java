package com.apiops.agent.diagnosis;

import com.apiops.agent.structured.StructuredOutputException;
import org.junit.jupiter.api.Test;

import static com.apiops.agent.diagnosis.DiagnosisTestSupport.PROJECT_ID;
import static com.apiops.agent.diagnosis.DiagnosisTestSupport.RUN_ID;
import static com.apiops.agent.diagnosis.DiagnosisTestSupport.mapper;
import static com.apiops.agent.diagnosis.DiagnosisTestSupport.validJson;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

class DiagnosisReportCandidateMapperTest {

    @Test
    void mapsValidReportHypothesesAndEvidenceRefs() {
        DiagnosisReport report = mapper().parse(validJson(
                true, Long.toString(PROJECT_ID), Long.toString(RUN_ID),
                "{\"itemId\":\"run:" + RUN_ID + "\"}"));

        assertEquals(PROJECT_ID, report.projectId());
        assertEquals(RUN_ID, report.runId());
        assertEquals(1, report.rootCauseHypotheses().size());
        assertEquals("MEDIUM", report.rootCauseHypotheses().getFirst().confidence().name());
        assertEquals("run:" + RUN_ID,
                report.rootCauseHypotheses().getFirst().evidenceRefs().getFirst().itemId());
    }

    @Test
    void acceptsLegitimateInsufficientEvidence() {
        DiagnosisReport report = mapper().parse(DiagnosisTestSupport.insufficientJson());
        assertFalse(report.sufficientEvidence());
        assertTrue(report.rootCauseHypotheses().isEmpty());
        assertFalse(report.limitations().isEmpty());
        assertFalse(report.recommendedChecks().isEmpty());
    }

    @Test
    void rejectsMissingRequiredFieldInvalidConfidenceAndUnknownField() {
        String valid = validJson(true, Long.toString(PROJECT_ID), Long.toString(RUN_ID),
                "{\"itemId\":\"run:" + RUN_ID + "\"}");
        assertThrows(StructuredOutputException.class,
                () -> mapper().parse(valid.replace("\"summary\":\"Evidence summary\",", "")));
        assertThrows(StructuredOutputException.class,
                () -> mapper().parse(valid.replace("\"MEDIUM\"", "\"CERTAIN\"")));
        assertThrows(StructuredOutputException.class,
                () -> mapper().parse(valid.replace("\"traceId\":\"trace-1\"", "\"extra\":true,\"traceId\":\"trace-1\"")));
        assertThrows(StructuredOutputException.class,
                () -> mapper().parse(valid.replace(
                        "\"evidenceRefs\":[{\"itemId\":\"run:" + RUN_ID + "\"}]",
                        "\"evidenceRefs\":[]")));
    }
}
