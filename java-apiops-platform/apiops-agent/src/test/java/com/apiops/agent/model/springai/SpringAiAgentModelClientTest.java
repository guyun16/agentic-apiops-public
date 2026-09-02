package com.apiops.agent.model.springai;

import com.apiops.agent.model.AgentModelException;
import com.apiops.agent.model.AgentModelRequest;
import com.apiops.agent.tool.AssertionTypeTool;
import com.apiops.agent.tool.GatewayToolTestSupport;
import com.apiops.tool.gateway.ToolExecutionContext;
import org.junit.jupiter.api.Test;
import org.springframework.ai.chat.messages.AssistantMessage;
import org.springframework.ai.chat.metadata.ChatResponseMetadata;
import org.springframework.ai.chat.model.ChatModel;
import org.springframework.ai.chat.model.ChatResponse;
import org.springframework.ai.chat.model.Generation;
import org.springframework.ai.chat.prompt.Prompt;
import org.springframework.ai.model.tool.ToolCallingChatOptions;
import org.springframework.ai.tool.ToolCallback;
import org.springframework.ai.tool.function.FunctionToolCallback;

import java.util.List;
import java.util.Map;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicReference;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertSame;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

class SpringAiAgentModelClientTest {

    private static final AgentModelRequest REQUEST = new AgentModelRequest(
            "diagnosis", "v1", "safe system", "safe user", "safe context");

    @Test
    void mapsSpringAiContentToProviderNeutralResponse() {
        AtomicReference<Prompt> captured = new AtomicReference<>();
        ChatModel chatModel = prompt -> {
            captured.set(prompt);
            return new ChatResponse(List.of(
                    new Generation(new AssistantMessage("candidate"))),
                    ChatResponseMetadata.builder().id("provider-call-1").build());
        };

        var response = new SpringAiAgentModelClient(chatModel).call(REQUEST);
        assertEquals("candidate", response.content());
        assertEquals("provider-call-1", response.modelCallId());
        assertEquals("safe system", captured.get().getSystemMessage().getText());
        assertTrue(captured.get().getUserMessage().getText().contains("safe user"));
        assertTrue(captured.get().getUserMessage().getText()
                .contains("<untrusted-context>\nsafe context"));
        assertTrue(!captured.get().getSystemMessage().getText().contains("safe context"));
    }

    @Test
    void mapsProviderFailureToStableExceptionWithoutProviderMessage() {
        String sensitiveProviderMessage = "Authorization: "
                + "provider-" + "credential";
        ChatModel chatModel = prompt -> {
            throw new IllegalStateException(sensitiveProviderMessage);
        };

        AgentModelException exception = assertThrows(AgentModelException.class,
                () -> new SpringAiAgentModelClient(chatModel).call(REQUEST));

        assertEquals("Model provider call failed", exception.getMessage());
        assertNull(exception.getCause());
        assertTrue(!exception.getMessage().contains("provider-credential"));
    }

    @Test
    void passesToolCallbacksToSpringAiInternalToolExecution() {
        AssertionTypeTool assertionTypeTool = new AssertionTypeTool();
        ToolExecutionContext trustedContext = new ToolExecutionContext(
                GatewayToolTestSupport.USER_ID,
                GatewayToolTestSupport.PROJECT_ID,
                java.util.Set.of("TOOL_READ"),
                "stage11-caller",
                "stage11-run");
        AtomicReference<Prompt> captured = new AtomicReference<>();
        ChatModel chatModel = prompt -> {
            captured.set(prompt);
            return new ChatResponse(List.of(
                    new Generation(new AssistantMessage("final"))),
                    ChatResponseMetadata.builder().id("provider-call-tools").build());
        };

        try (var bundle = GatewayToolTestSupport.assertionTypeCallback(
                trustedContext,
                (context, intent) -> {
                    AssertionTypeTool.Result result = assertionTypeTool
                            .isAllowedAssertionType(new AssertionTypeTool.Request(
                                    (String) intent.arguments().get("type")));
                    return Map.of("type", result.type(), "allowed", result.allowed());
                })) {
            ToolCallback callback = bundle.callback();
            var response = new SpringAiAgentModelClient(chatModel)
                    .callWithTools(REQUEST, List.of(bundle.callback()));

            ToolCallingChatOptions options = (ToolCallingChatOptions) captured.get().getOptions();
            assertSame(callback, options.getToolCallbacks().getFirst());
            assertTrue(options.getInternalToolExecutionEnabled());
            assertEquals("final", response.content());
        }
    }

    @Test
    @SuppressWarnings({"rawtypes", "unchecked"})
    void rejectsDirectSpringAiFunctionCallbackBeforeModelCall() {
        AtomicInteger modelCalls = new AtomicInteger();
        ChatModel chatModel = prompt -> {
            modelCalls.incrementAndGet();
            return new ChatResponse(List.of(
                    new Generation(new AssistantMessage("must-not-run"))),
                    ChatResponseMetadata.builder().id("unexpected-model-call").build());
        };
        FunctionToolCallback<String, String> directCallback =
                        FunctionToolCallback.<String, String>builder(
                                "direct.bypass", (String input) -> "bypass")
                        .description("direct callback")
                        .inputType(String.class)
                        .inputSchema("{\"type\":\"object\"}")
                        .build();

        List rawCallbacks = List.of(directCallback);
        IllegalArgumentException exception = assertThrows(IllegalArgumentException.class,
                () -> new SpringAiAgentModelClient(chatModel)
                        .callWithTools(REQUEST, rawCallbacks));

        assertTrue(exception.getMessage().contains("GatewayToolCallbackAdapter"));
        assertEquals(0, modelCalls.get());
    }
}
