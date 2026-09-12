package com.apiops.web.auth;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;

class Stage21MetadataAuthorityContractTest {
    private final ObjectMapper mapper = new ObjectMapper();

    @Test
    void inventoryBoundaryPreservesRequestSchemaAndRejectsDrift() throws Exception {
        String source = "{\"type\":\"object\",\"required\":[\"items\"],"
                + "\"properties\":{\"items\":{\"type\":\"array\"}}}";
        String upgraded = Stage21StandaloneAuthPrerequisiteSetupTest.withInventoryBoundary(mapper, source);
        JsonNode result = mapper.readTree(upgraded);
        assertEquals(mapper.readTree(source).path("properties"), result.path("properties"));
        assertEquals(mapper.readTree(source).path("required"), result.path("required"));
        assertEquals("GT", result.path("x-business-boundaries").path(0).path("operator").asText());
        assertEquals(2, result.path("x-business-boundaries").path(0).path("limit").asInt());
        assertEquals(result, mapper.readTree(
                Stage21StandaloneAuthPrerequisiteSetupTest.withInventoryBoundary(mapper, upgraded)));
        String conflicting = upgraded.replace("\"limit\":2", "\"limit\":100");
        assertThrows(IllegalStateException.class, () ->
                Stage21StandaloneAuthPrerequisiteSetupTest.withInventoryBoundary(mapper, conflicting));
    }

    @Test
    void responseAuthorityKeepsSuccessAndBusinessConflictDistinct() throws Exception {
        String source = "{\"type\":\"object\",\"properties\":{\"success\":{\"type\":\"boolean\"}}}";
        String success = Stage21StandaloneAuthPrerequisiteSetupTest.withResponseCodeAuthority(
                mapper, source, "ORDER_SUCCESS");
        String conflict = Stage21StandaloneAuthPrerequisiteSetupTest.withResponseCodeAuthority(
                mapper, source, "ORDER_BUSINESS_CONFLICT");
        assertEquals("ORDER_SUCCESS", mapper.readTree(success).path("properties")
                .path("code").path("enum").path(0).asText());
        assertEquals("ORDER_BUSINESS_CONFLICT", mapper.readTree(conflict).path("properties")
                .path("code").path("enum").path(0).asText());
        assertEquals(mapper.readTree(source).path("properties").path("success"),
                mapper.readTree(conflict).path("properties").path("success"));
        assertThrows(IllegalStateException.class, () ->
                Stage21StandaloneAuthPrerequisiteSetupTest.withResponseCodeAuthority(
                        mapper, success, "ORDER_BUSINESS_CONFLICT"));
    }
}
