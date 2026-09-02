package com.apiops.agent.generation;

import com.apiops.agent.model.AgentModelException;
import com.apiops.agent.model.ModelCallIdentity;
import com.apiops.agent.structured.StructuredOutputException;
import com.apiops.agent.structured.TestCaseTargetValidator;
import com.apiops.auth.application.ProjectAuthorizationService;
import com.apiops.auth.enums.ProjectRole;
import com.apiops.auth.security.ApiOpsPrincipal;
import com.apiops.openapi.application.OpenApiQueryApplicationService;
import com.apiops.openapi.exception.OpenApiMetadataNotFoundException;
import com.apiops.runner.application.RunExecutionService;
import com.apiops.runner.state.RunStatus;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.access.AccessDeniedException;
import org.springframework.security.core.context.SecurityContextHolder;

import java.util.List;
import java.util.Optional;

import static com.apiops.agent.generation.GenerateTestCaseTestSupport.API_ID;
import static com.apiops.agent.generation.GenerateTestCaseTestSupport.BASE_URL;
import static com.apiops.agent.generation.GenerateTestCaseTestSupport.PROJECT_ID;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

class GenerateTestCaseApplicationServiceTest {

    private final ProjectAuthorizationService authorization =
            new ProjectAuthorizationService((userId, projectId) ->
                    Optional.of(ProjectRole.EDITOR));

    @BeforeEach
    void authenticate() {
        var principal = new ApiOpsPrincipal(7L, "agent-user", "unused", true, List.of());
        SecurityContextHolder.getContext().setAuthentication(
                UsernamePasswordAuthenticationToken.authenticated(
                        principal, null, principal.getAuthorities()));
    }

    @AfterEach
    void clearAuthentication() {
        SecurityContextHolder.clearContext();
    }

    @Test
    void queriesMetadataThenSubmitsAcceptedCandidateToExistingRunner() {
        OpenApiQueryApplicationService metadata = mock(OpenApiQueryApplicationService.class);
        GenerateTestCaseAgent agent = mock(GenerateTestCaseAgent.class);
        RunExecutionService runner = mock(RunExecutionService.class);
        var generated = new GenerateTestCaseResult(
                "agent-run", "generate-testcase", "v1",
                List.of(new ModelCallIdentity("provider-call-1", null)),
                GenerateTestCaseTestSupport.validator().parse(
                        GenerateTestCaseTestSupport.validCandidate()));
        when(metadata.getApi(PROJECT_ID, API_ID))
                .thenReturn(GenerateTestCaseTestSupport.metadata());
        when(agent.generate(PROJECT_ID, GenerateTestCaseTestSupport.metadata(),
                GenerationIntent.HAPPY_PATH, BASE_URL)).thenReturn(generated);
        when(runner.prepare(generated.candidate())).thenReturn(99L);
        when(runner.executeBatchCase(99L)).thenReturn(RunStatus.ASSERTION_FAILED);

        var result = service(metadata, agent, runner).generateAndExecute(
                PROJECT_ID, API_ID, GenerationIntent.HAPPY_PATH, BASE_URL);

        assertEquals("agent-run", result.agentRunId());
        assertEquals(99L, result.runId());
        assertEquals(RunStatus.ASSERTION_FAILED, result.testStatus());
        assertEquals("generate-testcase", result.promptName());
        assertEquals(1, result.modelCallCount());
        assertEquals("provider-call-1", result.modelCalls().getFirst().modelCallId());
        verify(metadata).getApi(PROJECT_ID, API_ID);
        verify(runner).prepare(generated.candidate());
        verify(runner).executeBatchCase(99L);
    }

    @Test
    void generatesAcceptedCandidateWithoutExecutingRunner() {
        OpenApiQueryApplicationService metadata = mock(OpenApiQueryApplicationService.class);
        GenerateTestCaseAgent agent = mock(GenerateTestCaseAgent.class);
        RunExecutionService runner = mock(RunExecutionService.class);
        var generated = new GenerateTestCaseResult(
                "agent-run", "generate-testcase", "v1",
                List.of(new ModelCallIdentity("provider-call-1", null)),
                GenerateTestCaseTestSupport.validator().parse(
                        GenerateTestCaseTestSupport.validCandidate()));
        when(metadata.getApi(PROJECT_ID, API_ID))
                .thenReturn(GenerateTestCaseTestSupport.metadata());
        when(agent.generate(PROJECT_ID, GenerateTestCaseTestSupport.metadata(),
                GenerationIntent.HAPPY_PATH, BASE_URL)).thenReturn(generated);

        var result = service(metadata, agent, runner).generateOnly(PROJECT_ID, API_ID);

        assertEquals("agent-run", result.agentRunId());
        assertEquals(1, result.modelCallCount());
        verify(metadata).getApi(PROJECT_ID, API_ID);
        verify(agent).generate(PROJECT_ID, GenerateTestCaseTestSupport.metadata(),
                GenerationIntent.HAPPY_PATH, BASE_URL);
        verify(runner, never()).prepare(any());
        verify(runner, never()).executeBatchCase(anyLong());
    }

    @Test
    void wrongProjectApiOrBaseUrlNeverPreparesRunner() {
        for (String invalid : List.of(
                GenerateTestCaseTestSupport.validCandidate().replace("\"projectId\": 42", "\"projectId\": 43"),
                GenerateTestCaseTestSupport.validCandidate().replace(API_ID, "api_other"),
                GenerateTestCaseTestSupport.validCandidate().replace(BASE_URL, "http://other:8080"))) {
            assertInvalidNeverRuns(invalid);
        }
    }

    @Test
    void schemaInvalidUnsupportedAssertionAndEmptyStepsNeverPrepareRunner() {
        String valid = GenerateTestCaseTestSupport.validCandidate();
        for (String invalid : List.of(
                valid.replace("\"expected\": 201", "\"expected\": 99"),
                valid.replace("\"STATUS_CODE\"", "\"UNSUPPORTED\""),
                valid.replaceFirst("(?s)\"steps\"\\s*:\\s*\\[.*]\\s*}\\s*$", "\"steps\": []\n}"),
                valid.replaceFirst("\\{", "{\"unknownField\":true,"))) {
            assertInvalidNeverRuns(invalid);
        }
    }

    @Test
    void providerFailureNeverPreparesRunner() {
        OpenApiQueryApplicationService metadata = mock(OpenApiQueryApplicationService.class);
        RunExecutionService runner = mock(RunExecutionService.class);
        when(metadata.getApi(PROJECT_ID, API_ID))
                .thenReturn(GenerateTestCaseTestSupport.metadata());
        var agent = GenerateTestCaseTestSupport.agent(
                new GenerateTestCaseTestSupport.SequenceClient(
                        new AgentModelException("Model provider call failed")));

        assertThrows(AgentModelException.class,
                () -> service(metadata, agent, runner).generateAndExecute(
                        PROJECT_ID, API_ID, GenerationIntent.HAPPY_PATH, BASE_URL));
        verify(runner, never()).prepare(any());
    }

    @Test
    void invalidRequestedBaseUrlFailsBeforeModelCall() {
        OpenApiQueryApplicationService metadata = mock(OpenApiQueryApplicationService.class);
        RunExecutionService runner = mock(RunExecutionService.class);
        var model = new GenerateTestCaseTestSupport.SequenceClient(
                GenerateTestCaseTestSupport.validCandidate());

        assertThrows(IllegalArgumentException.class,
                () -> service(metadata, GenerateTestCaseTestSupport.agent(model), runner)
                        .generateAndExecute(PROJECT_ID, API_ID,
                                GenerationIntent.HAPPY_PATH,
                                BASE_URL + "?override=true"));

        assertEquals(0, model.requests.size());
        verify(metadata, never()).getApi(anyLong(), any());
        verify(runner, never()).prepare(any());
    }

    @Test
    void runnerSubmissionFailureRemainsRunnerFailure() {
        OpenApiQueryApplicationService metadata = mock(OpenApiQueryApplicationService.class);
        RunExecutionService runner = mock(RunExecutionService.class);
        when(metadata.getApi(PROJECT_ID, API_ID))
                .thenReturn(GenerateTestCaseTestSupport.metadata());
        when(runner.prepare(any())).thenThrow(new IllegalStateException("runner unavailable"));

        assertThrows(IllegalStateException.class,
                () -> service(metadata,
                        GenerateTestCaseTestSupport.agent(
                                new GenerateTestCaseTestSupport.SequenceClient(
                                        GenerateTestCaseTestSupport.validCandidate())),
                        runner).generateAndExecute(
                        PROJECT_ID, API_ID, GenerationIntent.HAPPY_PATH, BASE_URL));
    }

    @Test
    void missingMetadataOrDeniedEditAccessNeverCallsAgentOrRunner() {
        OpenApiQueryApplicationService metadata = mock(OpenApiQueryApplicationService.class);
        GenerateTestCaseAgent agent = mock(GenerateTestCaseAgent.class);
        RunExecutionService runner = mock(RunExecutionService.class);
        when(metadata.getApi(PROJECT_ID, API_ID)).thenThrow(
                new OpenApiMetadataNotFoundException("OpenAPI API", API_ID));

        assertThrows(OpenApiMetadataNotFoundException.class,
                () -> service(metadata, agent, runner).generateAndExecute(
                        PROJECT_ID, API_ID, GenerationIntent.HAPPY_PATH, BASE_URL));
        verify(agent, never()).generate(anyLong(), any(), any(), any());
        verify(runner, never()).prepare(any());

        var readOnlyAuthorization = new ProjectAuthorizationService(
                (userId, projectId) -> Optional.of(ProjectRole.VIEWER));
        assertThrows(AccessDeniedException.class,
                () -> new GenerateTestCaseApplicationService(
                        metadata, agent, runner, readOnlyAuthorization,
                        new TestCaseTargetValidator()).generateAndExecute(
                        PROJECT_ID, API_ID, GenerationIntent.HAPPY_PATH, BASE_URL));
        verify(metadata).getApi(PROJECT_ID, API_ID);
    }

    private void assertInvalidNeverRuns(String invalid) {
        OpenApiQueryApplicationService metadata = mock(OpenApiQueryApplicationService.class);
        RunExecutionService runner = mock(RunExecutionService.class);
        when(metadata.getApi(PROJECT_ID, API_ID))
                .thenReturn(GenerateTestCaseTestSupport.metadata());
        var agent = GenerateTestCaseTestSupport.agent(
                new GenerateTestCaseTestSupport.SequenceClient(invalid, invalid));

        assertThrows(StructuredOutputException.class,
                () -> service(metadata, agent, runner).generateAndExecute(
                        PROJECT_ID, API_ID, GenerationIntent.HAPPY_PATH, BASE_URL));
        verify(runner, never()).prepare(any());
        verify(runner, never()).executeBatchCase(org.mockito.ArgumentMatchers.anyLong());
    }

    private GenerateTestCaseApplicationService service(
            OpenApiQueryApplicationService metadata,
            GenerateTestCaseAgent agent,
            RunExecutionService runner) {
        return new GenerateTestCaseApplicationService(
                metadata, agent, runner, authorization,
                new TestCaseTargetValidator());
    }
}
