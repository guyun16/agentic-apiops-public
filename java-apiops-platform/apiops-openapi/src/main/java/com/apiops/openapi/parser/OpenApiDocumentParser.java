package com.apiops.openapi.parser;

import io.swagger.v3.oas.models.OpenAPI;
import io.swagger.v3.parser.OpenAPIV3Parser;
import io.swagger.v3.parser.core.models.ParseOptions;
import io.swagger.v3.parser.core.models.SwaggerParseResult;

import java.util.List;
import java.util.Objects;

public final class OpenApiDocumentParser {

    private static final String SUPPORTED_VERSION_PATTERN = "3\\.0\\.[0-9]+";

    public ParsedOpenApiDocument parse(String rawDocument) {
        if (rawDocument == null || rawDocument.isBlank()) {
            throw new OpenApiParseException(
                    OpenApiParseErrorType.PARSE_FAILED,
                    List.of("OpenAPI document must not be blank")
            );
        }

        SwaggerParseResult result;
        try {
            result = new OpenAPIV3Parser().readContents(
                    rawDocument,
                    null,
                    unresolvedParseOptions()
            );
        } catch (RuntimeException exception) {
            throw new OpenApiParseException(
                    OpenApiParseErrorType.PARSE_FAILED,
                    List.of("Swagger Parser could not read the document"),
                    exception
            );
        }

        List<String> messages = parserMessages(result);
        OpenAPI openApi = result.getOpenAPI();
        if (openApi == null) {
            throw new OpenApiParseException(failureType(messages), messages);
        }

        String version = openApi.getOpenapi();
        if (version == null || version.isBlank()) {
            throw new OpenApiParseException(OpenApiParseErrorType.INVALID_OPENAPI, messages);
        }
        if (!version.matches(SUPPORTED_VERSION_PATTERN)) {
            throw new OpenApiParseException(
                    OpenApiParseErrorType.UNSUPPORTED_OPENAPI_VERSION,
                    messages
            );
        }
        if (!messages.isEmpty()) {
            throw new OpenApiParseException(OpenApiParseErrorType.INVALID_OPENAPI, messages);
        }

        return new ParsedOpenApiDocument(version, openApi, messages);
    }

    private ParseOptions unresolvedParseOptions() {
        ParseOptions options = new ParseOptions();
        options.setResolve(false);
        options.setResolveFully(false);
        options.setFlatten(false);
        options.setValidateExternalRefs(false);
        return options;
    }

    private List<String> parserMessages(SwaggerParseResult result) {
        if (result.getMessages() == null) {
            return List.of();
        }
        return result.getMessages().stream()
                .filter(Objects::nonNull)
                .filter(message -> !message.isBlank())
                .toList();
    }

    private OpenApiParseErrorType failureType(List<String> messages) {
        boolean semanticFailure = !messages.isEmpty()
                && messages.stream().allMatch(message -> message.startsWith("attribute "));
        return semanticFailure
                ? OpenApiParseErrorType.INVALID_OPENAPI
                : OpenApiParseErrorType.PARSE_FAILED;
    }
}
