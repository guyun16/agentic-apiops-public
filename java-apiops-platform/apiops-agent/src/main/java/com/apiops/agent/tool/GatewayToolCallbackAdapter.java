package com.apiops.agent.tool;

import com.apiops.tool.gateway.ToolCallIntent;
import com.apiops.tool.gateway.ToolDefinition;
import com.apiops.tool.gateway.ToolExecutionContext;
import com.apiops.tool.gateway.ToolGateway;
import com.apiops.common.tool.ToolResult;
import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.springframework.ai.chat.model.ToolContext;
import org.springframework.ai.tool.ToolCallback;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.function.Supplier;

/**
 * Spring AI callback boundary for one registered Gateway Tool.
 *
 * <p>The adapter has no knowledge of RAG, SQL, Redis, HTTP, repositories, or vector stores.
 * It only decodes model arguments into the existing ToolCallIntent and delegates to the
 * existing ToolGateway with a Java-supplied trusted context.</p>
 */
public final class GatewayToolCallbackAdapter implements ToolCallback {

    private final ToolGateway gateway;
    private final ToolDefinition definition;
    private final Supplier<ToolExecutionContext> trustedContextSupplier;
    private final ToolGateway.ToolHandler handler;
    private final ObjectMapper objectMapper;
    private final org.springframework.ai.tool.definition.ToolDefinition springDefinition;

    public GatewayToolCallbackAdapter(
            ToolGateway gateway,
            ToolDefinition definition,
            Supplier<ToolExecutionContext> trustedContextSupplier,
            ToolGateway.ToolHandler handler,
            ObjectMapper objectMapper
    ) {
        this.gateway = Objects.requireNonNull(gateway, "gateway must not be null");
        this.definition = Objects.requireNonNull(definition, "definition must not be null");
        this.trustedContextSupplier = Objects.requireNonNull(
                trustedContextSupplier, "trustedContextSupplier must not be null");
        this.handler = Objects.requireNonNull(handler, "handler must not be null");
        this.objectMapper = Objects.requireNonNull(objectMapper, "objectMapper must not be null");
        this.springDefinition = org.springframework.ai.tool.definition.ToolDefinition.builder()
                // Provider transport names cannot contain dots. The stable Gateway
                // contract remains definition.name(); only Spring AI's external
                // function name is normalized at this adapter boundary.
                .name(providerToolName(definition.name()))
                .description(definition.description())
                .inputSchema(inputSchema(definition, objectMapper))
                .build();
    }

    @Override
    public org.springframework.ai.tool.definition.ToolDefinition getToolDefinition() {
        return springDefinition;
    }

    @Override
    public String call(String toolInput) {
        Map<String, Object> arguments = parseArguments(toolInput);
        ToolCallIntent intent = new ToolCallIntent(definition.name(), arguments);
        ToolExecutionContext trustedContext = trustedContextSupplier.get();
        ToolResult<Object> result = gateway.execute(trustedContext, intent, handler);
        try {
            return objectMapper.writeValueAsString(result);
        } catch (Exception exception) {
            throw new IllegalStateException("Unable to serialize ToolResult", exception);
        }
    }

    /** ToolContext is provider/model metadata and is never an authority source. */
    @Override
    public String call(String toolInput, ToolContext ignoredToolContext) {
        return call(toolInput);
    }

    private Map<String, Object> parseArguments(String toolInput) {
        if (toolInput == null || toolInput.isBlank()) {
            return Map.of();
        }
        try {
            JsonNode root = objectMapper.readTree(toolInput);
            if (root == null || !root.isObject()) {
                return Map.of();
            }
            return objectMapper.convertValue(root, new TypeReference<>() {
            });
        } catch (Exception exception) {
            // The existing strict Gateway contract turns missing required fields into INVALID.
            return Map.of();
        }
    }

    private static String inputSchema(ToolDefinition definition, ObjectMapper objectMapper) {
        Map<String, Object> schema = new LinkedHashMap<>();
        schema.put("type", "object");
        Map<String, Object> properties = new LinkedHashMap<>();
        List<String> required = new ArrayList<>();
        for (Map.Entry<String, Class<?>> entry : definition.argumentTypes().entrySet()) {
            String argumentName = entry.getKey();
            ToolDefinition.ParameterContract contract =
                    definition.parameterContracts().get(argumentName);
            Map<String, Object> property = new LinkedHashMap<>();
            property.put("type", jsonType(entry.getValue()));
            if (contract != null) {
                if (!contract.allowedValues().isEmpty()) {
                    property.put("enum", contract.allowedValues().stream()
                            .map(GatewayToolCallbackAdapter::schemaValue).toList());
                }
                if (contract.minLength() != null) {
                    property.put("minLength", contract.minLength());
                }
                if (contract.maxLength() != null) {
                    property.put("maxLength", contract.maxLength());
                }
                if (contract.min() != null) {
                    property.put("minimum", contract.min());
                }
                if (contract.max() != null) {
                    property.put("maximum", contract.max());
                }
            }
            properties.put(argumentName, property);
            if (contract == null || contract.required()) {
                required.add(argumentName);
            }
        }
        schema.put("properties", properties);
        schema.put("required", required);
        schema.put("additionalProperties", false);
        try {
            return objectMapper.writeValueAsString(schema);
        } catch (Exception exception) {
            throw new IllegalArgumentException("Unable to create Tool input schema", exception);
        }
    }

    private static Object schemaValue(Object value) {
        return value instanceof Enum<?> enumValue ? enumValue.name() : value;
    }

    private static String providerToolName(String stableToolName) {
        String normalized = stableToolName.replace('.', '_');
        if (!normalized.matches("[A-Za-z0-9_-]+")) {
            throw new IllegalArgumentException(
                    "Tool name is not representable by the Spring AI provider contract");
        }
        return normalized;
    }

    private static String jsonType(Class<?> type) {
        if (type == String.class || type == Character.class || type == char.class) {
            return "string";
        }
        if (type == Boolean.class || type == boolean.class) {
            return "boolean";
        }
        if (Number.class.isAssignableFrom(type)
                || type == byte.class || type == short.class || type == int.class
                || type == long.class || type == float.class || type == double.class) {
            return type == Float.class || type == Double.class
                    || type == float.class || type == double.class
                    ? "number" : "integer";
        }
        if (java.util.Collection.class.isAssignableFrom(type)) {
            return "array";
        }
        return "object";
    }
}
