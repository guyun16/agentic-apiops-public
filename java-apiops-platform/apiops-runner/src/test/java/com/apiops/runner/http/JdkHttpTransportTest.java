package com.apiops.runner.http;

import com.apiops.common.enums.FailureType;
import com.apiops.runner.dsl.RequestSpec;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.sun.net.httpserver.HttpExchange;
import com.sun.net.httpserver.HttpServer;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

import java.io.IOException;
import java.io.OutputStream;
import java.net.InetSocketAddress;
import java.net.ServerSocket;
import java.net.URI;
import java.net.http.HttpRequest;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.Map;
import java.util.Locale;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

class JdkHttpTransportTest {

    private final ObjectMapper mapper = new ObjectMapper();
    private HttpServer server;
    private URI serverBaseUri;

    @BeforeEach
    void startServer() throws IOException {
        server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        server.createContext("/", this::handle);
        server.start();
        serverBaseUri = URI.create("http://127.0.0.1:" + server.getAddress().getPort());
    }

    @AfterEach
    void stopServer() {
        server.stop(0);
    }

    @Test
    void returnsSnapshotFor200Response() {
        HttpResponseSnapshot snapshot = transport(Duration.ofSeconds(2))
                .execute(request("GET", "/status/200", Map.of(), null));

        assertEquals(200, snapshot.statusCode());
        assertEquals("ok", snapshot.body());
        assertTrue(snapshot.durationMs() >= 0);
        assertNotNull(snapshot.headers());
    }

    @Test
    void returnsSnapshotFor404Response() {
        HttpResponseSnapshot snapshot = transport(Duration.ofSeconds(2))
                .execute(request("GET", "/status/404", Map.of(), null));

        assertEquals(404, snapshot.statusCode());
        assertEquals("not found", snapshot.body());
    }

    @Test
    void returnsSnapshotFor500Response() {
        HttpResponseSnapshot snapshot = transport(Duration.ofSeconds(2))
                .execute(request("GET", "/status/500", Map.of(), null));

        assertEquals(500, snapshot.statusCode());
        assertEquals("server error", snapshot.body());
    }

    @Test
    void sendsPostJsonBodyAndHeaders() throws Exception {
        HttpRequest request = request(
                "POST", "/echo", Map.of(
                        "Content-Type", "application/json",
                        "X-Test", "present"),
                mapper.readTree("{\"quantity\":1}"));

        HttpResponseSnapshot snapshot = transport(Duration.ofSeconds(2)).execute(request);

        assertEquals(200, snapshot.statusCode());
        assertEquals("{\"quantity\":1}", snapshot.body());
        assertEquals("present", snapshot.headers().entrySet().stream()
                .filter(entry -> entry.getKey().toLowerCase(Locale.ROOT)
                        .equals("x-echo-request-header"))
                .findFirst()
                .orElseThrow()
                .getValue()
                .getFirst());
    }

    @Test
    void timeoutDoesNotProduceSnapshot() {
        HttpTransportException exception = assertThrows(
                HttpTransportException.class,
                () -> transport(Duration.ofMillis(50))
                        .execute(request("GET", "/slow", Map.of(), null)));

        assertEquals(FailureType.TIMEOUT, exception.failureType());
    }

    @Test
    void connectionFailureDoesNotProduceSnapshot() throws IOException {
        int unusedPort;
        try (ServerSocket socket = new ServerSocket(0)) {
            unusedPort = socket.getLocalPort();
        }
        HttpRequest request = new HttpRequestBuilder().build(
                "http://127.0.0.1:" + unusedPort,
                new RequestSpec("GET", "/status/200", Map.of(), Map.of(), Map.of(), null));

        HttpTransportException exception = assertThrows(
                HttpTransportException.class,
                () -> transport(Duration.ofSeconds(1)).execute(request));

        assertEquals(FailureType.CONNECT_ERROR, exception.failureType());
    }

    private JdkHttpTransport transport(Duration timeout) {
        return new JdkHttpTransport(timeout);
    }

    private HttpRequest request(
            String method, String path, Map<String, String> headers, JsonNode body) {
        return new HttpRequestBuilder().build(
                serverBaseUri.toString(),
                new RequestSpec(method, path, Map.of(), Map.of(), headers, body));
    }

    private void handle(HttpExchange exchange) throws IOException {
        String path = exchange.getRequestURI().getPath();
        String requestBody = new String(exchange.getRequestBody().readAllBytes(), StandardCharsets.UTF_8);
        if ("/slow".equals(path)) {
            try {
                Thread.sleep(500);
            } catch (InterruptedException exception) {
                Thread.currentThread().interrupt();
                throw new IOException("test server interrupted", exception);
            }
        }
        int status = switch (path) {
            case "/status/200", "/echo", "/slow" -> 200;
            case "/status/404" -> 404;
            case "/status/500" -> 500;
            default -> 404;
        };
        String body = switch (path) {
            case "/status/200", "/slow" -> "ok";
            case "/status/404" -> "not found";
            case "/status/500" -> "server error";
            case "/echo" -> requestBody;
            default -> "not found";
        };
        exchange.getResponseHeaders().add("Content-Type", "text/plain");
        if ("/echo".equals(path)) {
            exchange.getResponseHeaders().add(
                    "X-Echo-Request-Header",
                    exchange.getRequestHeaders().getFirst("X-Test"));
        }
        byte[] response = body.getBytes(StandardCharsets.UTF_8);
        exchange.sendResponseHeaders(status, response.length);
        try (OutputStream output = exchange.getResponseBody()) {
            output.write(response);
        }
    }
}
