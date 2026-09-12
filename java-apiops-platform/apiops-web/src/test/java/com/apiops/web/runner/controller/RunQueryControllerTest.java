package com.apiops.web.runner.controller;

import com.apiops.auth.application.ProjectAuthorizationService;
import com.apiops.auth.enums.ProjectRole;
import com.apiops.auth.security.ApiOpsPrincipal;
import com.apiops.common.enums.FailureType;
import com.apiops.runner.persistence.ExecutionFactRepository;
import com.apiops.runner.persistence.ExecutionFactRepository.RunExecutionFacts;
import com.apiops.runner.state.RunStatus;
import com.apiops.web.runner.application.RunQueryApplicationService;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;

import java.time.Instant;
import java.util.List;
import java.util.Optional;

import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

class RunQueryControllerTest {

    @AfterEach
    void clearSecurity() {
        SecurityContextHolder.clearContext();
    }

    @Test
    void exactRunQueryUsesPersistedRunIdentityWithoutScanningRecentRuns() throws Exception {
        ExecutionFactRepository repository = mock(ExecutionFactRepository.class);
        Instant startedAt = Instant.parse("2026-09-07T00:00:00Z");
        Instant finishedAt = Instant.parse("2026-09-07T00:00:02Z");
        when(repository.findRun(101L, 301L)).thenReturn(Optional.of(new RunExecutionFacts(
                101L, 201L, 301L, "case-1", "api-1", "Case one",
                RunStatus.SUCCESS, FailureType.NONE, startedAt, finishedAt, List.of())));
        MockMvc mvc = mvc(repository);

        mvc.perform(get("/api/v1/projects/101/test-runs/301"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.projectId").value(101))
                .andExpect(jsonPath("$.data.taskId").value(201))
                .andExpect(jsonPath("$.data.runId").value(301))
                .andExpect(jsonPath("$.data.caseId").value("case-1"))
                .andExpect(jsonPath("$.data.apiId").value("api-1"))
                .andExpect(jsonPath("$.data.status").value("SUCCESS"))
                .andExpect(jsonPath("$.data.durationMs").value(2000))
                .andExpect(jsonPath("$.data.reportId").value("report:301"));

        verify(repository).findRun(101L, 301L);
        verify(repository, never()).findRecentRunSummaries(101L);
    }

    @Test
    void exactRunQueryIsProjectScopedAndReturnsNotFound() throws Exception {
        ExecutionFactRepository repository = mock(ExecutionFactRepository.class);
        when(repository.findRun(102L, 301L)).thenReturn(Optional.empty());

        mvc(repository).perform(get("/api/v1/projects/102/test-runs/301"))
                .andExpect(status().isNotFound())
                .andExpect(jsonPath("$.code").value("A0002"));
    }

    private MockMvc mvc(ExecutionFactRepository repository) {
        ApiOpsPrincipal principal = new ApiOpsPrincipal(7L, "viewer", "hash", true, List.of());
        SecurityContextHolder.getContext().setAuthentication(
                UsernamePasswordAuthenticationToken.authenticated(principal, null, List.of()));
        ProjectAuthorizationService authorization = new ProjectAuthorizationService(
                (userId, projectId) -> Optional.of(ProjectRole.VIEWER));
        return MockMvcBuilders.standaloneSetup(new RunQueryController(
                new RunQueryApplicationService(authorization, repository))).build();
    }
}
