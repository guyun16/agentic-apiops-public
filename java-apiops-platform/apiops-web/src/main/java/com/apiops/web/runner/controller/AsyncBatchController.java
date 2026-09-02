package com.apiops.web.runner.controller;

import com.apiops.common.result.Result;
import com.apiops.runner.application.BatchCancelResult;
import com.apiops.web.runner.application.AsyncBatchHttpApplicationService;
import com.apiops.web.runner.dto.AsyncBatchSubmitRequest;
import com.apiops.web.runner.vo.AsyncBatchSubmission;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.UUID;

@RestController
@ConditionalOnProperty(prefix = "apiops.rabbitmq.execution", name = "enabled",
        havingValue = "true")
@RequestMapping("/api/v1/projects/{projectId}/test-batches")
public final class AsyncBatchController {

    private final AsyncBatchHttpApplicationService service;

    public AsyncBatchController(AsyncBatchHttpApplicationService service) {
        this.service = service;
    }

    @PostMapping
    public ResponseEntity<Result<AsyncBatchSubmission>> submit(
            @PathVariable long projectId,
            @RequestBody AsyncBatchSubmitRequest request) {
        return ResponseEntity.status(HttpStatus.ACCEPTED)
                .body(Result.success(service.submit(projectId, request)));
    }

    @PostMapping("/{batchId}/cancel")
    public Result<BatchCancelResult> cancel(
            @PathVariable long projectId,
            @PathVariable UUID batchId) {
        return Result.success(service.cancel(projectId, batchId));
    }
}
