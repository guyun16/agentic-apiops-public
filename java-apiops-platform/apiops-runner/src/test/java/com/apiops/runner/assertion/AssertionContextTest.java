package com.apiops.runner.assertion;

import com.fasterxml.jackson.databind.node.TextNode;
import org.junit.jupiter.api.Test;

import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;

class AssertionContextTest {

    @Test
    void preservesResponseFactsAndHeaderMultiplicity() {
        AssertionContext context = new AssertionContext(
                200,
                Map.of("Set-Cookie", List.of("a=1", "b=2")),
                TextNode.valueOf("body"),
                42L);

        assertEquals(200, context.statusCode());
        assertEquals(List.of("a=1", "b=2"), context.headers().get("Set-Cookie"));
        assertEquals(TextNode.valueOf("body"), context.body());
        assertEquals(42L, context.durationMs());
    }
}
