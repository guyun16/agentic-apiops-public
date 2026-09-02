package com.apiops.runner.dsl;

import com.fasterxml.jackson.annotation.JsonInclude;
import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.fasterxml.jackson.databind.JsonNode;

import java.util.Map;

@JsonInclude(JsonInclude.Include.NON_NULL)
@JsonIgnoreProperties(ignoreUnknown = false)
public record RequestSpec(
        String method,
        String path,
        Map<String, JsonNode> pathParams,
        Map<String, JsonNode> query,
        Map<String, String> headers,
        JsonNode body
) {
    public RequestSpec {
        pathParams = pathParams == null ? null : Map.copyOf(pathParams);
        query = query == null ? null : Map.copyOf(query);
        headers = headers == null ? null : Map.copyOf(headers);
    }
}
