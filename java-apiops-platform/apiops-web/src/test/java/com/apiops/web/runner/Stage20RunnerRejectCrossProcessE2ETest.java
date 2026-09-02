package com.apiops.web.runner;

import com.apiops.auth.enums.ProjectRole;
import com.apiops.auth.repository.AuthUserRepository;
import com.apiops.auth.repository.GlobalRbacRepository;
import com.apiops.auth.repository.ProjectMembershipRepository;
import com.apiops.auth.jwt.JwtTokenService;
import com.apiops.auth.security.ApiOpsPrincipal;
import com.apiops.auth.security.ApiOpsUserDetailsService;
import com.apiops.runner.application.BatchExecutionCoordinator;
import com.apiops.runner.messaging.BatchExecutionProducer;
import com.apiops.runner.persistence.ExecutionFactRepository;
import com.apiops.web.ApiOpsWebApplication;
import com.apiops.web.runner.application.AsyncBatchHttpApplicationService;
import com.apiops.web.runner.controller.AsyncBatchController;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.context.TestConfiguration;
import org.springframework.boot.test.web.server.LocalServerPort;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Import;
import org.springframework.context.annotation.Primary;
import org.springframework.security.core.userdetails.UserDetailsService;
import org.springframework.test.context.ActiveProfiles;

import java.io.IOException;
import java.io.UncheckedIOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.List;
import java.util.UUID;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.TimeUnit;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.fail;
import static org.mockito.Mockito.mock;

/** Real HTTP/security evidence that a malformed Runner submit is rejected before execution. */
@SpringBootTest(
        classes = ApiOpsWebApplication.class,
        webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT)
@ActiveProfiles("test")
@Import({
        Stage20RunnerRejectCrossProcessE2ETest.RunnerBoundaryConfiguration.class
})
class Stage20RunnerRejectCrossProcessE2ETest {

    private static final long USER_ID = 7L;
    private static final long PROJECT_ID = 42L;
    private static final long RUN_ID = 701L;
    private static final String USERNAME = "stage17-project-a";

    @LocalServerPort
    private int serverPort;

    @Autowired
    private JwtTokenService jwtTokenService;

    @Autowired
    private ObjectMapper objectMapper;

    @Test
    void pythonReceivesRealRunnerRejectAndNoExecutionIdentity() throws Exception {
        String token = jwtTokenService.generateAccessToken(new ApiOpsPrincipal(
                USER_ID,
                USERNAME,
                "test-password-hash",
                true,
                List.of()));
        String traceId = "stage20-runner-reject-" + UUID.randomUUID();
        Path pythonProject = findPythonProject();
        ProcessBuilder builder = new ProcessBuilder(
                "uv", "run", "python", "scripts/stage20_real_e2e.py", "--failure-probe");
        builder.directory(pythonProject.toFile());
        builder.environment().put("JAVA_APIOPS_BASE_URL", "http://127.0.0.1:" + serverPort);
        builder.environment().put("JAVA_APIOPS_TOKEN", token);
        builder.environment().put("STAGE20_PROJECT_ID", Long.toString(PROJECT_ID));
        builder.environment().put("STAGE20_RUN_ID", Long.toString(RUN_ID));
        builder.environment().put("STAGE20_TRACE_ID", traceId);
        builder.environment().put("STAGE20_FAILURE_MODE", "RUNNER_REJECT");
        builder.environment().put("PYTHONUTF8", "1");

        Process process = builder.start();
        CompletableFuture<String> stdout = readAsync(process.getInputStream());
        CompletableFuture<String> stderr = readAsync(process.getErrorStream());
        if (!process.waitFor(60, TimeUnit.SECONDS)) {
            process.destroyForcibly();
            fail("Python Runner rejection probe exceeded its deadline");
        }
        String output = stdout.join().trim();
        String errors = stderr.join().trim();
        assertFalse(output.contains(token));
        assertFalse(errors.contains(token));
        assertEquals(0, process.exitValue(), () -> "Runner rejection probe failed: " + errors);

        JsonNode result = objectMapper.readTree(output);
        assertEquals("RUNNER_REJECT", result.path("failureMode").asText());
        assertEquals("runner_rejected_before_execution", result.path("semantic").asText());
        assertEquals(400, result.path("httpStatus").asInt());
        assertEquals(traceId, result.path("traceId").asText());
        assertFalse(result.has("runId"));
        assertFalse(result.path("rawFallbackUsed").asBoolean(true));
    }

    private static CompletableFuture<String> readAsync(java.io.InputStream stream) {
        return CompletableFuture.supplyAsync(() -> {
            try (stream) {
                return new String(stream.readAllBytes(), StandardCharsets.UTF_8);
            } catch (IOException exception) {
                throw new UncheckedIOException(exception);
            }
        });
    }

    private static Path findPythonProject() {
        Path current = Path.of("").toAbsolutePath();
        while (current != null) {
            Path candidate = current.resolve("python-apiops-agentlab");
            if (Files.isRegularFile(candidate.resolve("pyproject.toml"))) {
                return candidate;
            }
            current = current.getParent();
        }
        throw new IllegalStateException("python-apiops-agentlab project was not found");
    }

    @TestConfiguration(proxyBeanMethods = false)
    static class RunnerBoundaryConfiguration {

        @Bean
        @Primary
        AuthUserRepository stage20AuthUsers() {
            ApiOpsPrincipal principal = new ApiOpsPrincipal(
                    USER_ID, USERNAME, "test-password-hash", true, List.of());
            return username -> USERNAME.equals(username)
                    ? java.util.Optional.of(principal)
                    : java.util.Optional.empty();
        }

        @Bean
        @Primary
        UserDetailsService stage20UserDetails(AuthUserRepository users) {
            return new ApiOpsUserDetailsService(users);
        }

        @Bean
        @Primary
        GlobalRbacRepository stage20GlobalPermissions() {
            return new GlobalRbacRepository() {
                @Override
                public java.util.Set<String> findRoleCodesByUserId(long userId) {
                    return java.util.Set.of();
                }

                @Override
                public java.util.Set<String> findPermissionCodesByUserId(long userId) {
                    return java.util.Set.of();
                }
            };
        }

        @Bean
        @Primary
        ProjectMembershipRepository stage20RunnerMemberships() {
            return (userId, projectId) -> userId == USER_ID && projectId == PROJECT_ID
                    ? java.util.Optional.of(ProjectRole.EDITOR)
                    : java.util.Optional.empty();
        }

        @Bean
        @Primary
        ExecutionFactRepository stage20RunnerRepository() {
            return mock(ExecutionFactRepository.class);
        }

        @Bean
        BatchExecutionProducer stage20RunnerProducer() {
            return mock(BatchExecutionProducer.class);
        }

        @Bean
        BatchExecutionCoordinator stage20RunnerCoordinator() {
            return mock(BatchExecutionCoordinator.class);
        }

        @Bean
        AsyncBatchHttpApplicationService stage20RunnerService(
                com.apiops.auth.application.ProjectAuthorizationService authorization,
                ExecutionFactRepository repository,
                BatchExecutionProducer producer,
                BatchExecutionCoordinator coordinator,
                ObjectMapper objectMapper
        ) {
            return new AsyncBatchHttpApplicationService(
                    authorization, repository, producer, coordinator, objectMapper);
        }

        /**
         * The production controller is conditional on Rabbit execution. This bean
         * exposes the same controller class against test-scope producer/coordinator
         * doubles; the invalid request fails before either can be used.
         */
        @Bean
        AsyncBatchController stage20RunnerController(AsyncBatchHttpApplicationService service) {
            return new AsyncBatchController(service);
        }
    }
}
