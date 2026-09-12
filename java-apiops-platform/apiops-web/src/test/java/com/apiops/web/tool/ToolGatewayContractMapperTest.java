package com.apiops.web.tool;

import com.apiops.common.enums.ToolStatus;
import com.apiops.common.tool.ToolResult;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.EnumSource;

import java.io.IOException;
import java.util.Arrays;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

class ToolGatewayContractMapperTest {

    private final ObjectMapper json = new ObjectMapper();
    private final ToolGatewayContractMapper mapper = new ToolGatewayContractMapper();

    @Test
    void canonicalRequestMapsParamsAndDottedNameToInternalIntent() throws Exception {
        ToolCallRequest request = json.readValue("""
                {
                  "schemaVersion":"0.2.0",
                  "agentRunId":"run-1",
                  "projectId":"42",
                  "toolName":"rag.search",
                  "params":{
                    "nested":{"enabled":true,"nullable":null},
                    "items":[1,2.5,false,null]
                  },
                  "traceId":"trace-contract-1"
                }
                """, ToolCallRequest.class);

        assertNull(mapper.validationError(request, 42L, "trace-contract-1"));
        assertEquals("rag.search", mapper.toInternalIntent(request, 42L).toolName());
        assertEquals(request.params(), mapper.toInternalIntent(request, 42L).arguments());
        JsonNode serialized = json.valueToTree(request);
        assertEquals("0.2.0", serialized.get("schemaVersion").asText());
        assertEquals("rag.search", serialized.get("toolName").asText());
        assertTrue(serialized.get("params").get("nested").get("enabled").asBoolean());
        assertNull(serialized.get("toolCallId"));
        assertNull(serialized.get("arguments"));
    }

    @Test
    void legacyNameAndProjectDriftFailCanonicalValidation() {
        ToolCallRequest legacy = request("RAG_SEARCH", "42");
        ToolCallRequest drifted = request("rag.search", "43");

        assertEquals("unknown canonical tool name",
                mapper.validationError(legacy, 42L, "trace-contract-1"));
        assertEquals("ToolCall projectId does not match the trusted path scope",
                mapper.validationError(drifted, 42L, "trace-contract-1"));
    }

    @Test
    void exactRedisLogicalAliasIsExpandedOnlyFromTrustedProjectScope() {
        ToolCallRequest logical = new ToolCallRequest(
                "0.2.0",
                "run-1",
                null,
                "42",
                "redis.read",
                Map.of("key", "runner:701"),
                "trace-contract-1",
                null);

        var normalized = mapper.toInternalIntent(logical, 42L);

        assertEquals("redis.read", normalized.toolName());
        assertEquals(Map.of(
                "command", "HGET",
                "keys", java.util.List.of("apiops:runner:progress:42:701"),
                "fields", java.util.List.of("status")), normalized.arguments());

        ToolCallRequest mixed = new ToolCallRequest(
                "0.2.0",
                "run-1",
                null,
                "42",
                "redis.read",
                Map.of("key", "runner:701", "command", "HGET"),
                "trace-contract-1",
                null);
        assertEquals(mixed.params(), mapper.toInternalIntent(mixed, 42L).arguments());
    }

    @Test
    void successSerializationMatchesFixtureConsumedByPython() throws IOException {
        ToolResult<Object> result = ToolResult.success(
                "rag.search",
                "java-generated-call-1",
                Map.of("value", "progress", "nested", Arrays.asList(true, 7, 1.5, null)));
        ToolResultResponse response = mapper.toPublicResult(result, "trace-contract-1");

        JsonNode actual = json.valueToTree(response);
        JsonNode expected = json.readTree(getClass().getResourceAsStream(
                "/contracts/tool-result-success.json"));
        assertEquals(expected, actual);
    }

    @Test
    void forbiddenSerializationMatchesFixtureConsumedByPython() throws IOException {
        ToolResult<Object> result = ToolResult.ofStatus(
                "rag.search",
                "java-generated-denied-1",
                ToolStatus.FORBIDDEN,
                null);
        ToolResultResponse response = mapper.toPublicResult(result, "trace-contract-1");

        JsonNode actual = json.valueToTree(response);
        JsonNode expected = json.readTree(getClass().getResourceAsStream(
                "/contracts/tool-result-forbidden.json"));
        assertEquals(expected, actual);
    }

    @ParameterizedTest
    @EnumSource(ToolStatus.class)
    void everyGatewayStatusMapsToCanonicalToolResult(ToolStatus status) {
        ToolResult<Object> result = ToolResult.ofStatus(
                "rag.search", "java-generated-status-id", status, null);

        ToolResultResponse response = mapper.toPublicResult(result, "trace-contract-1");

        assertEquals("0.1.0", response.schemaVersion());
        assertEquals("java-generated-status-id", response.toolCallId());
        assertEquals(status.name(), response.status());
        assertEquals(status == ToolStatus.SUCCESS, response.error() == null);
        assertTrue(response.sanitized());
        assertEquals("trace-contract-1", response.traceId());
    }

    @Test
    void resultLimitMarkerRemainsADataFactNotExecutionFailure() {
        ToolResult<Object> result = ToolResult.success(
                "rag.search",
                "java-generated-truncated-id",
                Map.of("_resultTruncated", true));

        ToolResultResponse response = mapper.toPublicResult(result, "trace-contract-1");

        assertEquals("SUCCESS", response.status());
        assertEquals(Map.of("_resultTruncated", true), response.data());
        assertNull(response.error());
    }

    private static ToolCallRequest request(String toolName, String projectId) {
        return new ToolCallRequest(
                "0.2.0",
                "run-1",
                null,
                projectId,
                toolName,
                Map.of("query", "order timeout", "topK", 2),
                "trace-contract-1",
                null);
    }
}
