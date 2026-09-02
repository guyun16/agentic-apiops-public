package com.apiops.common.enums;

import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertEquals;

public class BaseEnumPolymorphismTest {

    @Test
    void shouldUseBaseEnumPolymorphically() {
        BaseEnum item = ErrorCode.PARAM_INVALID;

        assertEquals("A0001", item.getCode());
        assertEquals("request parameter invalid", item.getMessage());
        printEnum(ErrorCode.SYSTEM_ERROR);
    }

    private static void printEnum(BaseEnum item) {
        System.out.println(item.getCode() + " - " + item.getMessage());
    }
}
