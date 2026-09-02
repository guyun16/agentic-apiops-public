package com.apiops.openapi.vo;

import com.fasterxml.jackson.databind.JsonNode;

import java.util.List;

public record ApiMetadataDetailVO(
        String apiId,
        String apiDocId,
        String operationId,
        String method,
        String path,
        String summary,
        String description,
        JsonNode tags,
        JsonNode servers,
        JsonNode security,
        boolean deprecated,
        List<ParameterVO> parameters,
        List<RequestSchemaVO> requestSchemas,
        List<ResponseSchemaVO> responseSchemas,
        List<ExampleVO> examples
) {
    public record ParameterVO(
            String name,
            String location,
            boolean required,
            String description,
            JsonNode schema,
            JsonNode example
    ) {
    }

    public record RequestSchemaVO(
            boolean required,
            String mediaType,
            JsonNode schema
    ) {
    }

    public record ResponseSchemaVO(
            String statusCode,
            String description,
            String mediaType,
            JsonNode schema
    ) {
    }

    public record ExampleVO(
            ExampleOwnerVO owner,
            String exampleName,
            String summary,
            String description,
            JsonNode value
    ) {
    }

    public record ExampleOwnerVO(
            String type,
            String parameterName,
            String parameterLocation,
            String mediaType,
            String statusCode
    ) {
    }
}
