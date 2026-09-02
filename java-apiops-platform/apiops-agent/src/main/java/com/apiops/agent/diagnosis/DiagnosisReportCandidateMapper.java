package com.apiops.agent.diagnosis;

import com.apiops.agent.structured.StructuredCandidateMapper;
import com.apiops.agent.structured.StructuredOutputException;
import com.apiops.agent.structured.StructuredOutputFailureType;
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
import java.util.List;
import java.util.Locale;
import java.util.Objects;

/** Validates the shared DiagnosisReport schema before Java mapping. */
public final class DiagnosisReportCandidateMapper
        implements StructuredCandidateMapper<DiagnosisReport> {

    private final ObjectMapper objectMapper;
    private final Schema schema;

    public DiagnosisReportCandidateMapper(ObjectMapper objectMapper, JsonNode schemaNode) {
        this.objectMapper = Objects.requireNonNull(objectMapper, "objectMapper")
                .copy()
                .configure(DeserializationFeature.FAIL_ON_UNKNOWN_PROPERTIES, true);
        Objects.requireNonNull(schemaNode, "schemaNode");
        this.schema = SchemaRegistry.withDefaultDialect(SpecificationVersion.DRAFT_2020_12)
                .getSchema(schemaNode);
    }

    public static DiagnosisReportCandidateMapper fromClasspath(ObjectMapper objectMapper) {
        try (InputStream input = DiagnosisReportCandidateMapper.class
                .getResourceAsStream("/shared-schemas/diagnosis-report-schema.json")) {
            if (input == null) {
                throw new IllegalStateException(
                        "shared DiagnosisReport schema was not found on the classpath");
            }
            return new DiagnosisReportCandidateMapper(objectMapper,
                    objectMapper.readTree(input));
        } catch (IOException exception) {
            throw new IllegalStateException(
                    "Unable to read shared DiagnosisReport schema", exception);
        }
    }

    @Override
    public DiagnosisReport parse(String candidate) {
        final JsonNode document;
        try {
            document = objectMapper.readTree(candidate);
        } catch (JsonProcessingException exception) {
            throw new StructuredOutputException(
                    StructuredOutputFailureType.JSON_PARSE,
                    List.of("/ JSON_PARSE_ERROR"));
        }
        if (document == null || !document.isObject()) {
            throw new StructuredOutputException(
                    StructuredOutputFailureType.CONTRACT_INVALID,
                    List.of("/ JSON_TYPE"));
        }
        List<Error> errors = schema.validate(document);
        if (!errors.isEmpty()) {
            throw new StructuredOutputException(
                    StructuredOutputFailureType.CONTRACT_INVALID,
                    errors.stream().map(this::describe).toList());
        }
        try {
            return objectMapper.treeToValue(document, DiagnosisReport.class);
        } catch (JsonProcessingException exception) {
            throw new StructuredOutputException(
                    StructuredOutputFailureType.CONTRACT_INVALID,
                    List.of("/ JAVA_MAPPING_ERROR"));
        }
    }

    private String describe(Error error) {
        String path = error.getInstanceLocation() == null
                ? "/" : error.getInstanceLocation().toString();
        String keyword = error.getKeyword();
        String code = keyword == null
                ? "SCHEMA_INVALID" : keyword.toUpperCase(Locale.ROOT);
        String message = error.getMessage();
        return message == null || message.isBlank()
                ? path + " " + code
                : path + " " + code + " " + message;
    }
}
