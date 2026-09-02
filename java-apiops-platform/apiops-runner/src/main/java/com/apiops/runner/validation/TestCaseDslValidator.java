package com.apiops.runner.validation;

import com.apiops.runner.dsl.TestCase;
import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.DeserializationFeature;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.networknt.schema.Error;
import com.networknt.schema.Schema;
import com.networknt.schema.SchemaRegistry;
import com.networknt.schema.SpecificationVersion;

import java.io.IOException;
import java.io.InputStream;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.List;
import java.util.Locale;
import java.util.Objects;

/** Validates the shared TestCase DSL before Jackson deserialization. */
public final class TestCaseDslValidator {

    public static final String SUPPORTED_SCHEMA_VERSION = "1.0.0";

    private final ObjectMapper objectMapper;
    private final Schema schema;

    public TestCaseDslValidator(ObjectMapper objectMapper, Path schemaPath) {
        this(objectMapper, readSchema(objectMapper, schemaPath));
    }

    public TestCaseDslValidator(ObjectMapper objectMapper, JsonNode schemaNode) {
        this.objectMapper = Objects.requireNonNull(objectMapper, "objectMapper must not be null")
                .copy()
                .configure(DeserializationFeature.FAIL_ON_UNKNOWN_PROPERTIES, true);
        Objects.requireNonNull(schemaNode, "schemaNode must not be null");
        this.schema = SchemaRegistry.withDefaultDialect(SpecificationVersion.DRAFT_2020_12)
                .getSchema(schemaNode);
    }

    public ValidationResult validate(String json) {
        try {
            return validate(objectMapper.readTree(json));
        } catch (JsonProcessingException exception) {
            return ValidationResult.invalid(List.of(new ValidationError(
                    "/", "JSON_PARSE_ERROR", exception.getOriginalMessage())));
        }
    }

    public ValidationResult validate(JsonNode document) {
        if (document == null) {
            return ValidationResult.invalid(List.of(new ValidationError(
                    "/", "JSON_TYPE", "TestCase DSL must be a JSON object")));
        }

        JsonNode version = document.get("schemaVersion");
        if (version != null && version.isTextual()
                && !SUPPORTED_SCHEMA_VERSION.equals(version.textValue())) {
            return ValidationResult.invalid(List.of(new ValidationError(
                    "/schemaVersion",
                    "UNSUPPORTED_SCHEMA_VERSION",
                    "Unsupported schemaVersion: " + version.textValue())));
        }

        List<Error> errors = schema.validate(document);
        if (errors.isEmpty()) {
            return ValidationResult.success();
        }
        return ValidationResult.invalid(errors.stream()
                .map(this::toValidationError)
                .toList());
    }

    public TestCase parse(String json) {
        final JsonNode document;
        try {
            document = objectMapper.readTree(json);
        } catch (JsonProcessingException exception) {
            throw new TestCaseDslValidationException(ValidationResult.invalid(List.of(
                    new ValidationError("/", "JSON_PARSE_ERROR", exception.getOriginalMessage()))));
        }

        ValidationResult result = validate(document);
        if (!result.valid()) {
            throw new TestCaseDslValidationException(result);
        }
        try {
            return objectMapper.treeToValue(document, TestCase.class);
        } catch (JsonProcessingException exception) {
            throw new IllegalStateException("Validated TestCase DSL could not be deserialized", exception);
        }
    }

    private ValidationError toValidationError(Error error) {
        return new ValidationError(
                normalizePath(error.getInstanceLocation().toString()),
                code(error.getKeyword()),
                error.getMessage());
    }

    private String code(String keyword) {
        if (keyword == null) {
            return "SCHEMA_INVALID";
        }
        return switch (keyword) {
            case "required" -> "REQUIRED";
            case "additionalProperties" -> "UNKNOWN_FIELD";
            case "oneOf" -> "SUBTYPE_MISMATCH";
            case "const" -> "CONTRACT_MISMATCH";
            case "enum" -> "INVALID_ENUM";
            case "type" -> "INVALID_TYPE";
            case "minLength", "minimum", "maximum", "minItems" -> "INVALID_VALUE";
            default -> keyword.toUpperCase(Locale.ROOT);
        };
    }

    private String normalizePath(String path) {
        if (path == null || path.isBlank() || "#".equals(path) || "$".equals(path)) {
            return "/";
        }
        return path;
    }

    private static JsonNode readSchema(ObjectMapper objectMapper, Path schemaPath) {
        Objects.requireNonNull(schemaPath, "schemaPath must not be null");
        try (InputStream input = Files.newInputStream(schemaPath)) {
            return objectMapper.readTree(input);
        } catch (IOException exception) {
            throw new IllegalStateException("Unable to read TestCase DSL schema: " + schemaPath,
                    exception);
        }
    }
}
