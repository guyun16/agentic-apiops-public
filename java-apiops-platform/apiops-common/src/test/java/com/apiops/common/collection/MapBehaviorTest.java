package com.apiops.common.collection;

import org.junit.jupiter.api.Test;

import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.TreeMap;

import static org.junit.jupiter.api.Assertions.assertEquals;

public class MapBehaviorTest {

    @Test
    void testMapGetByKey() {
        Map<String, String> headers = new HashMap<>();

        headers.put("Content-Type", "application/json");
        headers.put("Authorization", "Bearer token_001");

        assertEquals("application/json", headers.get("Content-Type"), "should get Content-Type value");
        assertEquals("Bearer token_001", headers.get("Authorization"), "should get Authorization value");
    }

    @Test
    void testMapKeyOverwrite() {
        Map<String, String> headers = new HashMap<>();

        headers.put("Content-Type", "application/json");
        headers.put("Content-Type", "text/plain");

        assertEquals("text/plain", headers.get("Content-Type"), "same key should overwrite old value");
        assertEquals(1, headers.size(), "same key should not create new entry");
    }

    @Test
    void testLinkedHashMapKeepsInsertionOrder() {
        Map<String, String> reportFields = new LinkedHashMap<>();

        reportFields.put("runId", "run_001");
        reportFields.put("status", "ASSERTION_FAILED");
        reportFields.put("failureType", "ASSERTION_MISMATCH");

        String joinedKeys = String.join(",", reportFields.keySet());

        assertEquals("runId,status,failureType", joinedKeys, "LinkedHashMap should keep insertion order");
    }

    @Test
    void testTreeMapSortsByKey() {
        Map<String, String> errorMessages = new TreeMap<>();

        errorMessages.put("C0001", "tool call failed");
        errorMessages.put("A0001", "request parameter invalid");
        errorMessages.put("B0001", "task status invalid");

        String joinedKeys = String.join(",", errorMessages.keySet());

        assertEquals("A0001,B0001,C0001", joinedKeys, "TreeMap should sort by key");
    }

}
