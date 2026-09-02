package com.apiops.agent.tool;

import com.apiops.runner.dsl.AssertionType;
import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

class AssertionTypeToolTest {

    private final AssertionTypeTool tool = new AssertionTypeTool();

    @Test
    void allowsExactlyTheStage7AssertionTypes() {
        for (AssertionType type : AssertionType.values()) {
            assertTrue(tool.isAllowedAssertionType(type.name()));
            assertEquals(new AssertionTypeTool.Result(type.name(), true),
                    tool.isAllowedAssertionType(new AssertionTypeTool.Request(type.name())));
        }
        assertFalse(tool.isAllowedAssertionType("UNSUPPORTED"));
        assertFalse(tool.isAllowedAssertionType((String) null));
        assertEquals(new AssertionTypeTool.Result("UNSUPPORTED", false),
                tool.isAllowedAssertionType(new AssertionTypeTool.Request("UNSUPPORTED")));
    }
}
