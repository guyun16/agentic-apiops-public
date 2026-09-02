package com.apiops.runner.validation;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.json.JsonMapper;

import java.io.IOException;
import java.io.InputStream;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;

final class TestCaseDslTestSupport {

    private TestCaseDslTestSupport() {
    }

    static ObjectMapper mapper() {
        return JsonMapper.builder().build();
    }

    static TestCaseDslValidator validator(ObjectMapper mapper) {
        Path current = Paths.get("").toAbsolutePath().normalize();
        for (int depth = 0; current != null && depth < 8; depth++, current = current.getParent()) {
            Path schema = current.resolve("shared-schemas/testcase-dsl-schema.json");
            if (Files.isRegularFile(schema)) {
                return new TestCaseDslValidator(mapper, schema);
            }
        }
        throw new IllegalStateException("shared-schemas/testcase-dsl-schema.json was not found");
    }

    static String fixture(String name) throws IOException {
        String resourceName = "/testcase-dsl/" + name;
        try (InputStream input = TestCaseDslTestSupport.class.getResourceAsStream(resourceName)) {
            if (input == null) {
                throw new IllegalArgumentException("Fixture not found: " + resourceName);
            }
            return new String(input.readAllBytes());
        }
    }
}
