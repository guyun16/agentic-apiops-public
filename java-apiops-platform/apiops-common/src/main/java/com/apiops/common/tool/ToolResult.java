package com.apiops.common.tool;

import com.apiops.common.enums.ErrorCode;
import com.apiops.common.enums.ToolStatus;

/**
 * Tool-call result model; it records outcomes but does not execute tools.
 */
public class ToolResult<T> {

    private final boolean success;
    private final ToolStatus status;
    private final String toolName;
    private final String toolCallId;
    private final String code;
    private final String message;
    private final T data;

    private ToolResult(ToolStatus status,
                       String toolName,
                       String toolCallId,
                       String code,
                       String message,
                       T data) {
        this.status = java.util.Objects.requireNonNull(status, "status must not be null");
        this.success = status == ToolStatus.SUCCESS;
        this.toolName = toolName;
        this.toolCallId = toolCallId;
        this.code = code;
        this.message = message;
        this.data = data;
    }

    public static <T> ToolResult<T> success(String toolName, String toolCallId, T data) {
        return new ToolResult<>(
                ToolStatus.SUCCESS,
                toolName,
                toolCallId,
                ErrorCode.SUCCESS.getCode(),
                ErrorCode.SUCCESS.getMessage(),
                data
        );
    }

    public static <T> ToolResult<T> fail(String toolName, String toolCallId, ErrorCode errorCode) {
        return fail(toolName, toolCallId, errorCode, errorCode.getMessage());
    }

    public static <T> ToolResult<T> fail(String toolName,
                                         String toolCallId,
                                         ErrorCode errorCode,
                                         String message) {
        return new ToolResult<>(
                statusFor(errorCode),
                toolName,
                toolCallId,
                errorCode.getCode(),
                message,
                null
        );
    }

    /** Creates a result with one of the existing stable ToolStatus values. */
    public static <T> ToolResult<T> ofStatus(String toolName,
                                             String toolCallId,
                                             ToolStatus status,
                                             T data) {
        return new ToolResult<>(
                status,
                toolName,
                toolCallId,
                status.getCode(),
                status.getMessage(),
                data
        );
    }

    private static ToolStatus statusFor(ErrorCode errorCode) {
        return switch (java.util.Objects.requireNonNull(errorCode, "errorCode must not be null")) {
            case PARAM_INVALID -> ToolStatus.PARAM_INVALID;
            case TOOL_RESULT_INVALID -> ToolStatus.RESULT_INVALID;
            case TOOL_CALL_FAILED -> ToolStatus.FAILED;
            default -> ToolStatus.FAILED;
        };
    }

    public boolean isSuccess() {
        return success;
    }

    public ToolStatus getStatus() {
        return status;
    }

    public String getToolName() {
        return toolName;
    }

    public String getToolCallId() {
        return toolCallId;
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
}
