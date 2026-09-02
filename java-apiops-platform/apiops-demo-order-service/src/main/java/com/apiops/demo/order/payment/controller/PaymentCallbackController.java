package com.apiops.demo.order.payment.controller;

import com.apiops.demo.order.common.web.ApiResponse;
import com.apiops.demo.order.payment.application.PaymentCallbackApplicationService;
import com.apiops.demo.order.payment.dto.PaymentCallbackRequest;
import com.apiops.demo.order.payment.vo.PaymentCallbackResultVO;
import com.apiops.demo.order.openapi.OpenApiSuccessResponses;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.media.Content;
import io.swagger.v3.oas.annotations.media.ExampleObject;
import io.swagger.v3.oas.annotations.media.Schema;
import io.swagger.v3.oas.annotations.responses.ApiResponses;
import jakarta.validation.Valid;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/payments")
@ConditionalOnProperty(name = "spring.datasource.url")
public class PaymentCallbackController {

    private final PaymentCallbackApplicationService paymentCallbackApplicationService;

    public PaymentCallbackController(
            PaymentCallbackApplicationService paymentCallbackApplicationService
    ) {
        this.paymentCallbackApplicationService = paymentCallbackApplicationService;
    }

    @Operation(
            operationId = "receivePaymentCallback",
            summary = "Receive a payment callback",
            description = "Processes a SUCCESS callback, transitions the pending payment and order, and returns FIRST_SUCCESS or IDEMPOTENT_REPLAY for duplicate delivery.",
            tags = {"Payments"})
    @ApiResponses({
            @io.swagger.v3.oas.annotations.responses.ApiResponse(
                    responseCode = "200", description = "Callback accepted or replayed idempotently.",
                    content = @Content(mediaType = "application/json",
                            schema = @Schema(implementation = OpenApiSuccessResponses.PaymentCallbackResponse.class),
                            examples = @ExampleObject(name = "firstSuccess", value = """
                                    {
                                      "success": true,
                                      "code": "ORDER_SUCCESS",
                                      "message": "success",
                                      "data": {
                                        "callbackId": "callback-1",
                                        "paymentId": 20,
                                        "orderId": 10,
                                        "paymentAmount": 99.00,
                                        "result": "SUCCESS",
                                        "outcome": "FIRST_SUCCESS",
                                        "replay": false
                                      }
                                    }
                                    """))),
            @io.swagger.v3.oas.annotations.responses.ApiResponse(
                    responseCode = "400", description = "Callback body validation failed.",
                    content = @Content(mediaType = "application/json",
                            schema = @Schema(implementation = ApiResponse.class),
                            examples = @ExampleObject(name = "invalidCallback", value = """
                                    {"success":false,"code":"ORDER_PARAM_INVALID","message":"request parameter invalid","data":null}
                                    """))),
            @io.swagger.v3.oas.annotations.responses.ApiResponse(
                    responseCode = "404", description = "Referenced payment or order does not exist.",
                    content = @Content(mediaType = "application/json",
                            schema = @Schema(implementation = ApiResponse.class),
                            examples = @ExampleObject(name = "missingPayment", value = """
                                    {"success":false,"code":"ORDER_RESOURCE_NOT_FOUND","message":"payment not found","data":null}
                                    """))),
            @io.swagger.v3.oas.annotations.responses.ApiResponse(
                    responseCode = "409", description = "Payment/order identity, amount, status, result, or callback idempotency conflicts.",
                    content = @Content(mediaType = "application/json",
                            schema = @Schema(implementation = ApiResponse.class),
                            examples = @ExampleObject(name = "callbackConflict", value = """
                                    {"success":false,"code":"ORDER_BUSINESS_CONFLICT","message":"payment callback idempotency conflict","data":null}
                                    """))),
            @io.swagger.v3.oas.annotations.responses.ApiResponse(
                    responseCode = "500", description = "Unexpected server failure.",
                    content = @Content(mediaType = "application/json",
                            schema = @Schema(implementation = ApiResponse.class),
                            examples = @ExampleObject(name = "systemError", value = """
                                    {"success":false,"code":"ORDER_SYSTEM_ERROR","message":"internal server error","data":null}
                                    """)))
    })
    @PostMapping("/callback")
    ApiResponse<PaymentCallbackResultVO> callback(
            @io.swagger.v3.oas.annotations.parameters.RequestBody(
                    description = "Payment platform callback payload. callbackId is the idempotency key.",
                    required = true,
                    content = @Content(mediaType = "application/json",
                            examples = @ExampleObject(name = "paymentCallbackRequest", value = """
                                    {
                                      "callbackId": "callback-1",
                                      "paymentId": 20,
                                      "orderId": 10,
                                      "paymentAmount": 99.00,
                                      "result": "SUCCESS",
                                      "callbackTime": "2025-01-01T00:00:00"
                                    }
                                    """)))
            @Valid @RequestBody PaymentCallbackRequest request
    ) {
        return ApiResponse.success(paymentCallbackApplicationService.handle(request));
    }
}
