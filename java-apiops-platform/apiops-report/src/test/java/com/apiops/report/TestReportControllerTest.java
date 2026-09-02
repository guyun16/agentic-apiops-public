package com.apiops.report;

import com.apiops.report.application.TestReportQueryService;
import com.apiops.report.assembler.TestReportAssembler;
import com.apiops.report.controller.TestReportController;
import com.apiops.report.exception.TestReportExceptionHandler;
import com.apiops.report.exception.TestReportNotFoundException;
import com.apiops.report.vo.TestReportVO;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.Test;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;

import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

class TestReportControllerTest {

    @Test
    void exposesProjectScopedReportReadModel() throws Exception {
        TestReportQueryService service = mock(TestReportQueryService.class);
        TestReportVO report = new TestReportAssembler(new ObjectMapper())
                .assemble(TestReportFacts.success());
        when(service.getReport(TestReportFacts.PROJECT_ID, TestReportFacts.RUN_ID))
                .thenReturn(report);

        mvc(service).perform(get(
                        "/api/v1/projects/{projectId}/test-runs/{runId}/report",
                        TestReportFacts.PROJECT_ID,
                        TestReportFacts.RUN_ID))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.success").value(true))
                .andExpect(jsonPath("$.data.projectId").value(TestReportFacts.PROJECT_ID))
                .andExpect(jsonPath("$.data.runId").value(TestReportFacts.RUN_ID))
                .andExpect(jsonPath("$.data.reportId")
                        .value("report:" + TestReportFacts.RUN_ID))
                .andExpect(jsonPath("$.data.summary.totalAssertions").value(2))
                .andExpect(jsonPath("$.data.cases[0].steps[0].responseStatusCode").value(200))
                .andExpect(jsonPath("$.data.cases[0].steps[0].assertionResults[0].type")
                        .value("STATUS_CODE"))
                .andExpect(jsonPath("$.data.cases[0].steps[0].body").doesNotExist())
                .andExpect(jsonPath("$.data.cases[0].steps[0].headers").doesNotExist());
    }

    @Test
    void returnsUnifiedNotFoundResponse() throws Exception {
        TestReportQueryService service = mock(TestReportQueryService.class);
        when(service.getReport(TestReportFacts.PROJECT_ID, TestReportFacts.RUN_ID))
                .thenThrow(new TestReportNotFoundException(
                        TestReportFacts.PROJECT_ID, TestReportFacts.RUN_ID));

        mvc(service).perform(get(
                        "/api/v1/projects/{projectId}/test-runs/{runId}/report",
                        TestReportFacts.PROJECT_ID,
                        TestReportFacts.RUN_ID))
                .andExpect(status().isNotFound())
                .andExpect(jsonPath("$.success").value(false))
                .andExpect(jsonPath("$.code").value("A0002"));
    }

    private MockMvc mvc(TestReportQueryService service) {
        return MockMvcBuilders.standaloneSetup(new TestReportController(service))
                .setControllerAdvice(new TestReportExceptionHandler())
                .build();
    }
}
