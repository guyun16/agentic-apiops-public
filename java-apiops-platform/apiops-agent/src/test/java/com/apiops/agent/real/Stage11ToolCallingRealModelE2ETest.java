package com.apiops.agent.real;

import com.apiops.agent.model.AgentModelRequest;
import com.apiops.agent.model.springai.SpringAiAgentModelClient;
import com.apiops.agent.tool.AssertionTypeTool;
import com.apiops.agent.tool.GatewayToolTestSupport;
import com.apiops.tool.gateway.ToolExecutionContext;
import org.junit.jupiter.api.Test;

import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicReference;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

/** Explicit real-provider tool-calling acceptance; excluded from default Surefire execution. */
class Stage11ToolCallingRealModelE2ETest {

    @Test
    void realModelSelectsJavaToolAndContinuesWithToolResult() {
        var client = DeepSeekRealTestSupport.client();
        assertTrue(client instanceof SpringAiAgentModelClient);

        AssertionTypeTool assertionTypeTool = new AssertionTypeTool();
        AtomicInteger invocations = new AtomicInteger();
        AtomicReference<AssertionTypeTool.Request> received = new AtomicReference<>();
        AtomicReference<AssertionTypeTool.Result> returned = new AtomicReference<>();

        AgentModelRequest request = new AgentModelRequest(
                "stage11-tool-calling", "v1",
                "You are a Spring AI tool-calling conformance test. "
                        + "You must call the isAllowedAssertionType tool before answering. "
                        + "Do not answer from memory or from the tool description. "
                        + "After the Java tool returns, output a JSON object containing "
                        + "toolResultUsed=true, checkedType, and allowed copied from the tool result.",
                "Call isAllowedAssertionType exactly once with the structured argument "
                        + "{\"type\":\"STATUS_CODE\"}. Then use the returned Java result and "
                        + "respond with the requested final JSON object.",
                "{}");

        ToolExecutionContext trustedContext = new ToolExecutionContext(
                GatewayToolTestSupport.USER_ID,
                GatewayToolTestSupport.PROJECT_ID,
                java.util.Set.of("TOOL_READ"),
                "stage11-real-caller",
                "stage11-real-run");
        try (var bundle = GatewayToolTestSupport.assertionTypeCallback(
                trustedContext,
                (context, intent) -> {
                    invocations.incrementAndGet();
                    AssertionTypeTool.Request requestValue = new AssertionTypeTool.Request(
                            (String) intent.arguments().get("type"));
                    received.set(requestValue);
                    AssertionTypeTool.Result resultValue =
                            assertionTypeTool.isAllowedAssertionType(requestValue);
                    returned.set(resultValue);
                    return Map.of("type", resultValue.type(), "allowed", resultValue.allowed());
                })) {
            var response = ((SpringAiAgentModelClient) client)
                    .callWithTools(request, List.of(bundle.callback()));

            assertEquals(1, invocations.get());
            assertNotNull(received.get());
            assertEquals("STATUS_CODE", received.get().type());
            assertEquals(new AssertionTypeTool.Result("STATUS_CODE", true), returned.get());
            String finalContent = response.content().toLowerCase(Locale.ROOT);
            assertTrue(finalContent.contains("toolresultused"));
            assertTrue(finalContent.contains("true"));

            System.out.println("REAL_STAGE11_TOOL_CALLING_E2E provider=DeepSeek"
                    + " adapter=SpringAiAgentModelClient model=" + DeepSeekRealTestSupport.MODEL
                    + " modelCallId=" + response.modelCallId()
                    + " toolName=isAllowedAssertionType"
                    + " toolInvocations=" + invocations.get()
                    + " javaResultAllowed=" + returned.get().allowed()
                    + " finalResponseObserved=true");
        }
    }
}
