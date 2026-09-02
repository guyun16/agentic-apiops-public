package com.apiops.agent.structured;

import com.apiops.runner.validation.TestCaseDslValidator;
import com.fasterxml.jackson.databind.json.JsonMapper;

import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;

final class StructuredOutputTestSupport {

    private StructuredOutputTestSupport() {
    }

    static TestCaseCandidateMapper mapper() {
        Path current = Path.of("").toAbsolutePath().normalize();
        while (current != null) {
            Path schema = current.resolve("shared-schemas/testcase-dsl-schema.json");
            if (Files.isRegularFile(schema)) {
                return new TestCaseCandidateMapper(
                        new TestCaseDslValidator(JsonMapper.builder().build(), schema));
            }
            current = current.getParent();
        }
        throw new IllegalStateException("shared TestCase DSL schema was not found");
    }

    static String validCandidate() {
        try (InputStream input = StructuredOutputTestSupport.class
                .getResourceAsStream("/candidates/testcase-valid.json")) {
            if (input == null) {
                throw new IllegalStateException("candidate fixture was not found");
            }
            return new String(input.readAllBytes(), StandardCharsets.UTF_8);
        } catch (IOException exception) {
            throw new IllegalStateException("candidate fixture could not be read");
        }
    }
}
