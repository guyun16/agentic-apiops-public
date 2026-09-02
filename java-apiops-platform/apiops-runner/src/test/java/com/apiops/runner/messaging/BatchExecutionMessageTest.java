package com.apiops.runner.messaging;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.json.JsonMapper;
import com.fasterxml.jackson.datatype.jsr310.JavaTimeModule;
import org.junit.jupiter.api.Test;

import java.time.Instant;
import java.util.UUID;

import static org.junit.jupiter.api.Assertions.assertEquals;

class BatchExecutionMessageTest {

    @Test
    void jsonRoundTripPreservesExecutionTriggerContract() throws Exception {
        ObjectMapper mapper = JsonMapper.builder()
                .addModule(new JavaTimeModule())
                .build();
        BatchExecutionMessage message = new BatchExecutionMessage(
                BatchExecutionMessage.CURRENT_VERSION,
                UUID.fromString("fd449cf0-e58a-43a7-a50a-a92245f2a812"),
                101L,
                UUID.fromString("806e287f-36bc-4e22-887a-dcba4a0153a7"),
                401L,
                "trace-stage9",
                Instant.parse("2026-08-11T12:00:00Z"));

        String json = mapper.writeValueAsString(message);

        assertEquals(message, mapper.readValue(json, BatchExecutionMessage.class));
        org.junit.jupiter.api.Assertions.assertFalse(json.contains("testCases"));
        org.junit.jupiter.api.Assertions.assertFalse(json.contains("testCaseDsl"));
        org.junit.jupiter.api.Assertions.assertFalse(json.contains("runId"));
    }
}
