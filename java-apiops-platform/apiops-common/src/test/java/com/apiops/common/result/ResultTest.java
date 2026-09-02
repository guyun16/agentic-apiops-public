package com.apiops.common.result;

import com.apiops.common.enums.ErrorCode;
import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

class ResultTest {

    @Test
    void successWithStringData() {
        Result<String> result = Result.success("ok");

        assertTrue(result.isSuccess(), "success result should be true");
        assertEquals(
                ErrorCode.SUCCESS.getCode(),
                result.getCode(),
                "success code should match ErrorCode.SUCCESS"
        );
        assertEquals(
                ErrorCode.SUCCESS.getMessage(),
                result.getMessage(),
                "success message should match ErrorCode.SUCCESS"
        );
        assertEquals("ok", result.getData(), "data should be ok");
    }

    @Test
    void successWithCustomData() {
        Result<SampleData> result =
                Result.success(new SampleData("task_001"));

        assertTrue(result.isSuccess(), "success result should be true");
        assertEquals(
                "task_001",
                result.getData().getTaskId(),
                "taskId should match"
        );
    }

    @Test
    void failWithErrorCode() {
        Result<String> result =
                Result.fail(ErrorCode.PARAM_INVALID);

        assertFalse(result.isSuccess(), "fail result should be false");
        assertEquals(
                ErrorCode.PARAM_INVALID.getCode(),
                result.getCode(),
                "fail code should match ErrorCode.PARAM_INVALID"
        );
        assertEquals(
                ErrorCode.PARAM_INVALID.getMessage(),
                result.getMessage(),
                "fail message should match ErrorCode.PARAM_INVALID"
        );
        assertNull(result.getData(), "fail data should be null");
    }

    @Test
    void failWithCustomMessage() {
        Result<String> result = Result.fail(
                ErrorCode.PARAM_INVALID,
                "pageNo must be greater than 0"
        );

        assertFalse(result.isSuccess(), "fail result should be false");
        assertEquals(
                ErrorCode.PARAM_INVALID.getCode(),
                result.getCode(),
                "fail code should still match ErrorCode.PARAM_INVALID"
        );
        assertEquals(
                "pageNo must be greater than 0",
                result.getMessage(),
                "custom message should be used"
        );
        assertNull(result.getData(), "fail data should be null");
    }

    private static class SampleData {

        private final String taskId;

        private SampleData(String taskId) {
            this.taskId = taskId;
        }

        private String getTaskId() {
            return taskId;
        }
    }
}