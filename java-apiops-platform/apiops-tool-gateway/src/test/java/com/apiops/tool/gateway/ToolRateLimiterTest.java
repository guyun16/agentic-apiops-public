package com.apiops.tool.gateway;

import org.junit.jupiter.api.Test;

import java.time.Duration;
import java.util.Map;
import java.util.Set;

import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

class ToolRateLimiterTest {

    @Test
    void keyIsUserProjectAndTool() {
        ToolRateLimiter limiter = new ToolRateLimiter(1, Duration.ofMinutes(1));
        ToolDefinition firstTool = new ToolDefinition("safe.read", "test", Map.of());
        ToolDefinition secondTool = new ToolDefinition("other.read", "test", Map.of());

        ToolExecutionContext userOneProjectOne = context(7L, 42L);
        ToolExecutionContext userTwoProjectOne = context(8L, 42L);
        ToolExecutionContext userOneProjectTwo = context(7L, 43L);

        assertTrue(limiter.tryAcquire(userOneProjectOne, firstTool).allowed());
        assertFalse(limiter.tryAcquire(userOneProjectOne, firstTool).allowed());
        assertTrue(limiter.tryAcquire(userTwoProjectOne, firstTool).allowed());
        assertTrue(limiter.tryAcquire(userOneProjectTwo, firstTool).allowed());
        assertTrue(limiter.tryAcquire(userOneProjectOne, secondTool).allowed());
    }

    private static ToolExecutionContext context(long userId, long projectId) {
        return new ToolExecutionContext(
                userId,
                projectId,
                Set.of("TOOL_READ"),
                "tool-call",
                "agent-run"
        );
    }
}
