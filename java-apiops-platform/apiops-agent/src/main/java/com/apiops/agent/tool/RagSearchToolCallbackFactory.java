package com.apiops.agent.tool;

import com.apiops.rag.retrieval.RagRetriever;
import com.apiops.tool.gateway.RagSearchTool;
import com.apiops.tool.gateway.ToolExecutionContext;
import com.apiops.tool.gateway.ToolGateway;
import com.apiops.tool.gateway.ToolDefinition;
import com.apiops.tool.gateway.ToolRegistry;
import com.fasterxml.jackson.databind.ObjectMapper;

import java.util.Objects;

/** Creates a per-model-call Gateway callback for the registered Stage 10 RAG Tool. */
public final class RagSearchToolCallbackFactory {

    private final ToolGateway gateway;
    private final ToolRegistry registry;
    private final RagRetriever retriever;
    private final ObjectMapper objectMapper;

    public RagSearchToolCallbackFactory(
            ToolGateway gateway,
            ToolRegistry registry,
            RagRetriever retriever,
            ObjectMapper objectMapper
    ) {
        this.gateway = Objects.requireNonNull(gateway, "gateway must not be null");
        this.registry = Objects.requireNonNull(registry, "registry must not be null");
        this.retriever = Objects.requireNonNull(retriever, "retriever must not be null");
        this.objectMapper = Objects.requireNonNull(objectMapper, "objectMapper must not be null");
    }

    public GatewayToolCallbackAdapter create(ToolExecutionContext trustedContext) {
        return create(trustedContext, ToolRegistry.DIAGNOSIS);
    }

    /**
     * Creates a callback only from the user/project-filtered, agent-allowlisted
     * definition. Discovery narrows visibility; ToolGateway still authorizes execution.
     */
    public GatewayToolCallbackAdapter create(
            ToolExecutionContext trustedContext,
            String agentType
    ) {
        Objects.requireNonNull(trustedContext, "trustedContext must not be null");
        Objects.requireNonNull(agentType, "agentType must not be null");
        ToolDefinition definition = registry.discover(trustedContext, agentType).stream()
                .filter(candidate -> RagSearchTool.TOOL_NAME.equals(candidate.name()))
                .findFirst()
                .orElseThrow(() -> new IllegalArgumentException(
                        "rag.search is not discovered for agent type: " + agentType));
        return new GatewayToolCallbackAdapter(
                gateway,
                definition,
                () -> trustedContext,
                RagSearchTool.handler(retriever),
                objectMapper);
    }
}
