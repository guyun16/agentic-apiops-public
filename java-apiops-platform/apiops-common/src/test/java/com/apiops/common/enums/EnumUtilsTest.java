package com.apiops.common.enums;

import com.apiops.common.util.EnumUtils;
import org.junit.jupiter.api.Test;

import java.util.Optional;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

public class EnumUtilsTest {

    @Test
    void testFromCode() {
        TaskStatus status = EnumUtils.fromCode(TaskStatus.class, "RUNNING");
        assertEquals(TaskStatus.RUNNING, status, "TaskStatus RUNNING should be found");
    }

    @Test
    void testFromCodeNotFound() {
        TaskStatus status = EnumUtils.fromCode(TaskStatus.class, "UNKNOWN");
        assertNull(status, "unknown code should return null");
    }

    @Test
    void testFromCodeOptionalFound() {
        Optional<TaskStatus> status = EnumUtils.fromCodeOptional(TaskStatus.class, "SUCCESS");
        assertTrue(status.isPresent(), "SUCCESS should be present");
        assertEquals(TaskStatus.SUCCESS, status.orElse(null), "SUCCESS should map to TaskStatus.SUCCESS");
    }

    @Test
    void testFromCodeOptionalEmpty() {
        Optional<TaskStatus> status = EnumUtils.fromCodeOptional(TaskStatus.class, "UNKNOWN");
        assertTrue(status.isEmpty(), "UNKNOWN should return Optional.empty");
    }

    @Test
    void testToCodeList() {
        java.util.List<String> codes = EnumUtils.toCodeList(TaskStatus.class);

        assertTrue(codes.contains("PENDING"), "codes should contain PENDING");
        assertTrue(codes.contains("RUNNING"), "codes should contain RUNNING");
        assertTrue(codes.contains("SUCCESS"), "codes should contain SUCCESS");
        assertTrue(codes.contains("FAILED"), "codes should contain FAILED");
    }

    @Test
    void testToMessageMap() {
        java.util.Map<String, String> messageMap = EnumUtils.toMessageMap(TaskStatus.class);

        assertEquals("task is pending", messageMap.get("PENDING"), "PENDING message should match");
        assertEquals("task is running", messageMap.get("RUNNING"), "RUNNING message should match");
        assertEquals("task succeeded", messageMap.get("SUCCESS"), "SUCCESS message should match");
        assertEquals("task failed", messageMap.get("FAILED"), "FAILED message should match");
        assertEquals("task timed out", messageMap.get("TIMEOUT"), "TIMEOUT message should match");
        assertEquals("task cancelled", messageMap.get("CANCELLED"), "CANCELLED message should match");
    }

    @Test
    void testNullEnumClassReturnsEmptyCollection() {
        java.util.List<String> codes = EnumUtils.toCodeList(null);
        java.util.Map<String, String> messageMap = EnumUtils.toMessageMap(null);

        assertTrue(codes.isEmpty(), "null enumClass should return empty code list");
        assertTrue(messageMap.isEmpty(), "null enumClass should return empty message map");
    }

}
