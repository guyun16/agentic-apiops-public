package com.apiops.demo.order.common.web;

import com.apiops.demo.order.common.exception.DemoOrderErrorCode;
import io.swagger.v3.oas.annotations.media.Schema;

import java.util.Objects;

@Schema(description = "Common response envelope used by every demo-order-service HTTP endpoint.")
public class ApiResponse<T> {

    @Schema(description = "Whether the request completed successfully.", example = "true",
            requiredMode = Schema.RequiredMode.REQUIRED)
    private final boolean success;
    @Schema(description = "Stable business result code.", example = "ORDER_SUCCESS",
            requiredMode = Schema.RequiredMode.REQUIRED)
    private final String code;
    @Schema(description = "Human-readable result message.", example = "success",
            requiredMode = Schema.RequiredMode.REQUIRED)
    private final String message;
    @Schema(description = "Endpoint-specific response data. It is null for error responses.",
            nullable = true)
    private final T data;

    private ApiResponse(boolean success, String code, String message, T data) {
        this.success = success;
        this.code = code;
        this.message = message;
        this.data = data;
    }

    public static <T> ApiResponse<T> success(T data) {
        return new ApiResponse<>(
                true,
                DemoOrderErrorCode.SUCCESS.getCode(),
                DemoOrderErrorCode.SUCCESS.getMessage(),
                data
        );
    }

    public static <T> ApiResponse<T> fail(DemoOrderErrorCode errorCode) {
        DemoOrderErrorCode requiredErrorCode = requireFailureErrorCode(errorCode);
        return new ApiResponse<>(
                false,
                requiredErrorCode.getCode(),
                requiredErrorCode.getMessage(),
                null
        );
    }

    public static <T> ApiResponse<T> fail(
            DemoOrderErrorCode errorCode,
            String safeMessage
    ) {
        DemoOrderErrorCode requiredErrorCode = requireFailureErrorCode(errorCode);
        return new ApiResponse<>(
                false,
                requiredErrorCode.getCode(),
                Objects.requireNonNull(safeMessage, "safeMessage must not be null"),
                null
        );
    }

    public boolean isSuccess() {
        return success;
    }

    public String getCode() {
        return code;
    }

    public String getMessage() {
        return message;
    }

    public T getData() {
        return data;
    }

    private static DemoOrderErrorCode requireFailureErrorCode(
            DemoOrderErrorCode errorCode
    ) {
        DemoOrderErrorCode requiredErrorCode = Objects.requireNonNull(
                errorCode,
                "errorCode must not be null"
        );
        if (requiredErrorCode == DemoOrderErrorCode.SUCCESS) {
            throw new IllegalArgumentException("SUCCESS cannot be used for a failure response");
        }
        return requiredErrorCode;
    }
}
