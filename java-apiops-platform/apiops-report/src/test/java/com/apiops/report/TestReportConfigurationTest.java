package com.apiops.report;

import com.apiops.auth.application.ProjectAuthorizationService;
import com.apiops.auth.enums.ProjectRole;
import com.apiops.report.application.TestReportQueryService;
import com.apiops.report.assembler.TestReportAssembler;
import com.apiops.report.config.TestReportConfiguration;
import com.apiops.report.controller.TestReportController;
import com.apiops.runner.persistence.ExecutionFactRepository;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.Test;
import org.springframework.boot.test.context.runner.ApplicationContextRunner;

import java.util.Optional;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.Mockito.mock;

class TestReportConfigurationTest {

    private final ApplicationContextRunner contextRunner = new ApplicationContextRunner()
            .withUserConfiguration(TestReportConfiguration.class)
            .withBean(ObjectMapper.class, ObjectMapper::new)
            .withBean(ProjectAuthorizationService.class, () ->
                    new ProjectAuthorizationService(
                            (userId, projectId) -> Optional.of(ProjectRole.VIEWER)));

    @Test
    void assemblesReadPathWhenExecutionFactRepositoryExists() {
        contextRunner
                .withBean(ExecutionFactRepository.class,
                        () -> mock(ExecutionFactRepository.class))
                .run(context -> {
                    assertEquals(1, context.getBeansOfType(TestReportAssembler.class).size());
                    assertEquals(1, context.getBeansOfType(TestReportQueryService.class).size());
                    assertEquals(1, context.getBeansOfType(TestReportController.class).size());
                });
    }

    @Test
    void keepsReadPathDisabledWhenExecutionFactRepositoryIsAbsent() {
        contextRunner.run(context -> {
            assertTrue(context.getBeansOfType(TestReportAssembler.class).isEmpty());
            assertTrue(context.getBeansOfType(TestReportQueryService.class).isEmpty());
            assertTrue(context.getBeansOfType(TestReportController.class).isEmpty());
        });
    }
}
