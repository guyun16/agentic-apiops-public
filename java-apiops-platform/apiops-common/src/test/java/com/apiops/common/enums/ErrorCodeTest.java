package com.apiops.common.enums;

import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertEquals;

public class ErrorCodeTest {

    @Test
    void shouldExposeSuccessCodeAndMessage() {
        assertEquals("00000", ErrorCode.SUCCESS.getCode());
        assertEquals("success", ErrorCode.SUCCESS.getMessage());
    }

    @Test
    void shouldExposeParamInvalidCodeAndMessage() {
        assertEquals("A0001", ErrorCode.PARAM_INVALID.getCode());
        assertEquals("request parameter invalid", ErrorCode.PARAM_INVALID.getMessage());
    }

    @Test
    void shouldExposeErrorCodeThroughBaseEnum() {
        BaseEnum baseEnum = ErrorCode.TOOL_CALL_FAILED;
        assertEquals("C0001", baseEnum.getCode());
    }
}
