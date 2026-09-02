package com.apiops.openapi.normalizer;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.node.ArrayNode;
import com.fasterxml.jackson.databind.node.ObjectNode;
import io.swagger.v3.core.util.Json;
import io.swagger.v3.oas.models.OpenAPI;
import io.swagger.v3.oas.models.media.Schema;

import java.net.URI;
import java.util.ArrayDeque;
import java.util.ArrayList;
import java.util.Deque;
import java.util.List;

/** Serializes Swagger's object tree and expands local schema references safely. */
public final class SchemaNormalizer {

    public String toJson(Object value) {
        try {
            return Json.mapper().writeValueAsString(value);
        } catch (JsonProcessingException exception) {
            throw new IllegalArgumentException("OpenAPI value cannot be represented as JSON", exception);
        }
    }

    public String toJson(Schema<?> schema, OpenAPI openApi) {
        JsonNode document = Json.mapper().valueToTree(openApi);
        JsonNode source = Json.mapper().valueToTree(schema);
        return toJson(resolve(source, document, new ArrayDeque<>()));
    }

    private JsonNode resolve(JsonNode node, JsonNode document, Deque<String> referenceStack) {
        if (node.isObject()) {
            JsonNode reference = node.get("$ref");
            if (reference != null && reference.isTextual()) {
                return resolveReference((ObjectNode) node, reference.textValue(),
                        document, referenceStack);
            }
            ObjectNode result = ((ObjectNode) node).deepCopy();
            List<String> fields = new ArrayList<>();
            result.fieldNames().forEachRemaining(fields::add);
            fields.forEach(field -> result.set(
                    field, resolve(result.get(field), document, referenceStack)));
            return result;
        }
        if (node.isArray()) {
            ArrayNode result = Json.mapper().createArrayNode();
            node.forEach(child -> result.add(resolve(child, document, referenceStack)));
            return result;
        }
        return node.deepCopy();
    }

    private JsonNode resolveReference(
            ObjectNode referenceNode,
            String reference,
            JsonNode document,
            Deque<String> referenceStack
    ) {
        InternalReference internalReference = internalReference(reference);
        String canonical = internalReference.canonical();
        if (referenceStack.contains(canonical)) {
            ObjectNode cycle = referenceNode.deepCopy();
            cycle.put("$ref", canonical);
            return cycle;
        }

        JsonNode target = document.at(internalReference.pointer());
        if (target.isMissingNode()) {
            throw OpenApiNormalizationException.missingInternalReference(canonical);
        }

        referenceStack.push(canonical);
        try {
            return resolve(target, document, referenceStack);
        } finally {
            referenceStack.pop();
        }
    }

    private InternalReference internalReference(String reference) {
        URI uri;
        try {
            uri = URI.create(reference);
        } catch (IllegalArgumentException exception) {
            throw OpenApiNormalizationException.missingInternalReference(reference);
        }
        String scheme = uri.getScheme();
        if (scheme != null && (scheme.equalsIgnoreCase("http")
                || scheme.equalsIgnoreCase("https"))) {
            throw OpenApiNormalizationException.remoteReference(reference);
        }
        if (!reference.startsWith("#")) {
            throw OpenApiNormalizationException.remoteReference(reference);
        }
        String pointer = uri.getFragment();
        if (pointer == null || !pointer.startsWith("/")) {
            throw OpenApiNormalizationException.missingInternalReference(reference);
        }
        return new InternalReference("#" + pointer, pointer);
    }

    private record InternalReference(String canonical, String pointer) {
    }
}
