package com.apiops.web.runner.controller;

import com.apiops.common.result.Result;
import com.apiops.common.enums.ErrorCode;
import com.apiops.web.runner.application.RunQueryApplicationService;
import com.apiops.web.runner.vo.RunDetailVO;
import com.apiops.web.runner.vo.RunSummaryVO;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
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
    public Result<List<RunSummaryVO>> list(
            @PathVariable long projectId,
            @RequestParam(required = false) Long beforeRunId,
            @RequestParam(required = false) Integer limit
    ) {
        if (beforeRunId == null && limit == null) {
            return Result.success(service.list(projectId));
        }
        return Result.success(service.listPage(projectId, beforeRunId, limit == null ? 100 : limit));
    }

    @GetMapping("/latest-by-case")
    public Result<RunSummaryVO> latestByCase(
            @PathVariable long projectId,
            @RequestParam String caseId
    ) {
        return Result.success(service.findLatestByCase(projectId, caseId).orElse(null));
    }

    @GetMapping("/{runId}")
    public ResponseEntity<Result<RunDetailVO>> get(
            @PathVariable long projectId,
            @PathVariable long runId
    ) {
        return service.find(projectId, runId)
                .map(run -> ResponseEntity.ok(Result.success(run)))
                .orElseGet(() -> ResponseEntity.status(HttpStatus.NOT_FOUND)
                        .body(Result.fail(ErrorCode.RESOURCE_NOT_FOUND)));
    }
}
