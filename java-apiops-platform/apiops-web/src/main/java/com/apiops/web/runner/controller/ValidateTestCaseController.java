package com.apiops.web.runner.controller;

import com.apiops.agent.structured.StructuredOutputException;
import com.apiops.agent.structured.TestCaseTargetValidator;
import com.apiops.common.result.Result;
import com.apiops.openapi.application.OpenApiQueryApplicationService;
import com.apiops.runner.validation.TestCaseDslValidator;
import com.apiops.runner.validation.ValidationError;
import com.apiops.runner.validation.ValidationResult;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.web.bind.annotation.*;

import java.io.IOException;
import java.util.List;

/** Read-only validation against the same schema and target contract as generation. */
@RestController
@ConditionalOnProperty(prefix = "apiops.datasource.openapi", name = "url")
@RequestMapping("/api/v1/projects/{projectId}/openapi/apis/{apiId}/testcases:validate")
public final class ValidateTestCaseController {
    private final OpenApiQueryApplicationService metadataQueries;
    private final TestCaseDslValidator validator;
    private final TestCaseTargetValidator targetValidator = new TestCaseTargetValidator();

    public ValidateTestCaseController(OpenApiQueryApplicationService metadataQueries, ObjectMapper mapper) {
        this.metadataQueries = metadataQueries;
        try (var input = getClass().getResourceAsStream("/shared-schemas/testcase-dsl-schema.json")) {
            if (input == null) throw new IllegalStateException("Shared TestCase schema is unavailable");
            validator = new TestCaseDslValidator(mapper, mapper.readTree(input));
        } catch (IOException exception) {
            throw new IllegalStateException("Unable to load TestCase schema", exception);
        }
    }

    @PostMapping
    public Result<ValidationResult> validate(@PathVariable long projectId, @PathVariable String apiId,
                                              @RequestBody JsonNode candidate) {
        // This query checks project read permission and endpoint ownership before validation.
        var metadata = metadataQueries.getApi(projectId, apiId);
        var result = validator.validate(candidate);
        if (!result.valid()) return Result.success(result);
        String baseUrl = null;
        if (metadata.servers() != null && metadata.servers().isArray()) {
            for (var server : metadata.servers()) {
                var url = server.get("url");
                if (url != null && url.isTextual() && !url.textValue().isBlank()) {
                    baseUrl = url.textValue();
                    break;
                }
            }
        }
        if (baseUrl == null) return invalid("No usable HTTP server URL in endpoint metadata");
        try {
            targetValidator.validate(validator.parse(candidate.toString()), projectId, apiId, baseUrl);
            return Result.success(ValidationResult.success());
        } catch (StructuredOutputException | IllegalArgumentException exception) {
            return invalid(exception.getMessage());
        }
    }

    private Result<ValidationResult> invalid(String message) {
        return Result.success(ValidationResult.invalid(List.of(
                new ValidationError("/", "TARGET_MISMATCH", message))));
    }
}
