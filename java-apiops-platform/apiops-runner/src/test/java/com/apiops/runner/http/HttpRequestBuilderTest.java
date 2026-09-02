package com.apiops.runner.http;

import com.apiops.common.enums.FailureType;
import com.apiops.runner.dsl.RequestSpec;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.Test;

import java.net.http.HttpRequest;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

class HttpRequestBuilderTest {

    private final ObjectMapper mapper = new ObjectMapper();
    private final HttpRequestBuilder builder = new HttpRequestBuilder();

    @Test
    void buildsGetWithEncodedQueryParameters() {
        HttpRequest request = builder.build("https://api.example.test/v1", request(
                "GET", "/orders", Map.of(), Map.of(
                        "q", mapper.valueToTree("a b&c"),
                        "page", mapper.valueToTree(2)), Map.of(), null));

        assertTrue(request.uri().toString().startsWith("https://api.example.test/v1/orders?"));
        assertTrue(request.uri().getRawQuery().contains("q=a%20b%26c"));
        assertTrue(request.uri().getRawQuery().contains("page=2"));
    }

    @Test
    void replacesPathParameterAndEncodesOnePathSegment() {
        HttpRequest request = builder.build("https://api.example.test", request(
                "GET", "/orders/{orderId}",
                Map.of("orderId", mapper.valueToTree("a/b c")),
                Map.of(), Map.of(), null));

        assertEquals("https://api.example.test/orders/a%2Fb%20c", request.uri().toString());
    }

    @Test
    void preservesExistingPathEscapeWithoutDoubleEncoding() {
        HttpRequest request = builder.build("https://api.example.test", request(
                "GET", "/files/a%20b/{name}",
                Map.of("name", mapper.valueToTree("x/y")),
                Map.of(), Map.of(), null));

        assertEquals("https://api.example.test/files/a%20b/x%2Fy", request.uri().toString());
    }

    @Test
    void rejectsMissingPathParameter() {
        HttpRequestBuildException exception = assertThrows(
                HttpRequestBuildException.class,
                () -> builder.build("https://api.example.test", request(
                        "GET", "/orders/{orderId}", Map.of(), Map.of(), Map.of(), null)));

        assertEquals(FailureType.REQUEST_BUILD_ERROR, exception.failureType());
    }

    @Test
    void rejectsUnusedPathParameter() {
        HttpRequestBuildException exception = assertThrows(
                HttpRequestBuildException.class,
                () -> builder.build("https://api.example.test", request(
                        "GET", "/orders", Map.of("orderId", mapper.valueToTree("1")),
                        Map.of(), Map.of(), null)));

        assertEquals(FailureType.REQUEST_BUILD_ERROR, exception.failureType());
    }

    @Test
    void buildsJsonBodyAndPreservesHeaderValues() throws Exception {
        HttpRequest request = builder.build("https://api.example.test", request(
                "POST", "/orders", Map.of(), Map.of(),
                Map.of("Content-Type", "application/json", "Authorization", "Bearer secret"),
                mapper.readTree("{\"quantity\":1}")));

        assertEquals("POST", request.method());
        assertEquals("application/json", request.headers().firstValue("Content-Type").orElseThrow());
        assertEquals("Bearer secret", request.headers().firstValue("Authorization").orElseThrow());
        assertEquals(14L, request.bodyPublisher().orElseThrow().contentLength());
    }

    private RequestSpec request(
            String method,
            String path,
            Map<String, com.fasterxml.jackson.databind.JsonNode> pathParams,
            Map<String, com.fasterxml.jackson.databind.JsonNode> query,
            Map<String, String> headers,
            com.fasterxml.jackson.databind.JsonNode body) {
        return new RequestSpec(method, path, pathParams, query, headers, body);
    }
}
