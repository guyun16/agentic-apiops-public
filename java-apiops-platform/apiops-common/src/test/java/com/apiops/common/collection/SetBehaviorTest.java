package com.apiops.common.collection;

import org.junit.jupiter.api.Test;

import java.util.HashSet;
import java.util.Set;
import java.util.TreeSet;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

public class SetBehaviorTest {

    @Test
    void testHashSetRemovesDuplicate() {
        Set<String> allowedTools = new HashSet<>();

        allowedTools.add("SQL_READ");
        allowedTools.add("LOG_SEARCH");
        allowedTools.add("SQL_READ");

        assertEquals(2, allowedTools.size(), "HashSet should remove duplicate tool names");
    }

    @Test
    void testHashSetContains() {
        Set<String> forbiddenActions = new HashSet<>();

        forbiddenActions.add("SQL_WRITE");
        forbiddenActions.add("REDIS_DELETE");

        assertTrue(forbiddenActions.contains("SQL_WRITE"), "forbiddenActions should contain SQL_WRITE");
        assertFalse(forbiddenActions.contains("SQL_READ"), "forbiddenActions should not contain SQL_READ");
    }

    @Test
    void testTreeSetSortsValues() {
        Set<String> errorCodes = new TreeSet<>();

        errorCodes.add("C0001");
        errorCodes.add("A0001");
        errorCodes.add("B0001");

        String joined = String.join(",", errorCodes);

        assertEquals("A0001,B0001,C0001", joined, "TreeSet should sort values");
    }

}
