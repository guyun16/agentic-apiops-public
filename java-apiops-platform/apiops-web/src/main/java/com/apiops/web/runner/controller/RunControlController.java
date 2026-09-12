package com.apiops.web.runner.controller;

import com.apiops.common.result.Result;
import com.apiops.runner.application.BatchCancelResult;
import com.apiops.web.runner.application.AsyncBatchHttpApplicationService;
import com.apiops.web.runner.vo.AsyncBatchSubmission;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.*;

@RestController
@ConditionalOnProperty(prefix = "apiops.rabbitmq.execution", name = "enabled", havingValue = "true")
@RequestMapping("/api/v1/projects/{projectId}/test-runs/{runId}")
public final class RunControlController {
    private final AsyncBatchHttpApplicationService service;

    public RunControlController(AsyncBatchHttpApplicationService service) { this.service = service; }

    @GetMapping("/controls")
    public Result<AsyncBatchHttpApplicationService.RunControls> controls(@PathVariable long projectId, @PathVariable long runId) {
        return Result.success(service.controls(projectId, runId));
    }

    @PostMapping("/cancel")
    public Result<BatchCancelResult> cancel(@PathVariable long projectId, @PathVariable long runId) {
        return Result.success(service.cancelRun(projectId, runId));
    }

    @PostMapping("/rerun")
    @ResponseStatus(HttpStatus.ACCEPTED)
    public Result<AsyncBatchSubmission> rerun(@PathVariable long projectId, @PathVariable long runId) {
        return Result.success(service.rerun(projectId, runId));
    }
}
