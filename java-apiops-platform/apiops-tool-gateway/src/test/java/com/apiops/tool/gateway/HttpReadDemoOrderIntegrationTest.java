package com.apiops.tool.gateway;

import com.apiops.common.enums.ToolStatus;
import com.apiops.common.tool.ToolResult;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

import java.net.URI;
import java.time.Duration;
import java.util.Map;
import java.util.Set;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.junit.jupiter.api.Assumptions.assumeTrue;

/** Real exact-origin Gateway read against the running demo-order-service. */
class HttpReadDemoOrderIntegrationTest {

    private URI origin;

    @BeforeEach
    void setUp() throws Exception {
        assumeTrue("true".equalsIgnoreCase(System.getenv("APIOPS_HTTP_DEMO_ORDER_IT")),
                "Set APIOPS_HTTP_DEMO_ORDER_IT=true to run demo-order HTTP integration");
        String configured = System.getenv("APIOPS_DEMO_ORDER_BASE_URL");
        assumeTrue(configured != null && !configured.isBlank(),
                "Set APIOPS_DEMO_ORDER_BASE_URL to the exact test origin");
        URI base = URI.create(configured).normalize();
        assumeTrue(base.getScheme() != null && base.getHost() != null && base.getPort() > 0,
                "APIOPS_DEMO_ORDER_BASE_URL must include scheme, host, and port");
        origin = new URI(base.getScheme(), base.getUserInfo(), base.getHost(), base.getPort(),
                null, null, null);
    }

    @Test
    void allowedExactOriginRunsThroughGatewayAndAuditsRealResponse() throws Exception {
        HttpGuard guard = new HttpGuard(Set.of(origin), Set.of(origin), HttpGuard.systemDns());
        ToolExecutionContext context = ToolSecurityTestSupport.context("http-demo-order");
        URI requestUri = URI.create(HttpGuard.origin(origin) + "/v3/api-docs");
        try (var bundle = ToolSecurityTestSupport.gateway(HttpReadTool.definition(), guard)) {
            ToolResult<Object> result = HttpReadTool.execute(
                    bundle.gateway(),
                    new HttpReadExecutor(guard, new JdkHttpDiagnosticClient(Duration.ofSeconds(5))),
                    context,
                    new ToolCallIntent(HttpGuard.TOOL_NAME, Map.of(
                            "method", "GET",
                            "url", requestUri.toString(),
                            "headers", Map.of("Accept", "application/json"))));

            assertEquals(ToolStatus.SUCCESS, result.getStatus());
            assertNotNull(result.getToolCallId());
            assertFalse(result.getToolCallId().isBlank());
            assertTrue(result.getData().toString().contains("openapi"));
            assertEquals(1, bundle.audit().events().size());
            Audit.AuditEvent event = bundle.audit().events().getFirst();
            assertEquals(AuditStatus.SUCCESS, event.status());
            assertEquals(HttpGuard.TOOL_NAME, event.toolName());
            assertEquals(context.projectId(), event.projectId());
            assertEquals(result.getToolCallId(), event.toolCallId());
        }
    }
}
