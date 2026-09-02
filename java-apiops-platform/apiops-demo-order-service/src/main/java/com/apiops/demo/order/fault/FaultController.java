package com.apiops.demo.order.fault;

import com.apiops.demo.order.common.web.ApiResponse;
import com.apiops.demo.order.openapi.OpenApiSuccessResponses;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.Parameter;
import io.swagger.v3.oas.annotations.media.Content;
import io.swagger.v3.oas.annotations.media.ExampleObject;
import io.swagger.v3.oas.annotations.media.Schema;
import io.swagger.v3.oas.annotations.responses.ApiResponses;
import jakarta.validation.constraints.Max;
import jakarta.validation.constraints.Min;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.context.annotation.Profile;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.validation.annotation.Validated;

import java.util.Map;

@RestController
@Validated
@RequestMapping("/api/faults")
@Profile({"local", "test"})
@ConditionalOnProperty(name = "apiops.fault.enabled", havingValue = "true")
public class FaultController {

    private final FaultService faultService;
    private final FaultProperties faultProperties;

    public FaultController(FaultService faultService, FaultProperties faultProperties) {
        this.faultService = faultService;
        this.faultProperties = faultProperties;
    }

    @Operation(
            operationId = "simulateTokenExpiredFault",
            summary = "Simulate an expired-token response",
            description = "Fault-injection endpoint enabled only in local/test profiles; the endpoint itself is public and deliberately returns the service's 401 token-expired error envelope.",
            tags = {"Faults"})
    @ApiResponses({
            @io.swagger.v3.oas.annotations.responses.ApiResponse(
                    responseCode = "401", description = "Simulated expired-token failure.",
                    content = @Content(mediaType = "application/json",
                            schema = @Schema(implementation = ApiResponse.class),
                            examples = @ExampleObject(name = "tokenExpired", value = """
                                    {"success":false,"code":"ORDER_TOKEN_EXPIRED","message":"token expired","data":null}
                                    """))),
            @io.swagger.v3.oas.annotations.responses.ApiResponse(
                    responseCode = "500", description = "Unexpected server failure.",
                    content = @Content(mediaType = "application/json",
                            schema = @Schema(implementation = ApiResponse.class),
                            examples = @ExampleObject(name = "systemError", value = """
                                    {"success":false,"code":"ORDER_SYSTEM_ERROR","message":"internal server error","data":null}
                                    """)))
    })
    @PostMapping("/token-expired")
    ApiResponse<Void> tokenExpired() {
        throw new TokenExpiredException();
    }

    @Operation(
            operationId = "simulateSlowSqlFault",
            summary = "Simulate a slow SQL fault",
            description = "Fault-injection endpoint enabled only in local/test profiles. delayMs defaults to 500 and must be between 100 and 2000 inclusive.",
            tags = {"Faults"})
    @ApiResponses({
            @io.swagger.v3.oas.annotations.responses.ApiResponse(
                    responseCode = "200", description = "Slow SQL execution measurement returned.",
                    content = @Content(mediaType = "application/json",
                            schema = @Schema(implementation = OpenApiSuccessResponses.SlowSqlResponse.class),
                            examples = @ExampleObject(name = "slowSql", value = """
                                    {
                                      "success": true,
                                      "code": "ORDER_SUCCESS",
                                      "message": "success",
                                      "data": {"requestedDelayMs": 500, "elapsedMs": 501}
                                    }
                                    """))),
            @io.swagger.v3.oas.annotations.responses.ApiResponse(
                    responseCode = "400", description = "delayMs is outside the 100-2000 inclusive range.",
                    content = @Content(mediaType = "application/json",
                            schema = @Schema(implementation = ApiResponse.class),
                            examples = @ExampleObject(name = "invalidDelay", value = """
                                    {"success":false,"code":"ORDER_PARAM_INVALID","message":"request parameter invalid","data":null}
                                    """))),
            @io.swagger.v3.oas.annotations.responses.ApiResponse(
                    responseCode = "500", description = "Unexpected server or fault infrastructure failure.",
                    content = @Content(mediaType = "application/json",
                            schema = @Schema(implementation = ApiResponse.class),
                            examples = @ExampleObject(name = "systemError", value = """
                                    {"success":false,"code":"ORDER_SYSTEM_ERROR","message":"internal server error","data":null}
                                    """)))
    })
    @GetMapping("/slow-sql")
    ApiResponse<Map<String, Object>> slowSql(
            @Parameter(description = "Requested SQL delay in milliseconds; defaults to 500.", example = "500",
                    schema = @Schema(type = "integer", format = "int32", minimum = "100", maximum = "2000",
                            defaultValue = "500"))
            @RequestParam(name = "delayMs", required = false)
            @Min(100) @Max(2000) Integer delayMs) {

        int effectiveDelayMs = delayMs == null
                ? faultProperties.getDefaultDelayMs()
                : delayMs;

        long elapsedMs = faultService.executeSlowSql(effectiveDelayMs);

        Map<String, Object> data = Map.of(
                "requestedDelayMs", effectiveDelayMs,
                "elapsedMs", elapsedMs);
        return ApiResponse.success(data);
    }
}
