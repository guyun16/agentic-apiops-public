package com.apiops.common.tool;

import com.apiops.common.enums.ErrorCode;
import com.apiops.common.enums.ToolStatus;
import org.junit.jupiter.api.Test;

import java.util.HashMap;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

public class ToolResultTest {

    @Test
    void shouldCreateSuccessStringToolResult() {
        ToolResult<String> result = ToolResult.success(
                "REDIS_GET",
                "tool_call_001",
                "value_001"
        );

        assertTrue(result.isSuccess(), "success should be true");
        assertEquals(ToolStatus.SUCCESS, result.getStatus(), "status should be success");
        assertEquals("REDIS_GET", result.getToolName(), "toolName should match");
        assertEquals("tool_call_001", result.getToolCallId(), "toolCallId should match");
        assertEquals(ErrorCode.SUCCESS.getCode(), result.getCode(), "code should be success code");
        assertEquals(ErrorCode.SUCCESS.getMessage(), result.getMessage(), "message should be success message");

        String data = result.getData();
        assertEquals("value_001", data, "data should match");
    }

    @Test
    void shouldCreateSuccessMapToolResult() {
        Map<String, Object> row = new HashMap<>();
        row.put("id", "order_001");
        row.put("status", "CREATED");

        ToolResult<Map<String, Object>> result = ToolResult.success(
                "SQL_READ",
                "tool_call_002",
                row
        );

        assertTrue(result.isSuccess(), "success should be true");
        assertEquals("SQL_READ", result.getToolName(), "toolName should match");
        assertEquals("tool_call_002", result.getToolCallId(), "toolCallId should match");

        Map<String, Object> data = result.getData();
        assertEquals("order_001", data.get("id"), "id should match");
        assertEquals("CREATED", data.get("status"), "status should match");
    }

    @Test
    void shouldCreateFailedToolResult() {
        ToolResult<String> result = ToolResult.fail(
                "SQL_READ",
                "tool_call_003",
                ErrorCode.TOOL_CALL_FAILED
        );

        assertFalse(result.isSuccess(), "success should be false");
        assertEquals(ToolStatus.FAILED, result.getStatus(), "status should be failed");
        assertEquals("SQL_READ", result.getToolName(), "toolName should match");
        assertEquals("tool_call_003", result.getToolCallId(), "toolCallId should match");
        assertEquals(ErrorCode.TOOL_CALL_FAILED.getCode(), result.getCode(), "code should match");
        assertEquals(ErrorCode.TOOL_CALL_FAILED.getMessage(), result.getMessage(), "message should match");
        assertNull(result.getData(), "failed result data should be null");
    }

    @Test
    void shouldCreateFailedToolResultWithCustomMessage() {
        ToolResult<String> result = ToolResult.fail(
                "LOG_SEARCH",
                "tool_call_004",
                ErrorCode.TOOL_CALL_FAILED,
                "log search failed because timeout"
        );

        assertFalse(result.isSuccess(), "success should be false");
        assertEquals(ToolStatus.FAILED, result.getStatus(), "status should be failed");
        assertEquals("LOG_SEARCH", result.getToolName(), "toolName should match");
        assertEquals("tool_call_004", result.getToolCallId(), "toolCallId should match");
        assertEquals(ErrorCode.TOOL_CALL_FAILED.getCode(), result.getCode(), "code should match");
        assertEquals("log search failed because timeout", result.getMessage(), "custom message should match");
        assertNull(result.getData(), "failed result data should be null");
    }

    @Test
    void supportsEveryExistingStableToolStatus() {
        for (ToolStatus status : ToolStatus.values()) {
            ToolResult<String> result = ToolResult.ofStatus(
                    "SQL_READ", "tool_call_status", status, null);

            assertEquals(status, result.getStatus(), "status should round-trip");
            assertEquals(status == ToolStatus.SUCCESS, result.isSuccess(),
                    "only SUCCESS should be successful");
        }

        assertEquals(ToolStatus.PARAM_INVALID,
                ToolResult.fail("SQL_READ", "tool_call_invalid", ErrorCode.PARAM_INVALID)
                        .getStatus());
        assertEquals(ToolStatus.RESULT_INVALID,
                ToolResult.fail("SQL_READ", "tool_call_invalid", ErrorCode.TOOL_RESULT_INVALID)
                        .getStatus());
    }

}
