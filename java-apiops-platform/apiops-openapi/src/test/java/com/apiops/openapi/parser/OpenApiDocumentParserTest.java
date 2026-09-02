package com.apiops.openapi.parser;

import io.swagger.v3.oas.models.Operation;
import org.junit.jupiter.api.Test;

import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertInstanceOf;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

class OpenApiDocumentParserTest {

    private final OpenApiDocumentParser parser = new OpenApiDocumentParser();

    @Test
    void shouldParseOpenApi30JsonIntoObjectModel() {
        ParsedOpenApiDocument parsed = parser.parse(fixture("minimal.json"));

        assertDocument(parsed);
    }

    @Test
    void shouldParseOpenApi30YamlIntoTheSameOutputModel() {
        ParsedOpenApiDocument json = parser.parse(fixture("minimal.json"));
        ParsedOpenApiDocument yaml = parser.parse(fixture("minimal.yaml"));

        assertInstanceOf(ParsedOpenApiDocument.class, json);
        assertInstanceOf(ParsedOpenApiDocument.class, yaml);
        assertEquals(json.openapiVersion(), yaml.openapiVersion());
        assertEquals(
                json.openApi().getPaths().keySet(),
                yaml.openApi().getPaths().keySet()
        );
        assertEquals(operation(json).getOperationId(), operation(yaml).getOperationId());
    }

    @Test
    void shouldClassifyMalformedJsonAsParseFailed() {
        assertError("invalid-json.json", OpenApiParseErrorType.PARSE_FAILED);
    }

    @Test
    void shouldClassifyOrdinaryJsonAsInvalidOpenApi() {
        assertError("not-openapi.json", OpenApiParseErrorType.INVALID_OPENAPI);
    }

    @Test
    void shouldRejectOpenApi31AsUnsupported() {
        assertError(
                "unsupported-version.json",
                OpenApiParseErrorType.UNSUPPORTED_OPENAPI_VERSION
        );
    }

    @Test
    void shouldRejectSwagger20WithoutAutomaticConversion() {
        assertError("swagger-2.0.json", OpenApiParseErrorType.INVALID_OPENAPI);
    }

    @Test
    void shouldKeepRemoteReferenceUnresolved() {
        ParsedOpenApiDocument parsed = parser.parse("""
                openapi: 3.0.3
                info:
                  title: Unresolved Ref API
                  version: 1.0.0
                paths: {}
                components:
                  schemas:
                    RemoteModel:
                      $ref: https://127.0.0.1:1/never-fetched.yaml#/RemoteModel
                """);

        assertEquals(
                "https://127.0.0.1:1/never-fetched.yaml#/RemoteModel",
                parsed.openApi().getComponents().getSchemas().get("RemoteModel").get$ref()
        );
    }

    private void assertDocument(ParsedOpenApiDocument parsed) {
        assertEquals("3.0.3", parsed.openapiVersion());
        assertTrue(parsed.openApi().getPaths().containsKey("/health"));
        assertEquals("getHealth", operation(parsed).getOperationId());
        assertTrue(parsed.parserMessages().isEmpty());
    }

    private Operation operation(ParsedOpenApiDocument parsed) {
        return parsed.openApi().getPaths().get("/health").getGet();
    }

    private void assertError(String fixture, OpenApiParseErrorType expectedType) {
        OpenApiParseException exception = assertThrows(
                OpenApiParseException.class,
                () -> parser.parse(fixture(fixture))
        );
        assertEquals(expectedType, exception.errorType());
    }

    private String fixture(String name) {
        try (InputStream input = getClass().getResourceAsStream("/openapi/" + name)) {
            if (input == null) {
                throw new IllegalArgumentException("Missing fixture: " + name);
            }
            return new String(input.readAllBytes(), StandardCharsets.UTF_8);
        } catch (IOException exception) {
            throw new IllegalStateException("Cannot read fixture: " + name, exception);
        }
    }
}
