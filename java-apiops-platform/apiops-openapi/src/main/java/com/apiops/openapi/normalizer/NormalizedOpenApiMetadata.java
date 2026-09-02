package com.apiops.openapi.normalizer;

import com.apiops.openapi.domain.ApiEndpoint;
import com.apiops.openapi.domain.ApiExample;
import com.apiops.openapi.domain.ApiParameter;
import com.apiops.openapi.domain.ApiRequestSchema;
import com.apiops.openapi.domain.ApiResponseSchema;

import java.util.List;

/** In-memory Day 5-8 output; persistence orchestration remains a later concern. */
public record NormalizedOpenApiMetadata(
        List<ApiEndpoint> endpoints,
        List<ApiParameter> parameters,
        List<ApiRequestSchema> requestSchemas,
        List<ApiResponseSchema> responseSchemas,
        List<ApiExample> examples
) {
    public NormalizedOpenApiMetadata {
        endpoints = List.copyOf(endpoints);
        parameters = List.copyOf(parameters);
        requestSchemas = List.copyOf(requestSchemas);
        responseSchemas = List.copyOf(responseSchemas);
        examples = List.copyOf(examples);
    }
}
