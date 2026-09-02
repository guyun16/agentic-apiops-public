package com.apiops.common.exception;

import com.apiops.common.enums.ErrorCode;
import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;

public class BusinessExceptionTest {

    @Test
    void testDefaultMessage() {
        BusinessException exception = new BusinessException(ErrorCode.PARAM_INVALID);

        assertEquals(ErrorCode.PARAM_INVALID, exception.getErrorCode(), "errorCode should match");
        assertEquals(ErrorCode.PARAM_INVALID.getMessage(), exception.getMessage(), "message should come from errorCode");
    }

    @Test
    void testCustomMessage() {
        BusinessException exception = new BusinessException(
                ErrorCode.PARAM_INVALID,
                "caseId must not be blank"
        );

        assertEquals(ErrorCode.PARAM_INVALID, exception.getErrorCode(), "errorCode should match");
        assertEquals("caseId must not be blank", exception.getMessage(), "message should be custom message");
    }

    @Test
    void testCause() {
        IllegalStateException cause = new IllegalStateException("original cause");

        BusinessException exception = new BusinessException(
                ErrorCode.SYSTEM_ERROR,
                "system error",
                cause
        );

        assertEquals(ErrorCode.SYSTEM_ERROR, exception.getErrorCode(), "errorCode should match");
        assertEquals("system error", exception.getMessage(), "message should be custom message");
        assertEquals(cause, exception.getCause(), "cause should be preserved");
    }

    @Test
    void testThrowAndCatch() {
        BusinessException exception = assertThrows(
                BusinessException.class,
                () -> {
                    throw new BusinessException(ErrorCode.TASK_STATUS_INVALID, "task status invalid");
                }
        );

        assertEquals(ErrorCode.TASK_STATUS_INVALID, exception.getErrorCode(), "errorCode should be preserved after catch");
        assertEquals("task status invalid", exception.getMessage(), "message should be preserved after catch");
    }
}
