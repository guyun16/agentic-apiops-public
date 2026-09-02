package com.apiops.agent.generation;

import com.apiops.agent.model.AgentModelClient;
import com.apiops.agent.model.AgentModelRequest;
import com.apiops.agent.model.AgentModelResponse;
import com.apiops.agent.prompt.PromptTemplateService;
import com.apiops.agent.structured.BoundedStructuredOutputRepair;
import com.apiops.agent.structured.TestCaseCandidateMapper;
import com.apiops.openapi.vo.ApiMetadataDetailVO;
import com.apiops.runner.validation.TestCaseDslValidator;
import com.apiops.runner.dsl.TestCase;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.json.JsonMapper;

import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayDeque;
import java.util.ArrayList;
import java.util.List;

final class GenerateTestCaseTestSupport {

    static final long PROJECT_ID = 42L;
    static final String API_ID = "api_create_order";
    static final String BASE_URL = "http://localhost:8080";
    static final ObjectMapper MAPPER = JsonMapper.builder().build();

    private GenerateTestCaseTestSupport() {
    }

    static GenerateTestCaseAgent agent(AgentModelClient modelClient) {
        return new GenerateTestCaseAgent(
                new PromptTemplateService(),
                new BoundedStructuredOutputRepair<TestCase>(
                        modelClient, new TestCaseCandidateMapper(validator())),
                MAPPER);
    }

    static TestCaseDslValidator validator() {
        Path current = Path.of("").toAbsolutePath().normalize();
        while (current != null) {
            Path schema = current.resolve("shared-schemas/testcase-dsl-schema.json");
            if (Files.isRegularFile(schema)) {
                return new TestCaseDslValidator(MAPPER, schema);
            }
            current = current.getParent();
        }
        throw new IllegalStateException("shared TestCase DSL schema was not found");
    }

    static ApiMetadataDetailVO metadata() {
        return new ApiMetadataDetailVO(
                API_ID, "doc-orders", "createOrder", "POST", "/orders",
                "Create order", "Creates one order", MAPPER.createArrayNode(),
                MAPPER.createArrayNode().add(MAPPER.createObjectNode().put("url", BASE_URL)),
                MAPPER.createArrayNode(), false,
                List.of(new ApiMetadataDetailVO.ParameterVO(
                        "dryRun", "query", false, "dry run",
                        MAPPER.createObjectNode().put("type", "boolean"), null)),
                List.of(new ApiMetadataDetailVO.RequestSchemaVO(
                        true, "application/json",
                        MAPPER.createObjectNode().put("type", "object"))),
                List.of(new ApiMetadataDetailVO.ResponseSchemaVO(
                        "201", "created", "application/json",
                        MAPPER.createObjectNode().put("type", "object"))),
                List.of(new ApiMetadataDetailVO.ExampleVO(
                        new ApiMetadataDetailVO.ExampleOwnerVO(
                                "RESPONSE_SCHEMA", null, null,
                                "application/json", "201"),
                        "created", "created", null,
                        MAPPER.createObjectNode().put("id", 1))));
    }

    static String validCandidate() {
        try (InputStream input = GenerateTestCaseTestSupport.class
                .getResourceAsStream("/candidates/testcase-valid.json")) {
            if (input == null) throw new IllegalStateException("fixture not found");
            return new String(input.readAllBytes(), StandardCharsets.UTF_8);
        } catch (IOException exception) {
            throw new IllegalStateException("fixture could not be read");
        }
    }

    static final class SequenceClient implements AgentModelClient {
        final ArrayList<AgentModelRequest> requests = new ArrayList<>();
        private final ArrayDeque<Object> outcomes;

        SequenceClient(Object... outcomes) {
            this.outcomes = new ArrayDeque<>(List.of(outcomes));
        }

        @Override
        public AgentModelResponse call(AgentModelRequest request) {
            requests.add(request);
            Object outcome = outcomes.removeFirst();
            if (outcome instanceof RuntimeException failure) throw failure;
            return new AgentModelResponse(
                    "model-call-" + requests.size(), (String) outcome);
        }
    }
}
