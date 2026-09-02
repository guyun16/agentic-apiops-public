package com.apiops.web.tool;

import com.apiops.agent.diagnosis.DiagnosisReport;
import com.apiops.agent.diagnosis.DiagnosisReportCandidateMapper;
import com.apiops.agent.structured.StructuredOutputException;
import com.apiops.common.enums.ToolStatus;
import com.apiops.common.tool.ToolResult;
import com.apiops.openapi.vo.ApiMetadataDetailVO;
import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.DeserializationFeature;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.json.JsonMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import com.networknt.schema.Error;
import com.networknt.schema.Schema;
import com.networknt.schema.SchemaRegistry;
import com.networknt.schema.SpecificationVersion;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.EnumSource;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.List;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertThrows;

/** Verifies Java and Python canonical fixtures against the same shared contracts. */
class SharedContractCompatibilityTest {

    private final ObjectMapper json = JsonMapper.builder()
            .configure(DeserializationFeature.FAIL_ON_UNKNOWN_PROPERTIES, true)
            .build();
    private final ToolGatewayContractMapper toolMapper = new ToolGatewayContractMapper();

    @Test
    void canonicalMetadataIsAcceptedBySharedSchemaAndJavaProducerView() throws Exception {
        JsonNode fixture = read("examples/openapi-metadata-valid.json");

        assertValid("shared-schemas/openapi-metadata-schema.json", fixture);
        ApiMetadataDetailVO metadata = json.treeToValue(fixture, ApiMetadataDetailVO.class);

        assertEquals(fixture, json.valueToTree(metadata));
    }

    @Test
    void metadataInvalidCasesAreRejectedBySharedJavaValidation() throws Exception {
        ObjectNode valid = (ObjectNode) read("examples/openapi-metadata-valid.json");

        assertInvalid("shared-schemas/openapi-metadata-schema.json",
                copyWithout(valid, "apiId"));
        assertInvalid("shared-schemas/openapi-metadata-schema.json",
                valid.deepCopy().put("unknownField", true));
        ObjectNode malformed = valid.deepCopy();
        malformed.set("parameters", json.createObjectNode().put("name", "limit"));
        assertInvalid("shared-schemas/openapi-metadata-schema.json", malformed);
        ObjectNode invalidEnum = valid.deepCopy();
        ((ObjectNode) invalidEnum.withArray("parameters").get(0)).put("location", "body");
        assertInvalid("shared-schemas/openapi-metadata-schema.json", invalidEnum);
    }

    @Test
    void canonicalToolCallIsAcceptedBySharedSchemaAndJavaMapper() throws Exception {
        JsonNode fixture = read("examples/tool-call-valid.json");

        assertValid("shared-schemas/tool-call-schema.json", fixture);
        ToolCallRequest request = json.treeToValue(fixture, ToolCallRequest.class);

        assertNull(toolMapper.validationError(request, 42L, "trace_001"));
        assertEquals(fixture, json.valueToTree(request));
    }

    @Test
    void toolCallInvalidCasesAreRejectedByJavaContractBoundary() throws Exception {
        ObjectNode valid = (ObjectNode) read("examples/tool-call-valid.json");
        String schema = "shared-schemas/tool-call-schema.json";

        ObjectNode missing = copyWithout(valid, "agentRunId");
        assertInvalid(schema, missing);
        assertFalse(toolMapper.validationError(
                json.treeToValue(missing, ToolCallRequest.class), 42L, "trace_001").isBlank());

        ObjectNode unknown = (ObjectNode) read(
                "examples/invalid/tool-call-unknown-field.json");
        assertInvalid(schema, unknown);
        assertThrows(JsonProcessingException.class,
                () -> json.treeToValue(unknown, ToolCallRequest.class));

        ObjectNode wrongType = valid.deepCopy();
        wrongType.set("params", json.createArrayNode().add("not-an-object"));
        assertInvalid(schema, wrongType);
        assertThrows(JsonProcessingException.class,
                () -> json.treeToValue(wrongType, ToolCallRequest.class));

        ObjectNode invalidEnum = (ObjectNode) read(
                "examples/invalid/tool-call-legacy-tool-name.json");
        assertInvalid(schema, invalidEnum);
        assertFalse(toolMapper.validationError(
                json.treeToValue(invalidEnum, ToolCallRequest.class), 42L, "trace_001").isBlank());

        ObjectNode unsupported = valid.deepCopy().put("schemaVersion", "9.9.9");
        assertInvalid(schema, unsupported);
        assertFalse(toolMapper.validationError(
                json.treeToValue(unsupported, ToolCallRequest.class), 42L, "trace_001").isBlank());
    }

    @Test
    void canonicalToolResultIsAcceptedBySharedSchemaAndJavaView() throws Exception {
        JsonNode fixture = read("examples/tool-result-valid.json");

        assertValid("shared-schemas/tool-result-schema.json", fixture);
        ToolResultResponse response = json.treeToValue(fixture, ToolResultResponse.class);

        assertEquals(fixture, json.valueToTree(response));
    }

    @ParameterizedTest
    @EnumSource(ToolStatus.class)
    void everyJavaProducedToolStatusSatisfiesSharedSchema(ToolStatus status) throws Exception {
        ToolResultResponse response = toolMapper.toPublicResult(
                ToolResult.ofStatus("rag.search", "java-generated-contract-id", status, null),
                "trace-contract");

        assertValid("shared-schemas/tool-result-schema.json", json.valueToTree(response));
    }

    @Test
    void toolResultInvalidCasesAreRejectedBySharedJavaValidation() throws Exception {
        ObjectNode valid = (ObjectNode) read("examples/tool-result-valid.json");
        String schema = "shared-schemas/tool-result-schema.json";

        assertInvalid(schema, copyWithout(valid, "status"));
        assertInvalid(schema, read("examples/invalid/tool-result-unknown-field.json"));
        assertInvalid(schema, valid.deepCopy().put("status", "DENIED"));
        assertInvalid(schema, valid.deepCopy().put("sanitized", "true"));
        assertInvalid(schema, valid.deepCopy().put("schemaVersion", "9.9.9"));
    }

    @Test
    void canonicalDiagnosisReportIsAcceptedBySharedSchemaAndJavaMapper() throws Exception {
        JsonNode fixture = read("examples/diagnosis-report-valid.json");

        assertValid("shared-schemas/diagnosis-report-schema.json", fixture);
        DiagnosisReport report = DiagnosisReportCandidateMapper.fromClasspath(json)
                .parse(json.writeValueAsString(fixture));

        assertEquals("report:1001001", report.reportId());
        assertEquals(1001001L, report.runId());
    }

    @Test
    void diagnosisInvalidCasesAreRejectedByJavaMapper() throws Exception {
        ObjectNode valid = (ObjectNode) read("examples/diagnosis-report-valid.json");
        DiagnosisReportCandidateMapper mapper = DiagnosisReportCandidateMapper.fromClasspath(json);

        assertDiagnosisInvalid(mapper, copyWithout(valid, "summary"));
        assertDiagnosisInvalid(mapper, valid.deepCopy().put("unknownField", true));
        ObjectNode invalidEnum = valid.deepCopy();
        ((ObjectNode) invalidEnum.withArray("rootCauseHypotheses").get(0))
                .put("confidence", "CERTAIN");
        assertDiagnosisInvalid(mapper, invalidEnum);
        assertDiagnosisInvalid(mapper, valid.deepCopy().put("schemaVersion", "9.9.9"));
    }

    private void assertDiagnosisInvalid(DiagnosisReportCandidateMapper mapper, JsonNode value)
            throws JsonProcessingException {
        assertThrows(StructuredOutputException.class,
                () -> mapper.parse(json.writeValueAsString(value)));
    }

    private void assertValid(String schemaPath, JsonNode value) throws IOException {
        List<Error> errors = schema(schemaPath).validate(value);
        assertEquals(List.of(), errors);
    }

    private void assertInvalid(String schemaPath, JsonNode value) throws IOException {
        assertFalse(schema(schemaPath).validate(value).isEmpty());
    }

    private Schema schema(String path) throws IOException {
        return SchemaRegistry.withDefaultDialect(SpecificationVersion.DRAFT_2020_12)
                .getSchema(read(path));
    }

    private JsonNode read(String path) throws IOException {
        return json.readTree(repositoryFile(path).toFile());
    }

    private static ObjectNode copyWithout(ObjectNode source, String field) {
        ObjectNode copy = source.deepCopy();
        copy.remove(field);
        return copy;
    }

    private static Path repositoryFile(String relativePath) {
        Path current = Path.of("").toAbsolutePath();
        while (current != null) {
            Path candidate = current.resolve(relativePath);
            if (Files.isRegularFile(candidate)) {
                return candidate;
            }
            current = current.getParent();
        }
        throw new IllegalStateException("repository file not found: " + relativePath);
    }
}
