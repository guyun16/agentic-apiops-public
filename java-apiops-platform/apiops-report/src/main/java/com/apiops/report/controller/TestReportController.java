package com.apiops.report.controller;

import com.apiops.common.result.Result;
import com.apiops.report.application.TestReportQueryService;
import com.apiops.report.vo.TestReportVO;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.Objects;

@RestController
@RequestMapping("/api/v1/projects/{projectId}/test-runs")
public final class TestReportController {

    private final TestReportQueryService queryService;

    public TestReportController(TestReportQueryService queryService) {
        this.queryService = Objects.requireNonNull(queryService, "queryService must not be null");
    }

    @GetMapping("/{runId}/report")
    public Result<TestReportVO> report(
            @PathVariable long projectId,
            @PathVariable long runId
    ) {
        return Result.success(queryService.getReport(projectId, runId));
    }
}
