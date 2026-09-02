package com.apiops.common.util;

import org.junit.jupiter.api.Test;

import java.time.LocalDateTime;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNull;

public class TimeUtilsTest {

    @Test
    void testFormatShouldUseDefaultPattern() {
        LocalDateTime time = LocalDateTime.of(2026, 7, 2, 10, 30, 15);

        String text = TimeUtils.format(time);

        assertEquals("2026-07-02 10:30:15", text, "formatted time should match default pattern");
    }

    @Test
    void testParseShouldReadDefaultPattern() {
        LocalDateTime time = TimeUtils.parse("2026-07-02 10:30:15");

        assertEquals(2026, time.getYear(), "year should be 2026");
        assertEquals(7, time.getMonthValue(), "month should be 7");
        assertEquals(2, time.getDayOfMonth(), "day should be 2");
        assertEquals(10, time.getHour(), "hour should be 10");
        assertEquals(30, time.getMinute(), "minute should be 30");
        assertEquals(15, time.getSecond(), "second should be 15");
    }

    @Test
    void testFormatNullShouldReturnNull() {
        String text = TimeUtils.format(null);

        assertNull(text, "format null should return null");
    }

    @Test
    void testParseBlankShouldReturnNull() {
        LocalDateTime time = TimeUtils.parse("   ");

        assertNull(time, "parse blank should return null");
    }
}
