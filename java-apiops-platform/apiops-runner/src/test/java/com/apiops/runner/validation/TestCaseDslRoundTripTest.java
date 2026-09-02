package com.apiops.runner.validation;

import com.fasterxml.jackson.databind.JsonNode;
import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertEquals;

class TestCaseDslRoundTripTest {

    @Test
    void jsonJavaJsonPreservesContractTree() throws Exception {
        var mapper = TestCaseDslTestSupport.mapper();
        var validator = TestCaseDslTestSupport.validator(mapper);
        String originalJson = TestCaseDslTestSupport.fixture("valid-basic.json");

        JsonNode original = mapper.readTree(originalJson);
        String serializedJson = mapper.writeValueAsString(validator.parse(originalJson));
        JsonNode serialized = mapper.readTree(serializedJson);

        assertEquals(original, serialized);
    }
}
