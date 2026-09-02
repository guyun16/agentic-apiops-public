package com.apiops.runner.execution;

import com.apiops.runner.assertion.AssertionContext;
import com.apiops.runner.http.HttpResponseSnapshot;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.Test;

import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

class AssertionContextMapperTest {

    @Test
    void mapsAllResponseFactsToAssertionContext() throws Exception {
        HttpResponseSnapshot snapshot = new HttpResponseSnapshot(
                404,
                Map.of("Content-Type", List.of("application/json", "charset=utf-8")),
                "{\"error\":\"missing\"}",
                37L);

        AssertionContext context = new AssertionContextMapper(new ObjectMapper()).map(snapshot);

        assertEquals(404, context.statusCode());
        assertEquals(List.of("application/json", "charset=utf-8"),
                context.headers().get("Content-Type"));
        assertEquals("missing", context.body().get("error").asText());
        assertEquals(37L, context.durationMs());
    }

    @Test
    void keepsNonJsonBodyForNonJsonAwareAssertions() {
        AssertionContext context = new AssertionContextMapper().map(
                new HttpResponseSnapshot(200, Map.of(), "plain text", 4L));

        assertTrue(context.body().isTextual());
        assertEquals("plain text", context.body().asText());
    }
}
