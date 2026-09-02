package com.apiops.agent.model.springai;

import com.apiops.agent.model.AgentModelClient;
import com.apiops.agent.model.AgentModelException;
import com.apiops.agent.model.AgentModelRequest;
import com.apiops.agent.model.AgentModelResponse;
import com.apiops.agent.tool.GatewayToolCallbackAdapter;
import com.apiops.agent.tool.RagSearchToolCallbackFactory;
import com.apiops.tool.gateway.ToolExecutionContext;
import org.springframework.ai.chat.model.ChatModel;
import org.springframework.ai.chat.messages.SystemMessage;
import org.springframework.ai.chat.messages.UserMessage;
import org.springframework.ai.chat.prompt.Prompt;
import org.springframework.ai.model.tool.DefaultToolCallingChatOptions;

import java.util.ArrayList;
import java.util.List;
import java.util.Objects;

public final class SpringAiAgentModelClient implements AgentModelClient {

    private final ChatModel chatModel;

    public SpringAiAgentModelClient(ChatModel chatModel) {
        this.chatModel = Objects.requireNonNull(chatModel, "chatModel");
    }

    @Override
    public AgentModelResponse call(AgentModelRequest request) {
        Objects.requireNonNull(request, "request");
        return callPrompt(prompt(request, null));
    }

    /**
     * Calls the provider with callbacks that are already bound to the ToolGateway.
     * Spring AI executes eligible Gateway callbacks and continues the model
     * conversation before this method returns the final response.
     *
     * <p>This deliberately accepts only the final Gateway adapter type. There is
     * no general {@code List<ToolCallback>} entry point: direct Spring AI
     * callbacks (including function, retriever, or repository callbacks) must
     * not become model-visible through this boundary.</p>
     */
    public AgentModelResponse callWithTools(
            AgentModelRequest request,
            List<GatewayToolCallbackAdapter> toolCallbacks) {
        Objects.requireNonNull(request, "request");
        List<GatewayToolCallbackAdapter> gatewayCallbacks = requireGatewayCallbacks(toolCallbacks);
        var options = DefaultToolCallingChatOptions.builder()
                .toolCallbacks(gatewayCallbacks.stream()
                        .map(callback -> (org.springframework.ai.tool.ToolCallback) callback)
                        .toList())
                .internalToolExecutionEnabled(true)
                .build();
        return callPrompt(prompt(request, options));
    }

    /**
     * Keeps the runtime boundary closed even when an unchecked/raw caller
     * attempts to pass a direct Spring AI callback.
     */
    private static List<GatewayToolCallbackAdapter> requireGatewayCallbacks(
            List<?> suppliedCallbacks) {
        Objects.requireNonNull(suppliedCallbacks, "toolCallbacks");
        if (suppliedCallbacks.isEmpty()) {
            throw new IllegalArgumentException("toolCallbacks must not be empty");
        }
        List<GatewayToolCallbackAdapter> gatewayCallbacks =
                new ArrayList<>(suppliedCallbacks.size());
        for (Object callback : suppliedCallbacks) {
            if (!(callback instanceof GatewayToolCallbackAdapter gatewayCallback)) {
                throw new IllegalArgumentException(
                        "Only GatewayToolCallbackAdapter is permitted in formal Tool Calling");
            }
            gatewayCallbacks.add(gatewayCallback);
        }
        return List.copyOf(gatewayCallbacks);
    }

    /**
     * RAG-specific wiring convenience. The model client receives only a Gateway-bound
     * callback; it never receives the RagRetriever or another resource directly.
     */
    public AgentModelResponse callWithRagTool(
            AgentModelRequest request,
            ToolExecutionContext trustedContext,
            RagSearchToolCallbackFactory callbackFactory) {
        Objects.requireNonNull(trustedContext, "trustedContext");
        Objects.requireNonNull(callbackFactory, "callbackFactory");
        return callWithTools(request, List.of(callbackFactory.create(trustedContext)));
    }

    private Prompt prompt(AgentModelRequest request, org.springframework.ai.chat.prompt.ChatOptions options) {
        List<org.springframework.ai.chat.messages.Message> messages = List.of(
                new SystemMessage(request.system()),
                new UserMessage(request.user()
                        + "\n\n<untrusted-context>\n"
                        + request.context()
                        + "\n</untrusted-context>"));
        return options == null ? new Prompt(messages) : new Prompt(messages, options);
    }

    private AgentModelResponse callPrompt(Prompt prompt) {
        try {
            var response = chatModel.call(prompt);
            String content = response == null || response.getResult() == null
                    ? null : response.getResult().getOutput().getText();
            String modelCallId = response == null || response.getMetadata() == null
                    ? null : response.getMetadata().getId();
            if (content == null || modelCallId == null || modelCallId.isBlank()) {
                throw new AgentModelException("Model provider returned an incomplete response");
            }
            return new AgentModelResponse(modelCallId, content);
        } catch (AgentModelException exception) {
            throw exception;
        } catch (RuntimeException exception) {
            throw new AgentModelException("Model provider call failed");
        }
    }
}
