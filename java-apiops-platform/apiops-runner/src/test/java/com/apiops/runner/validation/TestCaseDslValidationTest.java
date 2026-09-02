package com.apiops.runner.validation;

import com.apiops.runner.dsl.HeaderAssertionSpec;
import com.apiops.runner.dsl.JsonPathAssertionSpec;
import com.apiops.runner.dsl.ResponseTimeAssertionSpec;
import com.apiops.runner.dsl.StatusCodeAssertionSpec;
import com.apiops.runner.dsl.TestCase;
import org.junit.jupiter.api.Test;

import java.util.List;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertInstanceOf;
import static org.junit.jupiter.api.Assertions.assertTrue;

class TestCaseDslValidationTest {

    @Test
    void acceptsValidDslAndDeserializesAllAssertionSubtypes() throws Exception {
        var mapper = TestCaseDslTestSupport.mapper();
        var validator = TestCaseDslTestSupport.validator(mapper);
        var json = TestCaseDslTestSupport.fixture("valid-basic.json");

        ValidationResult result = validator.validate(json);
        assertTrue(result.valid(), () -> result.errors().toString());

        TestCase testCase = validator.parse(json);
        assertEquals("1.0.0", testCase.schemaVersion());
        assertEquals(1001L, testCase.projectId());
        assertEquals("api_create_order", testCase.apiId());
        assertEquals(5, testCase.steps().getFirst().assertions().size());
        assertInstanceOf(StatusCodeAssertionSpec.class,
                testCase.steps().getFirst().assertions().get(0));
        assertInstanceOf(HeaderAssertionSpec.class,
                testCase.steps().getFirst().assertions().get(1));
        assertInstanceOf(JsonPathAssertionSpec.class,
                testCase.steps().getFirst().assertions().get(2));
        assertInstanceOf(JsonPathAssertionSpec.class,
                testCase.steps().getFirst().assertions().get(3));
        assertInstanceOf(ResponseTimeAssertionSpec.class,
                testCase.steps().getFirst().assertions().get(4));
    }

    @Test
    void rejectsMissingRequiredField() throws Exception {
        assertInvalid("missing-required.json", "REQUIRED");
    }

    @Test
    void rejectsMissingSchemaVersion() throws Exception {
        assertInvalid("missing-schema-version.json", "REQUIRED");
    }

    @Test
    void rejectsStringProjectId() throws Exception {
        assertInvalid("project-id-string.json", "INVALID_TYPE");
    }

    @Test
    void rejectsUnknownRootField() throws Exception {
        assertInvalid("unknown-field.json", "UNKNOWN_FIELD");
    }

    @Test
    void rejectsUnknownAssertionType() throws Exception {
        assertInvalid("unknown-assertion-type.json", "SUBTYPE_MISMATCH");
    }

    @Test
    void rejectsStatusCodeAssertionWithoutExpected() throws Exception {
        assertInvalid("status-code-missing-expected.json", "REQUIRED");
    }

    @Test
    void rejectsJsonPathEqualsWithoutExpected() throws Exception {
        assertInvalid("json-path-equals-missing-expected.json", "REQUIRED");
    }

    @Test
    void rejectsOneOfSubtypeMismatch() throws Exception {
        assertInvalid("one-of-mismatch.json", "SUBTYPE_MISMATCH");
    }

    @Test
    void rejectsUnsupportedSchemaVersionBeforeSchemaValidation() throws Exception {
        var mapper = TestCaseDslTestSupport.mapper();
        var validator = TestCaseDslTestSupport.validator(mapper);

        ValidationResult result = validator.validate(
                TestCaseDslTestSupport.fixture("unsupported-version.json"));

        assertFalse(result.valid());
        assertEquals(List.of("/schemaVersion"), result.errors().stream()
                .map(ValidationError::path)
                .toList());
        assertEquals(List.of("UNSUPPORTED_SCHEMA_VERSION"), result.errors().stream()
                .map(ValidationError::code)
                .toList());
    }

    @Test
    void parseExposesPlatformValidationResultInsteadOfValidatorException() throws Exception {
        var validator = TestCaseDslTestSupport.validator(TestCaseDslTestSupport.mapper());

        try {
            validator.parse(TestCaseDslTestSupport.fixture("unknown-field.json"));
        } catch (TestCaseDslValidationException exception) {
            assertFalse(exception.result().valid());
            assertTrue(exception.result().errors().stream()
                    .anyMatch(error -> "UNKNOWN_FIELD".equals(error.code())));
            return;
        }
        throw new AssertionError("Expected TestCaseDslValidationException");
    }

    private void assertInvalid(String fixture, String expectedCode) throws Exception {
        var validator = TestCaseDslTestSupport.validator(TestCaseDslTestSupport.mapper());
        ValidationResult result = validator.validate(TestCaseDslTestSupport.fixture(fixture));

        assertFalse(result.valid(), () -> fixture + " unexpectedly passed");
        assertTrue(result.errors().stream().anyMatch(error -> expectedCode.equals(error.code())),
                () -> fixture + " errors: " + result.errors());
    }
}
