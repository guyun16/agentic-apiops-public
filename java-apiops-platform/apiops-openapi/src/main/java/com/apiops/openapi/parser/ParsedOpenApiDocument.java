package com.apiops.openapi.parser;

import io.swagger.v3.oas.models.OpenAPI;

import java.util.List;
import java.util.Objects;

public record ParsedOpenApiDocument(
        String openapiVersion,
        OpenAPI openApi,
        List<String> parserMessages
) {
    public ParsedOpenApiDocument {
        Objects.requireNonNull(openapiVersion, "openapiVersion must not be null");
        Objects.requireNonNull(openApi, "openApi must not be null");
        parserMessages = List.copyOf(parserMessages);
    }
}
