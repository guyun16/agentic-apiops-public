package com.apiops.demo.order.openapi;

import com.apiops.demo.order.coupon.vo.CouponVO;
import com.apiops.demo.order.coupon.vo.UserCouponVO;
import com.apiops.demo.order.order.vo.OrderDetailVO;
import com.apiops.demo.order.payment.vo.PaymentCallbackResultVO;
import com.apiops.demo.order.product.vo.ProductPageVO;
import com.apiops.demo.order.product.vo.ProductVO;
import com.apiops.demo.order.user.vo.UserVO;
import io.swagger.v3.oas.annotations.media.Schema;

import java.util.List;

/** Concrete documentation-only views for the runtime {@code ApiResponse<T>} envelope. */
public final class OpenApiSuccessResponses {

    private OpenApiSuccessResponses() {
    }

    public record OrderDetailResponse(
            @Schema(requiredMode = Schema.RequiredMode.REQUIRED, example = "true") boolean success,
            @Schema(requiredMode = Schema.RequiredMode.REQUIRED, example = "ORDER_SUCCESS") String code,
            @Schema(requiredMode = Schema.RequiredMode.REQUIRED, example = "success") String message,
            @Schema(requiredMode = Schema.RequiredMode.REQUIRED) OrderDetailVO data) {
    }

    public record ProductResponse(
            @Schema(requiredMode = Schema.RequiredMode.REQUIRED, example = "true") boolean success,
            @Schema(requiredMode = Schema.RequiredMode.REQUIRED, example = "ORDER_SUCCESS") String code,
            @Schema(requiredMode = Schema.RequiredMode.REQUIRED, example = "success") String message,
            @Schema(requiredMode = Schema.RequiredMode.REQUIRED) ProductVO data) {
    }

    public record ProductPageResponse(
            @Schema(requiredMode = Schema.RequiredMode.REQUIRED, example = "true") boolean success,
            @Schema(requiredMode = Schema.RequiredMode.REQUIRED, example = "ORDER_SUCCESS") String code,
            @Schema(requiredMode = Schema.RequiredMode.REQUIRED, example = "success") String message,
            @Schema(requiredMode = Schema.RequiredMode.REQUIRED) ProductPageVO data) {
    }

    public record CouponResponse(
            @Schema(requiredMode = Schema.RequiredMode.REQUIRED, example = "true") boolean success,
            @Schema(requiredMode = Schema.RequiredMode.REQUIRED, example = "ORDER_SUCCESS") String code,
            @Schema(requiredMode = Schema.RequiredMode.REQUIRED, example = "success") String message,
            @Schema(requiredMode = Schema.RequiredMode.REQUIRED) CouponVO data) {
    }

    public record UserCouponResponse(
            @Schema(requiredMode = Schema.RequiredMode.REQUIRED, example = "true") boolean success,
            @Schema(requiredMode = Schema.RequiredMode.REQUIRED, example = "ORDER_SUCCESS") String code,
            @Schema(requiredMode = Schema.RequiredMode.REQUIRED, example = "success") String message,
            @Schema(requiredMode = Schema.RequiredMode.REQUIRED) UserCouponVO data) {
    }

    public record UserCouponListResponse(
            @Schema(requiredMode = Schema.RequiredMode.REQUIRED, example = "true") boolean success,
            @Schema(requiredMode = Schema.RequiredMode.REQUIRED, example = "ORDER_SUCCESS") String code,
            @Schema(requiredMode = Schema.RequiredMode.REQUIRED, example = "success") String message,
            @Schema(requiredMode = Schema.RequiredMode.REQUIRED) List<UserCouponVO> data) {
    }

    public record UserResponse(
            @Schema(requiredMode = Schema.RequiredMode.REQUIRED, example = "true") boolean success,
            @Schema(requiredMode = Schema.RequiredMode.REQUIRED, example = "ORDER_SUCCESS") String code,
            @Schema(requiredMode = Schema.RequiredMode.REQUIRED, example = "success") String message,
            @Schema(requiredMode = Schema.RequiredMode.REQUIRED) UserVO data) {
    }

    public record PaymentCallbackResponse(
            @Schema(requiredMode = Schema.RequiredMode.REQUIRED, example = "true") boolean success,
            @Schema(requiredMode = Schema.RequiredMode.REQUIRED, example = "ORDER_SUCCESS") String code,
            @Schema(requiredMode = Schema.RequiredMode.REQUIRED, example = "success") String message,
            @Schema(requiredMode = Schema.RequiredMode.REQUIRED) PaymentCallbackResultVO data) {
    }

    public record SlowSqlResponse(
            @Schema(requiredMode = Schema.RequiredMode.REQUIRED, example = "true") boolean success,
            @Schema(requiredMode = Schema.RequiredMode.REQUIRED, example = "ORDER_SUCCESS") String code,
            @Schema(requiredMode = Schema.RequiredMode.REQUIRED, example = "success") String message,
            @Schema(requiredMode = Schema.RequiredMode.REQUIRED) SlowSqlData data) {
    }

    public record SlowSqlData(
            @Schema(requiredMode = Schema.RequiredMode.REQUIRED, example = "500", minimum = "100", maximum = "2000")
            int requestedDelayMs,
            @Schema(requiredMode = Schema.RequiredMode.REQUIRED, example = "501", format = "int64")
            long elapsedMs) {
    }
}
