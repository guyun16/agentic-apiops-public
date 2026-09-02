package com.apiops.demo.order.order.controller;

import com.apiops.demo.order.common.web.ApiResponse;
import com.apiops.demo.order.order.application.CreateOrderApplicationService;
import com.apiops.demo.order.order.application.OrderApplicationService;
import com.apiops.demo.order.order.dto.CreateOrderRequest;
import com.apiops.demo.order.order.enums.OrderEvent;
import com.apiops.demo.order.order.vo.OrderDetailVO;
import com.apiops.demo.order.openapi.OpenApiSuccessResponses;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.Parameter;
import io.swagger.v3.oas.annotations.media.Content;
import io.swagger.v3.oas.annotations.media.ExampleObject;
import io.swagger.v3.oas.annotations.media.Schema;
import io.swagger.v3.oas.annotations.responses.ApiResponses;
import jakarta.validation.Valid;
import jakarta.validation.constraints.Positive;
import org.springframework.validation.annotation.Validated;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@Validated
@RestController
@RequestMapping("/orders")
public class OrderController {

    private final CreateOrderApplicationService createOrderApplicationService;
    private final OrderApplicationService orderApplicationService;

    public OrderController(
            CreateOrderApplicationService createOrderApplicationService,
            OrderApplicationService orderApplicationService
    ) {
        this.createOrderApplicationService = createOrderApplicationService;
        this.orderApplicationService = orderApplicationService;
    }

    @Operation(
            operationId = "createOrder",
            summary = "Create an order",
            description = "Creates an order in PENDING_PAYMENT state, deducts inventory, optionally consumes the user's available coupon, and creates the pending payment record.",
            tags = {"Orders"})
    @ApiResponses({
            @io.swagger.v3.oas.annotations.responses.ApiResponse(
                    responseCode = "200", description = "Order created.",
                    content = @Content(mediaType = "application/json",
                            schema = @Schema(implementation = OpenApiSuccessResponses.OrderDetailResponse.class),
                            examples = @ExampleObject(name = "createdOrder", value = """
                                    {
                                      "success": true,
                                      "code": "ORDER_SUCCESS",
                                      "message": "success",
                                      "data": {
                                        "id": 10,
                                        "orderNo": "ord_00000000-0000-4000-8000-000000000001",
                                        "userId": 1,
                                        "originalAmount": 100.00,
                                        "discountAmount": 20.00,
                                        "payableAmount": 80.00,
                                        "status": "PENDING_PAYMENT",
                                        "createdAt": "2025-01-01T00:00:00",
                                        "updatedAt": "2025-01-01T00:00:00",
                                        "items": [
                                          {
                                            "id": 100,
                                            "productId": 1,
                                            "productNo": "prd_001",
                                            "productName": "Demo Product 001",
                                            "unitPrice": 100.00,
                                            "quantity": 1,
                                            "lineAmount": 100.00
                                          }
                                        ]
                                      }
                                    }
                                    """))),
            @io.swagger.v3.oas.annotations.responses.ApiResponse(
                    responseCode = "400", description = "Request body or parameter validation failed.",
                    content = @Content(mediaType = "application/json",
                            schema = @Schema(implementation = ApiResponse.class),
                            examples = @ExampleObject(name = "invalidParameter", value = """
                                    {"success":false,"code":"ORDER_PARAM_INVALID","message":"request parameter invalid","data":null}
                                    """))),
            @io.swagger.v3.oas.annotations.responses.ApiResponse(
                    responseCode = "404", description = "Referenced user, product, or coupon template does not exist.",
                    content = @Content(mediaType = "application/json",
                            schema = @Schema(implementation = ApiResponse.class),
                            examples = @ExampleObject(name = "missingUser", value = """
                                    {"success":false,"code":"ORDER_RESOURCE_NOT_FOUND","message":"user id 999 not found","data":null}
                                    """))),
            @io.swagger.v3.oas.annotations.responses.ApiResponse(
                    responseCode = "409", description = "Order creation conflicts with product status, inventory, duplicate lines, or coupon availability.",
                    content = @Content(mediaType = "application/json",
                            schema = @Schema(implementation = ApiResponse.class),
                            examples = @ExampleObject(name = "insufficientInventory", value = """
                                    {"success":false,"code":"ORDER_BUSINESS_CONFLICT","message":"insufficient inventory for product id 10","data":null}
                                    """))),
            @io.swagger.v3.oas.annotations.responses.ApiResponse(
                    responseCode = "500", description = "Unexpected server failure.",
                    content = @Content(mediaType = "application/json",
                            schema = @Schema(implementation = ApiResponse.class),
                            examples = @ExampleObject(name = "systemError", value = """
                                    {"success":false,"code":"ORDER_SYSTEM_ERROR","message":"internal server error","data":null}
                                    """)))
    })
    @PostMapping
    ApiResponse<OrderDetailVO> createOrder(
            @io.swagger.v3.oas.annotations.parameters.RequestBody(
                    description = "Order owner, distinct product lines, and an optional coupon template id.",
                    required = true,
                    content = @Content(mediaType = "application/json",
                            examples = @ExampleObject(name = "createOrderRequest", value = """
                                    {
                                      "userId": 1,
                                      "items": [{"productId": 1, "quantity": 1}],
                                      "couponId": 1
                                    }
                                    """)))
            @Valid @RequestBody CreateOrderRequest request
    ) {
        return ApiResponse.success(createOrderApplicationService.createOrder(request));
    }

    @Operation(
            operationId = "getOrderDetail",
            summary = "Get order details",
            description = "Returns one order with its persisted item snapshots.",
            tags = {"Orders"})
    @ApiResponses({
            @io.swagger.v3.oas.annotations.responses.ApiResponse(
                    responseCode = "200", description = "Order details returned.",
                    content = @Content(mediaType = "application/json",
                            schema = @Schema(implementation = OpenApiSuccessResponses.OrderDetailResponse.class),
                            examples = @ExampleObject(name = "orderDetails", value = """
                                    {
                                      "success": true,
                                      "code": "ORDER_SUCCESS",
                                      "message": "success",
                                      "data": {
                                        "id": 10,
                                        "orderNo": "ord_00000000-0000-4000-8000-000000000001",
                                        "userId": 1,
                                        "originalAmount": 100.00,
                                        "discountAmount": 20.00,
                                        "payableAmount": 80.00,
                                        "status": "PENDING_PAYMENT",
                                        "createdAt": "2025-01-01T00:00:00",
                                        "updatedAt": "2025-01-01T00:00:00",
                                        "items": []
                                      }
                                    }
                                    """))),
            @io.swagger.v3.oas.annotations.responses.ApiResponse(
                    responseCode = "400", description = "Order id must be positive.",
                    content = @Content(mediaType = "application/json",
                            schema = @Schema(implementation = ApiResponse.class),
                            examples = @ExampleObject(name = "invalidOrderId", value = """
                                    {"success":false,"code":"ORDER_PARAM_INVALID","message":"request parameter invalid","data":null}
                                    """))),
            @io.swagger.v3.oas.annotations.responses.ApiResponse(
                    responseCode = "404", description = "Order does not exist.",
                    content = @Content(mediaType = "application/json",
                            schema = @Schema(implementation = ApiResponse.class),
                            examples = @ExampleObject(name = "missingOrder", value = """
                                    {"success":false,"code":"ORDER_RESOURCE_NOT_FOUND","message":"order not found","data":null}
                                    """))),
            @io.swagger.v3.oas.annotations.responses.ApiResponse(
                    responseCode = "500", description = "Unexpected server failure.",
                    content = @Content(mediaType = "application/json",
                            schema = @Schema(implementation = ApiResponse.class),
                            examples = @ExampleObject(name = "systemError", value = """
                                    {"success":false,"code":"ORDER_SYSTEM_ERROR","message":"internal server error","data":null}
                                    """)))
    })
    @GetMapping("/{orderId}")
    ApiResponse<OrderDetailVO> queryOrder(
            @Parameter(description = "Order primary key.", example = "10",
                    schema = @Schema(type = "integer", format = "int64", minimum = "1"))
            @PathVariable @Positive Long orderId
    ) {
        return ApiResponse.success(orderApplicationService.queryDetail(orderId));
    }

    @Operation(
            operationId = "cancelOrder",
            summary = "Cancel an order",
            description = "Applies the fixed CANCEL event and returns the resulting order details.",
            tags = {"Orders"})
    @ApiResponses({
            @io.swagger.v3.oas.annotations.responses.ApiResponse(
                    responseCode = "200", description = "Order cancelled or already in the resulting state.",
                    content = @Content(mediaType = "application/json",
                            schema = @Schema(implementation = OpenApiSuccessResponses.OrderDetailResponse.class),
                            examples = @ExampleObject(name = "cancelledOrder", value = """
                                    {
                                      "success": true,
                                      "code": "ORDER_SUCCESS",
                                      "message": "success",
                                      "data": {
                                        "id": 10,
                                        "orderNo": "ord_00000000-0000-4000-8000-000000000001",
                                        "userId": 1,
                                        "originalAmount": 100.00,
                                        "discountAmount": 20.00,
                                        "payableAmount": 80.00,
                                        "status": "CANCELLED",
                                        "createdAt": "2025-01-01T00:00:00",
                                        "updatedAt": "2025-01-01T00:00:00",
                                        "items": []
                                      }
                                    }
                                    """))),
            @io.swagger.v3.oas.annotations.responses.ApiResponse(
                    responseCode = "400", description = "Order id must be positive.",
                    content = @Content(mediaType = "application/json",
                            schema = @Schema(implementation = ApiResponse.class),
                            examples = @ExampleObject(name = "invalidOrderId", value = """
                                    {"success":false,"code":"ORDER_PARAM_INVALID","message":"request parameter invalid","data":null}
                                    """))),
            @io.swagger.v3.oas.annotations.responses.ApiResponse(
                    responseCode = "404", description = "Order does not exist.",
                    content = @Content(mediaType = "application/json",
                            schema = @Schema(implementation = ApiResponse.class),
                            examples = @ExampleObject(name = "missingOrder", value = """
                                    {"success":false,"code":"ORDER_RESOURCE_NOT_FOUND","message":"order not found","data":null}
                                    """))),
            @io.swagger.v3.oas.annotations.responses.ApiResponse(
                    responseCode = "409", description = "Order state cannot transition to CANCELLED.",
                    content = @Content(mediaType = "application/json",
                            schema = @Schema(implementation = ApiResponse.class),
                            examples = @ExampleObject(name = "orderStatusConflict", value = """
                                    {"success":false,"code":"ORDER_BUSINESS_CONFLICT","message":"order status conflict","data":null}
                                    """))),
            @io.swagger.v3.oas.annotations.responses.ApiResponse(
                    responseCode = "500", description = "Unexpected server failure.",
                    content = @Content(mediaType = "application/json",
                            schema = @Schema(implementation = ApiResponse.class),
                            examples = @ExampleObject(name = "systemError", value = """
                                    {"success":false,"code":"ORDER_SYSTEM_ERROR","message":"internal server error","data":null}
                                    """)))
    })
    @PostMapping("/{orderId}/cancel")
    ApiResponse<OrderDetailVO> cancelOrder(
            @Parameter(description = "Order primary key.", example = "10",
                    schema = @Schema(type = "integer", format = "int64", minimum = "1"))
            @PathVariable @Positive Long orderId
    ) {
        orderApplicationService.transition(orderId, OrderEvent.CANCEL);
        return ApiResponse.success(orderApplicationService.queryDetail(orderId));
    }
}
