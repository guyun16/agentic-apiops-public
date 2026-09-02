package com.apiops.agent.record;

import org.junit.jupiter.api.Test;

import java.lang.reflect.RecordComponent;
import java.time.Instant;
import java.util.Arrays;
import java.util.Set;
import java.util.stream.Collectors;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;

class AgentRecordContractTest {

    @Test
    void modelCallFactExcludesSecretsPromptsOutputsAndContext() {
        Set<String> fields = Arrays.stream(ModelCallRecord.class.getRecordComponents())
                .map(RecordComponent::getName)
                .collect(Collectors.toSet());

        assertFalse(fields.stream().anyMatch(name -> Set.of(
                "apiKey", "authorization", "cookie", "password", "prompt",
                "promptContent", "output", "contextPack").contains(name)));

        Instant started = Instant.parse("2026-08-13T00:00:00Z");
        ModelCallRecord failure = new ModelCallRecord(
                "call-1", "agent-run-1", "step-1", 42L,
                "GENERATE_TEST_CASE", "configured-provider", "configured-model",
                "generate-testcase", "v1", started, started.plusMillis(10),
                10L, AgentCallStatus.FAILURE, ModelCallErrorType.PROVIDER_FAILURE,
                false, null);
        assertEquals(ModelCallErrorType.PROVIDER_FAILURE, failure.errorType());

        ModelCallRecord repair = new ModelCallRecord(
                "call-2", "agent-run-1", "step-1", 42L,
                "GENERATE_TEST_CASE", "configured-provider", "configured-model",
                "generate-testcase", "v1", started, started.plusMillis(12),
                12L, AgentCallStatus.SUCCESS, null, true, "call-1");
        assertEquals("generate-testcase", repair.promptName());
        assertEquals("v1", repair.promptVersion());
        assertEquals("call-1", repair.repairOfModelCallId());
    }

    @Test
    void agentStepUsesOnlyAgentTypesAndOptionalModelCallIdentity() {
        Instant started = Instant.parse("2026-08-13T00:00:00Z");
        AgentStepRecord step = new AgentStepRecord(
                "step-1", "agent-run-1", 42L, "MODEL_CALL",
                started, started.plusMillis(25), 25L,
                AgentStepStatus.SUCCESS, "model-call-1");

        assertEquals("model-call-1", step.modelCallId());
        assertEquals("com.apiops.agent.record.AgentStepStatus",
                step.status().getClass().getName());
    }
}
