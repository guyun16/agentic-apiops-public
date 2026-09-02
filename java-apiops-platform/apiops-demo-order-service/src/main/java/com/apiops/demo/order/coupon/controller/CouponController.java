package com.apiops.demo.order.coupon.controller;

import com.apiops.demo.order.common.exception.DemoOrderErrorCode;
import com.apiops.demo.order.common.web.ApiResponse;
import com.apiops.demo.order.coupon.application.CouponApplicationService;
import com.apiops.demo.order.coupon.dto.UserCouponQuery;
import com.apiops.demo.order.coupon.vo.CouponVO;
import com.apiops.demo.order.coupon.vo.UserCouponVO;
import com.apiops.demo.order.openapi.OpenApiSuccessResponses;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.Parameter;
import io.swagger.v3.oas.annotations.media.Content;
import io.swagger.v3.oas.annotations.media.ExampleObject;
import io.swagger.v3.oas.annotations.media.Schema;
import io.swagger.v3.oas.annotations.responses.ApiResponses;
import jakarta.validation.Valid;
import jakarta.validation.constraints.Min;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.validation.annotation.Validated;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.ModelAttribute;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;
import jakarta.validation.ConstraintViolationException;

import java.util.List;

@Validated
@RestController
@RequestMapping
public class CouponController {

    private final CouponApplicationService couponApplicationService;

    public CouponController(CouponApplicationService couponApplicationService) {
        this.couponApplicationService = couponApplicationService;
    }

    @Operation(
            operationId = "getCoupon",
            summary = "Get a coupon template",
            description = "Returns one coupon template by its primary key.",
            tags = {"Coupons"})
    @ApiResponses({
            @io.swagger.v3.oas.annotations.responses.ApiResponse(
                    responseCode = "200", description = "Coupon template returned.",
                    content = @Content(mediaType = "application/json",
                            schema = @Schema(implementation = OpenApiSuccessResponses.CouponResponse.class),
                            examples = @ExampleObject(name = "couponTemplate", value = """
                                    {
                                      "success": true,
                                      "code": "ORDER_SUCCESS",
                                      "message": "success",
                                      "data": {
                                        "id": 1,
                                        "couponNo": "cpn_001",
                                        "couponName": "100 minus 20",
                                        "thresholdAmount": 100.00,
                                        "discountAmount": 20.00,
                                        "validFrom": "2020-01-01T00:00:00",
                                        "validUntil": "2099-12-31T23:59:59.999",
                                        "status": "ACTIVE",
                                        "createdAt": "2025-01-01T00:00:00",
                                        "updatedAt": "2025-01-01T00:00:00"
                                      }
                                    }
                                    """))),
            @io.swagger.v3.oas.annotations.responses.ApiResponse(
                    responseCode = "400", description = "Coupon id must be at least 1.",
                    content = @Content(mediaType = "application/json",
                            schema = @Schema(implementation = ApiResponse.class),
                            examples = @ExampleObject(name = "invalidParameter", value = """
                                    {"success":false,"code":"ORDER_PARAM_INVALID","message":"request parameter invalid","data":null}
                                    """))),
            @io.swagger.v3.oas.annotations.responses.ApiResponse(
                    responseCode = "404", description = "Coupon template does not exist.",
                    content = @Content(mediaType = "application/json",
                            schema = @Schema(implementation = ApiResponse.class),
                            examples = @ExampleObject(name = "missingCoupon", value = """
                                    {"success":false,"code":"ORDER_RESOURCE_NOT_FOUND","message":"coupon id 999 not found","data":null}
                                    """))),
            @io.swagger.v3.oas.annotations.responses.ApiResponse(
                    responseCode = "500", description = "Unexpected server failure.",
                    content = @Content(mediaType = "application/json",
                            schema = @Schema(implementation = ApiResponse.class),
                            examples = @ExampleObject(name = "systemError", value = """
                                    {"success":false,"code":"ORDER_SYSTEM_ERROR","message":"internal server error","data":null}
                                    """)))
    })
    @GetMapping("/coupons/{couponId}")
    ApiResponse<CouponVO> queryCoupon(
            @Parameter(description = "Coupon template primary key.", example = "1",
                    schema = @Schema(type = "integer", format = "int64", minimum = "1"))
            @PathVariable @Min(1) Long couponId) {
        return ApiResponse.success(couponApplicationService.queryCouponById(couponId));
    }

    @Operation(
            operationId = "claimCoupon",
            summary = "Claim a coupon",
            description = "Creates a user-coupon instance for an enabled user and an active, currently valid coupon template.",
            tags = {"Coupons"})
    @ApiResponses({
            @io.swagger.v3.oas.annotations.responses.ApiResponse(
                    responseCode = "200", description = "Coupon claimed.",
                    content = @Content(mediaType = "application/json",
                            schema = @Schema(implementation = OpenApiSuccessResponses.UserCouponResponse.class),
                            examples = @ExampleObject(name = "claimedCoupon", value = """
                                    {
                                      "success": true,
                                      "code": "ORDER_SUCCESS",
                                      "message": "success",
                                      "data": {
                                        "id": 10,
                                        "userCouponNo": "ucp_001",
                                        "userId": 1,
                                        "couponId": 1,
                                        "status": "AVAILABLE",
                                        "receivedAt": "2025-01-01T00:00:00",
                                        "usedAt": null,
                                        "createdAt": "2025-01-01T00:00:00",
                                        "updatedAt": "2025-01-01T00:00:00",
                                        "coupon": {
                                          "id": 1,
                                          "couponNo": "cpn_001",
                                          "couponName": "100 minus 20",
                                          "thresholdAmount": 100.00,
                                          "discountAmount": 20.00,
                                          "validFrom": "2020-01-01T00:00:00",
                                          "validUntil": "2099-12-31T23:59:59.999",
                                          "status": "ACTIVE",
                                          "createdAt": "2025-01-01T00:00:00",
                                          "updatedAt": "2025-01-01T00:00:00"
                                        }
                                      }
                                    }
                                    """))),
            @io.swagger.v3.oas.annotations.responses.ApiResponse(
                    responseCode = "400", description = "User or coupon id is invalid.",
                    content = @Content(mediaType = "application/json",
                            schema = @Schema(implementation = ApiResponse.class),
                            examples = @ExampleObject(name = "invalidParameter", value = """
                                    {"success":false,"code":"ORDER_PARAM_INVALID","message":"request parameter invalid","data":null}
                                    """))),
            @io.swagger.v3.oas.annotations.responses.ApiResponse(
                    responseCode = "404", description = "User or coupon template does not exist.",
                    content = @Content(mediaType = "application/json",
                            schema = @Schema(implementation = ApiResponse.class),
                            examples = @ExampleObject(name = "missingUser", value = """
                                    {"success":false,"code":"ORDER_RESOURCE_NOT_FOUND","message":"user id 999 not found","data":null}
                                    """))),
            @io.swagger.v3.oas.annotations.responses.ApiResponse(
                    responseCode = "409", description = "The user is ineligible, the template is inactive/out of validity, or the user already claimed it.",
                    content = @Content(mediaType = "application/json",
                            schema = @Schema(implementation = ApiResponse.class),
                            examples = @ExampleObject(name = "duplicateClaim", value = """
                                    {"success":false,"code":"ORDER_BUSINESS_CONFLICT","message":"user 1 already claimed coupon 1","data":null}
                                    """))),
            @io.swagger.v3.oas.annotations.responses.ApiResponse(
                    responseCode = "500", description = "Unexpected server failure.",
                    content = @Content(mediaType = "application/json",
                            schema = @Schema(implementation = ApiResponse.class),
                            examples = @ExampleObject(name = "systemError", value = """
                                    {"success":false,"code":"ORDER_SYSTEM_ERROR","message":"internal server error","data":null}
                                    """)))
    })
    @PostMapping("/users/{userId}/coupons/{couponId}")
    ApiResponse<UserCouponVO> claimCoupon(
            @Parameter(description = "User primary key.", example = "1",
                    schema = @Schema(type = "integer", format = "int64", minimum = "1"))
            @PathVariable @Min(1) Long userId,
            @Parameter(description = "Coupon template primary key.", example = "1",
                    schema = @Schema(type = "integer", format = "int64", minimum = "1"))
            @PathVariable @Min(1) Long couponId) {
        return ApiResponse.success(couponApplicationService.claimCoupon(userId, couponId));
    }

    @Operation(
            operationId = "listUserCoupons",
            summary = "List a user's coupons",
            description = "Returns the user's claimed coupon instances, optionally filtered by AVAILABLE, USED, or EXPIRED status.",
            tags = {"Coupons"})
    @ApiResponses({
            @io.swagger.v3.oas.annotations.responses.ApiResponse(
                    responseCode = "200", description = "User coupons returned.",
                    content = @Content(mediaType = "application/json",
                            schema = @Schema(implementation = OpenApiSuccessResponses.UserCouponListResponse.class),
                            examples = @ExampleObject(name = "userCoupons", value = """
                                    {
                                      "success": true,
                                      "code": "ORDER_SUCCESS",
                                      "message": "success",
                                      "data": [
                                        {
                                          "id": 10,
                                          "userCouponNo": "ucp_001",
                                          "userId": 1,
                                          "couponId": 1,
                                          "status": "AVAILABLE",
                                          "receivedAt": "2025-01-01T00:00:00",
                                          "usedAt": null,
                                          "createdAt": "2025-01-01T00:00:00",
                                          "updatedAt": "2025-01-01T00:00:00",
                                          "coupon": {
                                            "id": 1,
                                            "couponNo": "cpn_001",
                                            "couponName": "100 minus 20",
                                            "thresholdAmount": 100.00,
                                            "discountAmount": 20.00,
                                            "validFrom": "2020-01-01T00:00:00",
                                            "validUntil": "2099-12-31T23:59:59.999",
                                            "status": "ACTIVE",
                                            "createdAt": "2025-01-01T00:00:00",
                                            "updatedAt": "2025-01-01T00:00:00"
                                          }
                                        }
                                      ]
                                    }
                                    """))),
            @io.swagger.v3.oas.annotations.responses.ApiResponse(
                    responseCode = "400", description = "User id or status filter is invalid.",
                    content = @Content(mediaType = "application/json",
                            schema = @Schema(implementation = ApiResponse.class),
                            examples = @ExampleObject(name = "invalidStatus", value = """
                                    {"success":false,"code":"ORDER_PARAM_INVALID","message":"request parameter invalid","data":null}
                                    """))),
            @io.swagger.v3.oas.annotations.responses.ApiResponse(
                    responseCode = "404", description = "User does not exist.",
                    content = @Content(mediaType = "application/json",
                            schema = @Schema(implementation = ApiResponse.class),
                            examples = @ExampleObject(name = "missingUser", value = """
                                    {"success":false,"code":"ORDER_RESOURCE_NOT_FOUND","message":"user id 999 not found","data":null}
                                    """))),
            @io.swagger.v3.oas.annotations.responses.ApiResponse(
                    responseCode = "500", description = "Unexpected server failure.",
                    content = @Content(mediaType = "application/json",
                            schema = @Schema(implementation = ApiResponse.class),
                            examples = @ExampleObject(name = "systemError", value = """
                                    {"success":false,"code":"ORDER_SYSTEM_ERROR","message":"internal server error","data":null}
                                    """)))
    })
    @GetMapping("/users/{userId}/coupons")
    ApiResponse<List<UserCouponVO>> queryUserCoupons(
            @Parameter(description = "User primary key.", example = "1",
                    schema = @Schema(type = "integer", format = "int64", minimum = "1"))
            @PathVariable @Min(1) Long userId,
            @Valid @ModelAttribute UserCouponQuery query) {
        return ApiResponse.success(
                couponApplicationService.queryUserCoupons(userId, query.getStatus()));
    }

    @ExceptionHandler(ConstraintViolationException.class)
    ResponseEntity<ApiResponse<Void>> handleConstraintViolation() {
        return ResponseEntity.status(HttpStatus.BAD_REQUEST)
                .body(ApiResponse.fail(DemoOrderErrorCode.PARAM_INVALID));
    }
}
