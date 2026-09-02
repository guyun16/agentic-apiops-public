package com.apiops.web.agent.controller;

import com.apiops.agent.generation.GenerateTestCaseApplicationService;
import com.apiops.agent.generation.GenerateTestCaseResult;
import com.apiops.agent.structured.StructuredOutputException;
import com.apiops.common.enums.ErrorCode;
import com.apiops.common.result.Result;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

/** Project-scoped HTTP adapter for the existing Java TestCase generation agent. */
@RestController
@ConditionalOnProperty(prefix = "spring.ai.model", name = "chat", havingValue = "openai")
@RequestMapping("/api/v1/projects/{projectId}/openapi/apis/{apiId}/testcases:generate")
public final class GenerateTestCaseController {

    private final GenerateTestCaseApplicationService service;

    public GenerateTestCaseController(GenerateTestCaseApplicationService service) {
        this.service = service;
    }

    @PostMapping
    public ResponseEntity<Result<GenerateTestCaseResult>> generate(
            @PathVariable long projectId,
            @PathVariable String apiId,
            @RequestBody(required = false) GenerateTestCaseRequest request) {
        try {
            GenerateTestCaseRequest effectiveRequest = request == null
                    ? GenerateTestCaseRequest.defaults() : request;
            return ResponseEntity.ok(Result.success(service.generateOnly(
                    projectId,
                    apiId,
                    effectiveRequest.strategy())));
        } catch (StructuredOutputException exception) {
            return ResponseEntity.status(HttpStatus.UNPROCESSABLE_ENTITY)
                    .body(Result.fail(
                            ErrorCode.PARAM_INVALID,
                            "Generated TestCase candidate rejected after bounded repair: "
                                    + String.join("; ", exception.errors())));
        }
    }
}
