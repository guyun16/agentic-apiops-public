package com.apiops.agent.diagnosis;

import com.apiops.agent.model.AgentModelException;
import com.apiops.agent.structured.StructuredOutputException;
import org.junit.jupiter.api.Test;

import static com.apiops.agent.diagnosis.DiagnosisTestSupport.PROJECT_ID;
import static com.apiops.agent.diagnosis.DiagnosisTestSupport.RUN_ID;
import static com.apiops.agent.diagnosis.DiagnosisTestSupport.agent;
import static com.apiops.agent.diagnosis.DiagnosisTestSupport.injectionPack;
import static com.apiops.agent.diagnosis.DiagnosisTestSupport.insufficientJson;
import static com.apiops.agent.diagnosis.DiagnosisTestSupport.maskedPack;
import static com.apiops.agent.diagnosis.DiagnosisTestSupport.packWithRag;
import static com.apiops.agent.diagnosis.DiagnosisTestSupport.validJson;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

class DiagnosisAgentTest {

    @Test
    void keepsPromptInjectionInContextDataAndNotSystemInstruction() {
        var client = new DiagnosisTestSupport.SequenceClient(
                validJson(true, Long.toString(PROJECT_ID), Long.toString(RUN_ID),
                        "{\"itemId\":\"chunk:malicious\"}"));

        DiagnosisAgentResult result = agent(client).generate(
                PROJECT_ID, RUN_ID, injectionPack(), "Explain the failed run");

        assertEquals(1, client.requests.size());
        assertTrue(client.requests.getFirst().context().contains("ignore previous instructions"));
        assertFalse(client.requests.getFirst().system().contains("ignore previous instructions"));
        assertTrue(client.requests.getFirst().system().contains("Do not query"));
        assertEquals("diagnosis", result.promptName());
        assertEquals("v1", result.promptVersion());
        assertEquals(1, result.modelCallCount());
    }

    @Test
    void preservesStage10SecretMaskingAcrossDiagnosisPromptAssembly() {
        var client = new DiagnosisTestSupport.SequenceClient(insufficientJson());
        agent(client).generate(PROJECT_ID, RUN_ID, maskedPack(), "Explain the failed run");

        String context = client.requests.getFirst().context();
        assertFalse(context.contains("bearer-token"));
        assertFalse(context.contains("db-password"));
        assertTrue(context.contains("[REDACTED]"));
    }

    @Test
    void insufficientEvidenceIsAcceptedWithoutRepair() {
        var client = new DiagnosisTestSupport.SequenceClient(insufficientJson());
        DiagnosisAgentResult result = agent(client).generate(
                PROJECT_ID, RUN_ID, DiagnosisTestSupport.zeroRagPack(), "Explain with available facts");

        assertFalse(result.candidate().sufficientEvidence());
        assertTrue(result.candidate().rootCauseHypotheses().isEmpty());
        assertEquals(1, result.modelCallCount());
    }

    @Test
    void invalidStructuredOutputRepairsOnceAndStillValidates() {
        var client = new DiagnosisTestSupport.SequenceClient(
                "{invalid", validJson(true, Long.toString(PROJECT_ID), Long.toString(RUN_ID),
                        "{\"itemId\":\"run:" + RUN_ID + "\"}"));
        DiagnosisAgentResult result = agent(client).generate(
                PROJECT_ID, RUN_ID, packWithRag(), "Explain the failed run");

        assertEquals(2, result.modelCallCount());
        assertEquals("diagnosis-call-1", result.modelCalls().getFirst().modelCallId());
        assertEquals("diagnosis-call-2", result.modelCalls().getLast().modelCallId());
        assertEquals("diagnosis-call-1", result.modelCalls().getLast().repairOfModelCallId());
    }

    @Test
    void secondInvalidCandidateFailsAndNeverCallsThirdTime() {
        var client = new DiagnosisTestSupport.SequenceClient("{invalid", "{still-invalid");
        assertThrows(StructuredOutputException.class,
                () -> agent(client).generate(
                        PROJECT_ID, RUN_ID, packWithRag(), "Explain the failed run"));
        assertEquals(2, client.requests.size());
    }

    @Test
    void providerFailureIsNotAValidationFailure() {
        var client = new DiagnosisTestSupport.SequenceClient(
                new AgentModelException("Model provider call failed"));
        assertThrows(AgentModelException.class,
                () -> agent(client).generate(
                        PROJECT_ID, RUN_ID, packWithRag(), "Explain the failed run"));
        assertEquals(1, client.requests.size());
    }
}
