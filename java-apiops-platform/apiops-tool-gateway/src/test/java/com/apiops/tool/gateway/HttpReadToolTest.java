package com.apiops.tool.gateway;

import com.apiops.common.enums.ToolStatus;
import com.apiops.common.tool.ToolResult;
import com.sun.net.httpserver.HttpServer;
import org.junit.jupiter.api.Test;

import java.net.InetAddress;
import java.net.InetSocketAddress;
import java.net.URI;
import java.time.Duration;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.concurrent.atomic.AtomicInteger;

import static org.junit.jupiter.api.Assertions.*;

class HttpReadToolTest {
    private static final URI ORIGIN = URI.create("https://orders.example.test:8443");

    @Test void exactOriginSucceedsAndResponseIsSanitized() throws Exception {
        HttpGuard guard = publicGuard(ORIGIN);
        RecordingClient client = new RecordingClient(new HttpDiagnosticClient.Response(
                200, Map.of("Authorization", List.of("Bearer response-secret")),
                "password=body-secret"));
        try (var bundle = ToolSecurityTestSupport.gateway(HttpReadTool.definition(), guard)) {
            ToolResult<Object> result = HttpReadTool.execute(bundle.gateway(),
                    new HttpReadExecutor(guard, client), ToolSecurityTestSupport.context("http-ok"),
                    intent("GET", "https://orders.example.test:8443/actuator/health", Map.of("Accept", "application/json")));
            assertEquals(ToolStatus.SUCCESS, result.getStatus());
            assertEquals(1, client.calls.get());
            assertFalse(result.getData().toString().contains("response-secret"));
            assertFalse(result.getData().toString().contains("body-secret"));
            assertTrue(result.getData().toString().contains(ResultSanitizer.REDACTED_MARKER));
            assertFalse(bundle.audit().events().getFirst().sanitizedSummary().contains("response-secret"));
            assertFalse(bundle.audit().events().getFirst().sanitizedSummary().contains("body-secret"));
        }
    }

    @Test void ssrfAndOriginAttackMatrixStopsBeforeClient() throws Exception {
        RecordingClient client = new RecordingClient(new HttpDiagnosticClient.Response(200, Map.of(), "ok"));
        List<Case> cases = List.of(
                new Case(publicGuard(ORIGIN), intent("GET", "https://orders.example.test:9443/x", Map.of()), ToolStatus.FORBIDDEN),
                new Case(publicGuard(ORIGIN), intent("GET", "ftp://orders.example.test:8443/x", Map.of()), ToolStatus.FORBIDDEN),
                new Case(publicGuard(ORIGIN), intent("GET", "https://evil.example.test/x", Map.of()), ToolStatus.FORBIDDEN),
                new Case(new HttpGuard(Set.of(URI.create("http://localhost:8080")),
                        host -> List.of(InetAddress.getLoopbackAddress())),
                        intent("GET", "http://localhost:8080/x", Map.of()), ToolStatus.FORBIDDEN),
                new Case(new HttpGuard(Set.of(URI.create("http://service.test:8080")),
                        host -> List.of(InetAddress.getByName("10.0.0.4"))),
                        intent("GET", "http://service.test:8080/x", Map.of()), ToolStatus.FORBIDDEN),
                new Case(new HttpGuard(Set.of(URI.create("http://metadata.test")),
                        host -> List.of(InetAddress.getByName("169.254.169.254"))),
                        intent("GET", "http://metadata.test/latest/meta-data", Map.of()), ToolStatus.FORBIDDEN),
                new Case(new HttpGuard(Set.of(URI.create("http://127.0.0.1:8080")),
                        host -> List.of(InetAddress.getByName("127.0.0.1"))),
                        intent("GET", "http://127.0.0.1:8080/x", Map.of()), ToolStatus.FORBIDDEN),
                new Case(publicGuard(ORIGIN), intent("POST", "https://orders.example.test:8443/x", Map.of()), ToolStatus.PARAM_INVALID),
                new Case(publicGuard(ORIGIN), intent("PUT", "https://orders.example.test:8443/x", Map.of()), ToolStatus.PARAM_INVALID),
                new Case(publicGuard(ORIGIN), intent("DELETE", "https://orders.example.test:8443/x", Map.of()), ToolStatus.PARAM_INVALID),
                new Case(publicGuard(ORIGIN), intent("GET", "https://orders.example.test:8443/x",
                        Map.of("Authorization", "Bearer forged")), ToolStatus.FORBIDDEN),
                new Case(publicGuard(ORIGIN), intent("GET", "https://orders.example.test:8443/x",
                        Map.of("Cookie", "session=forged")), ToolStatus.FORBIDDEN)
        );
        int index = 0;
        for (Case attack : cases) {
            try (var bundle = ToolSecurityTestSupport.gateway(HttpReadTool.definition(), attack.guard())) {
                ToolResult<Object> result = HttpReadTool.execute(bundle.gateway(),
                        new HttpReadExecutor(attack.guard(), client),
                        ToolSecurityTestSupport.context("http-attack-" + index++), attack.intent());
                assertEquals(attack.status(), result.getStatus());
            }
        }
        assertEquals(0, client.calls.get());
    }

    @Test void redirectIsNotFollowedAndOversizedResponseFailsClosed() throws Exception {
        AtomicInteger escapedCalls = new AtomicInteger();
        HttpServer server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        server.createContext("/redirect", exchange -> {
            exchange.getResponseHeaders().add("Location", "/escaped");
            exchange.sendResponseHeaders(302, -1); exchange.close();
        });
        server.createContext("/escaped", exchange -> {
            escapedCalls.incrementAndGet(); exchange.sendResponseHeaders(200, 2);
            exchange.getResponseBody().write("ok".getBytes()); exchange.close();
        });
        server.createContext("/large", exchange -> {
            byte[] body = new byte[HttpGuard.MAX_RESPONSE_BYTES + 1];
            exchange.sendResponseHeaders(200, body.length);
            exchange.getResponseBody().write(body); exchange.close();
        });
        server.start();
        try {
            URI origin = URI.create("http://127.0.0.1:" + server.getAddress().getPort());
            HttpGuard guard = new HttpGuard(Set.of(origin), Set.of(origin),
                    host -> List.of(InetAddress.getByName("127.0.0.1")));
            JdkHttpDiagnosticClient client = new JdkHttpDiagnosticClient(Duration.ofSeconds(2));
            try (var bundle = ToolSecurityTestSupport.gateway(HttpReadTool.definition(), guard)) {
                ToolResult<Object> redirect = HttpReadTool.execute(bundle.gateway(),
                        new HttpReadExecutor(guard, client), ToolSecurityTestSupport.context("http-redirect"),
                        intent("GET", origin + "/redirect", Map.of()));
                assertEquals(ToolStatus.SUCCESS, redirect.getStatus());
                assertTrue(redirect.getData().toString().contains("302"));
                assertEquals(0, escapedCalls.get());

                ToolResult<Object> large = HttpReadTool.execute(bundle.gateway(),
                        new HttpReadExecutor(guard, client), ToolSecurityTestSupport.context("http-large"),
                        intent("GET", origin + "/large", Map.of()));
                assertEquals(ToolStatus.FAILED, large.getStatus());
            }
        } finally { server.stop(0); }
    }

    private static HttpGuard publicGuard(URI origin) throws Exception {
        return new HttpGuard(Set.of(origin),
                host -> List.of(InetAddress.getByName("93.184.216.34")));
    }

    private static ToolCallIntent intent(String method, String url, Map<String, String> headers) {
        return new ToolCallIntent(HttpGuard.TOOL_NAME,
                Map.of("method", method, "url", url, "headers", headers));
    }

    private record Case(HttpGuard guard, ToolCallIntent intent, ToolStatus status) {}

    private static final class RecordingClient implements HttpDiagnosticClient {
        private final AtomicInteger calls = new AtomicInteger();
        private final Response response;
        private RecordingClient(Response response) { this.response = response; }
        @Override public Response send(String method, URI uri, Map<String, String> headers) {
            calls.incrementAndGet(); return response;
        }
    }
}
