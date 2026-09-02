package com.apiops.common.collection;

import org.junit.jupiter.api.Test;

import java.util.ArrayList;
import java.util.List;

import static org.junit.jupiter.api.Assertions.assertEquals;

public class ListBehaviorTest {

    @Test
    void testListKeepsOrder() {
        List<String> steps = new ArrayList<>();

        steps.add("read_openapi");
        steps.add("generate_testcase");
        steps.add("validate_testcase");
        steps.add("submit_runner");

        assertEquals("read_openapi", steps.get(0), "first step should be read_openapi");
        assertEquals("generate_testcase", steps.get(1), "second step should be generate_testcase");
        assertEquals("validate_testcase", steps.get(2), "third step should be validate_testcase");
        assertEquals("submit_runner", steps.get(3), "fourth step should be submit_runner");
    }

    @Test
    void testListAllowsDuplicate() {
        List<String> errorCodes = new ArrayList<>();

        errorCodes.add("A0001");
        errorCodes.add("A0001");

        assertEquals(2, errorCodes.size(), "List should allow duplicate values");
    }

    @Test
    void testArrayListAccessByIndex() {
        List<String> assertionTypes = new ArrayList<>();

        assertionTypes.add("STATUS_CODE");
        assertionTypes.add("JSON_PATH_EQUALS");
        assertionTypes.add("RESPONSE_TIME_LESS_THAN");

        assertEquals("JSON_PATH_EQUALS", assertionTypes.get(1), "ArrayList should support index access");
    }

}
