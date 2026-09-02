package com.apiops.web.runner.controller;

import com.apiops.common.result.Result;
import com.apiops.web.runner.application.RunQueryApplicationService;
import com.apiops.web.runner.vo.RunSummaryVO;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;
import java.util.Objects;

@RestController
@ConditionalOnProperty(prefix = "apiops.datasource.runner", name = "url")
@RequestMapping("/api/v1/projects/{projectId}/test-runs")
public final class RunQueryController {

    private final RunQueryApplicationService service;

    public RunQueryController(RunQueryApplicationService service) {
        this.service = Objects.requireNonNull(service, "service must not be null");
    }

    @GetMapping
    public Result<List<RunSummaryVO>> list(@PathVariable long projectId) {
        return Result.success(service.list(projectId));
    }
}
