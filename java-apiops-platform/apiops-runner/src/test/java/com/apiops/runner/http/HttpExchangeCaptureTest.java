package com.apiops.runner.http;

import com.apiops.runner.dsl.RequestSpec;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.Test;

import java.util.List;
import java.util.Map;
import java.util.LinkedHashMap;

import static org.junit.jupiter.api.Assertions.*;

class HttpExchangeCaptureTest {
    private final ObjectMapper json = new ObjectMapper();

    @Test
    void capturesBuiltRequestAndResponseWithoutChangingTheirOriginalValues() throws Exception {
        var body = json.readTree("{\"password\":123456,\"name\":\"private-name\",\"count\":3}");
        var spec = new RequestSpec("post", "/users/{id}", Map.of("id", json.valueToTree("private/id*")),
                Map.of("token", json.valueToTree("query-secret")),
                Map.of("Authorization", "Bearer header-secret", "Content-Type", "application/json"), body);
        var request = new HttpRequestBuilder().build("http://localhost:8080", spec);
        var response = new HttpResponseSnapshot(201,
                Map.of("Content-Type", List.of("application/json"), "Set-Cookie", List.of("session=secret")),
                "{\"access_token\":\"response-secret\",\"nested\":{\"ok\":true,\"note\":\"Bearer arbitrary-secret\"}}", 19);

        var exchange = HttpExchangeCapture.capture(request, spec, response);
        assertNotNull(exchange);
        assertEquals("POST", exchange.request().method());
        assertEquals("http://localhost:8080/users/[REDACTED]?token=[REDACTED]", exchange.request().url());
        assertEquals(201, exchange.response().statusCode());
        assertTrue(exchange.request().body().contains("\"count\":3"));
        assertTrue(exchange.response().body().contains("\"ok\":true"));
        String stored = json.writeValueAsString(exchange);
        for (String secret : List.of("123456", "private-name", "query-secret", "header-secret", "session=secret", "response-secret", "arbitrary-secret")) {
            assertFalse(stored.contains(secret), secret);
        }
        assertTrue(response.body().contains("response-secret"));
        assertEquals("Bearer header-secret", request.headers().firstValue("Authorization").orElseThrow());
        assertEquals(123456, body.get("password").intValue());
    }

    @Test
    void omitsBinaryPlaintextAndInvalidJson() {
        for (String type : List.of("image/png", "text/plain", "application/json")) {
            var exchange = capture(type, "not-json-secret");
            assertEquals("omitted", exchange.response().bodyState());
            assertNull(exchange.response().body());
        }
        assertEquals("omitted", capture("application/json", "{\"ok\":true} trailing-secret")
                .response().bodyState());
        assertEquals("null", capture("application/json", "null").response().body());
        assertEquals("captured", capture("application/json", "null").response().bodyState());
    }

    @Test
    void boundsInputOutputAndHeadersAndMarksTruncation() {
        var tooLarge = capture("application/json", "\"" + "x".repeat(70000) + "\"");
        assertTrue(tooLarge.response().truncated());
        assertEquals("omitted", tooLarge.response().bodyState());
        var manyNumbers = capture("application/json", "[" + "123456789,".repeat(2000) + "0]");
        assertTrue(manyNumbers.response().truncated());
        assertEquals(HttpExchangeCapture.MAX_BODY_CHARS, manyNumbers.response().body().length());
        var deeplyNested = capture("application/json", "[".repeat(20) + "123" + "]".repeat(20));
        assertTrue(deeplyNested.response().truncated());
        assertTrue(deeplyNested.response().body().contains("[OMITTED]"));
        assertFalse(deeplyNested.response().body().contains("123"));
        Map<String, String> headers = new LinkedHashMap<>();
        for (int i = 0; i < 100; i++) headers.put("x-test-" + i, "secret");
        var spec = new RequestSpec("GET", "/", null, null, headers, null);
        var bounded = HttpExchangeCapture.capture(new HttpRequestBuilder().build("http://localhost", spec), spec, null);
        assertEquals(32, bounded.request().headers().size());
        assertTrue(bounded.request().truncated());
    }

    @Test
    void missingResponseStillRetainsTheAttemptedRequest() {
        var spec = new RequestSpec("GET", "/health", null, null, null, null);
        var exchange = HttpExchangeCapture.capture(new HttpRequestBuilder().build("http://localhost", spec), spec, null);
        assertNull(exchange.response());
        assertEquals("empty", exchange.request().bodyState());
        assertEquals("http://localhost/health", exchange.request().url());
    }

    @Test
    void stripsUserinfoSensitivePathAndContentTypeParameters() {
        var spec = new RequestSpec("GET", "/token/secret", null, null,
                Map.of("Content-Type", "application/json; password=secret"), null);
        var exchange = HttpExchangeCapture.capture(new HttpRequestBuilder().build("http://user:secret@localhost", spec), spec, null);
        assertEquals("http://localhost/[REDACTED]/[REDACTED]", exchange.request().url());
        assertEquals(List.of("application/json"), exchange.request().headers().get("content-type"));
    }

    private HttpExchangeSnapshot capture(String contentType, String body) {
        var spec = new RequestSpec("GET", "/", null, null, null, null);
        return HttpExchangeCapture.capture(new HttpRequestBuilder().build("http://localhost", spec), spec,
                new HttpResponseSnapshot(200, Map.of("content-type", List.of(contentType)), body, 1));
    }
}
