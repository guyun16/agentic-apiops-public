package com.apiops.demo.order.order.controller;

import com.apiops.demo.order.common.web.ApiResponse;
import com.apiops.demo.order.order.application.CreateOrderApplicationService;
import com.apiops.demo.order.order.dto.CreateOrderRequest;
import com.apiops.demo.order.order.vo.OrderDetailVO;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.enums.SecuritySchemeType;
import io.swagger.v3.oas.annotations.enums.SecuritySchemeIn;
import io.swagger.v3.oas.annotations.security.SecurityRequirement;
import io.swagger.v3.oas.annotations.security.SecurityScheme;
import jakarta.validation.Valid;
import org.springframework.context.annotation.Profile;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RestController;

/** Local benchmark adapter; the public /orders contract is unchanged. */
@RestController
@Profile("local")
@SecurityScheme(name = "apiKeyAuth", type = SecuritySchemeType.APIKEY,
        in = SecuritySchemeIn.HEADER, paramName = "Authorization")
public class BenchmarkOrderController {
    private final CreateOrderApplicationService orders;

    public BenchmarkOrderController(CreateOrderApplicationService orders) {
        this.orders = orders;
    }

    @Operation(operationId = "stage21AuthCheck", summary = "Create an order with a benchmark API key",
            security = @SecurityRequirement(name = "apiKeyAuth"))
    @io.swagger.v3.oas.annotations.responses.ApiResponse(responseCode = "401",
            description = "Missing or invalid benchmark API key",
            content = @io.swagger.v3.oas.annotations.media.Content(mediaType = "application/json",
                    schema = @io.swagger.v3.oas.annotations.media.Schema(implementation = UnauthorizedResponse.class)))
    @PostMapping("/stage21/auth-check")
    public ApiResponse<OrderDetailVO> create(@Valid @RequestBody CreateOrderRequest request) {
        return ApiResponse.success(orders.createOrder(request));
    }

    public record UnauthorizedResponse(boolean success,
            @io.swagger.v3.oas.annotations.media.Schema(allowableValues = {"AUTH_UNAUTHORIZED"}) String code,
            String message, Object data) { }
}
