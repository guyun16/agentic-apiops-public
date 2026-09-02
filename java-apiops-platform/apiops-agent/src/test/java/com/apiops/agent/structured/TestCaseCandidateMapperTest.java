package com.apiops.agent.structured;

import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;

class TestCaseCandidateMapperTest {

    private final TestCaseCandidateMapper mapper = StructuredOutputTestSupport.mapper();

    @Test
    void rejectsMalformedJsonWithStableParseFailure() {
        StructuredOutputException exception = assertThrows(
                StructuredOutputException.class, () -> mapper.parse("{broken"));
        assertEquals(StructuredOutputFailureType.JSON_PARSE, exception.failureType());
    }

    @Test
    void rejectsSchemaInvalidAndUnknownFieldsThroughStage7Validator() {
        String valid = StructuredOutputTestSupport.validCandidate();

        StructuredOutputException schema = assertThrows(
                StructuredOutputException.class,
                () -> mapper.parse(valid.replace("\"expected\": 201", "\"expected\": 99")));
        assertEquals(StructuredOutputFailureType.CONTRACT_INVALID, schema.failureType());

        StructuredOutputException unknown = assertThrows(
                StructuredOutputException.class,
                () -> mapper.parse(valid.replaceFirst("\\{", "{\"unknownField\":true,")));
        assertEquals(StructuredOutputFailureType.CONTRACT_INVALID, unknown.failureType());
        org.junit.jupiter.api.Assertions.assertTrue(unknown.errors().stream()
                .anyMatch(error -> error.contains("UNKNOWN_FIELD")));
    }

    @Test
    void targetValidatorRejectsSchemaValidWrongApiId() {
        var candidate = mapper.parse(StructuredOutputTestSupport.validCandidate()
                .replace("api_create_order", "api_other"));

        StructuredOutputException exception = assertThrows(
                StructuredOutputException.class,
                () -> new TestCaseTargetValidator().validate(
                        candidate, 42L, "api_create_order"));
        assertEquals(StructuredOutputFailureType.TARGET_MISMATCH,
                exception.failureType());
    }
}
