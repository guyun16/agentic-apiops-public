package com.apiops.demo.order.web;

import com.apiops.demo.order.common.exception.DemoOrderBusinessException;
import com.apiops.demo.order.common.exception.DemoOrderErrorCode;
import com.apiops.demo.order.common.exception.ResourceNotFoundException;
import com.apiops.demo.order.common.web.ApiResponse;
import com.apiops.demo.order.order.dto.CreateOrderRequest;
import io.swagger.v3.oas.annotations.Hidden;
import jakarta.validation.Valid;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/fixture")
@Hidden
class OrderFixtureController {

    @PostMapping("/orders")
    ApiResponse<Void> createOrder(
            @Valid @RequestBody CreateOrderRequest request
    ) {
        return ApiResponse.success(null);
    }

    @GetMapping("/missing-resource")
    ApiResponse<Void> missingResource() {
        throw new ResourceNotFoundException("order not found");
    }

    @GetMapping("/conflict")
    ApiResponse<Void> conflict() {
        throw new DemoOrderBusinessException(DemoOrderErrorCode.BUSINESS_CONFLICT);
    }

    @GetMapping("/system-error")
    ApiResponse<Void> systemError() {
        throw new IllegalStateException("database password at C:\\secret\\config.yml");
    }
}
