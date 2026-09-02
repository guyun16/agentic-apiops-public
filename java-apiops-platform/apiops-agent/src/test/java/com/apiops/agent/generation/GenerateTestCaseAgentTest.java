package com.apiops.agent.generation;

import com.apiops.agent.model.AgentModelException;
import com.apiops.agent.structured.StructuredOutputException;
import com.apiops.openapi.vo.ApiMetadataDetailVO;
import com.apiops.runner.dsl.TestCase;
import org.junit.jupiter.api.Test;

import java.util.Arrays;

import static com.apiops.agent.generation.GenerateTestCaseTestSupport.API_ID;
import static com.apiops.agent.generation.GenerateTestCaseTestSupport.BASE_URL;
import static com.apiops.agent.generation.GenerateTestCaseTestSupport.PROJECT_ID;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

class GenerateTestCaseAgentTest {

    @Test
    void validOutputUsesVersionedPromptAndTrustedMetadataContext() {
        var model = new GenerateTestCaseTestSupport.SequenceClient(
                GenerateTestCaseTestSupport.validCandidate());

        GenerateTestCaseResult result = GenerateTestCaseTestSupport.agent(model).generate(
                PROJECT_ID, GenerateTestCaseTestSupport.metadata(),
                GenerationIntent.HAPPY_PATH, BASE_URL);

        assertEquals(API_ID, result.candidate().apiId());
        assertEquals("generate-testcase", result.promptName());
        assertEquals("v1", result.promptVersion());
        assertEquals(1, result.modelCallCount());
        assertTrue(model.requests.getFirst().user()
                .contains("Generate one normal happy-path TestCase"));
        String context = model.requests.getFirst().context();
        assertTrue(context.contains("\"operationId\":\"createOrder\""));
        assertTrue(context.contains("\"parameters\""));
        assertTrue(context.contains("\"requestSchemas\""));
        assertTrue(context.contains("\"responseSchemas\""));
        assertTrue(context.contains("\"examples\""));
        assertTrue(context.contains("\"security\""));
        assertTrue(context.contains("\"trustedBaseUrl\":\"" + BASE_URL + "\""));
    }

    @Test
    void malformedOutputRepairsOnceThenRejects() {
        var model = new GenerateTestCaseTestSupport.SequenceClient("{bad", "{still-bad");

        assertThrows(StructuredOutputException.class,
                () -> GenerateTestCaseTestSupport.agent(model).generate(
                        PROJECT_ID, GenerateTestCaseTestSupport.metadata(),
                        GenerationIntent.HAPPY_PATH, BASE_URL));

        assertEquals(2, model.requests.size());
    }

    @Test
    void repairedCandidatePreservesBothProviderCallIdentities() {
        var model = new GenerateTestCaseTestSupport.SequenceClient(
                "{bad", GenerateTestCaseTestSupport.validCandidate());

        GenerateTestCaseResult result = GenerateTestCaseTestSupport.agent(model).generate(
                PROJECT_ID, GenerateTestCaseTestSupport.metadata(),
                GenerationIntent.HAPPY_PATH, BASE_URL);

        assertEquals(2, result.modelCallCount());
        assertEquals(API_ID, result.candidate().apiId());
        assertEquals("model-call-1", result.modelCalls().getFirst().modelCallId());
        assertEquals("model-call-2", result.modelCalls().getLast().modelCallId());
        assertEquals("model-call-1",
                result.modelCalls().getLast().repairOfModelCallId());
    }

    @Test
    void providerFailureStopsBeforeValidationAndRepair() {
        var model = new GenerateTestCaseTestSupport.SequenceClient(
                new AgentModelException("Model provider call failed"));

        assertThrows(AgentModelException.class,
                () -> GenerateTestCaseTestSupport.agent(model).generate(
                        PROJECT_ID, GenerateTestCaseTestSupport.metadata(),
                        GenerationIntent.HAPPY_PATH, BASE_URL));

        assertEquals(1, model.requests.size());
    }

    @Test
    void structurallyValidTargetMismatchRemainsCandidateForApplicationValidation() {
        var model = new GenerateTestCaseTestSupport.SequenceClient(
                GenerateTestCaseTestSupport.validCandidate()
                        .replace("\"projectId\": 42", "\"projectId\": 43"));

        GenerateTestCaseResult result = GenerateTestCaseTestSupport.agent(model).generate(
                PROJECT_ID, GenerateTestCaseTestSupport.metadata(),
                GenerationIntent.HAPPY_PATH, BASE_URL);

        assertEquals(43L, result.candidate().projectId());
        assertEquals(1, model.requests.size());
    }

    @Test
    void boundaryUsesMetadataVoAndStage7TestCaseWithoutRunnerOrHttpDependencies() throws Exception {
        var generateMethod = GenerateTestCaseAgent.class.getMethod(
                "generate", long.class, ApiMetadataDetailVO.class,
                GenerationIntent.class, String.class);

        assertEquals(GenerateTestCaseResult.class, generateMethod.getReturnType());
        assertEquals(TestCase.class, Arrays.stream(
                        GenerateTestCaseResult.class.getRecordComponents())
                .filter(component -> "candidate".equals(component.getName()))
                .findFirst().orElseThrow().getType());
        assertTrue(Arrays.stream(GenerateTestCaseAgent.class.getDeclaredFields())
                .map(field -> field.getType().getName())
                .noneMatch(type -> type.startsWith("com.apiops.runner.")
                        || type.contains("HttpTransport")));
    }
}
