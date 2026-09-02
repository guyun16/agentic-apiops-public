package com.apiops.openapi.normalizer;

import com.apiops.openapi.domain.ApiEndpoint;
import com.apiops.openapi.domain.ApiExample;
import com.apiops.openapi.domain.ApiParameter;
import com.apiops.openapi.domain.ApiRequestSchema;
import com.apiops.openapi.domain.ApiResponseSchema;
import com.apiops.openapi.parser.OpenApiDocumentParser;
import com.apiops.openapi.parser.OpenApiParseException;
import com.apiops.openapi.parser.ParsedOpenApiDocument;
import com.fasterxml.jackson.databind.JsonNode;
import io.swagger.v3.core.util.Json;
import io.swagger.v3.oas.models.OpenAPI;
import io.swagger.v3.oas.models.Operation;
import io.swagger.v3.oas.models.PathItem;
import io.swagger.v3.oas.models.Paths;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.NullAndEmptySource;
import org.junit.jupiter.params.provider.ValueSource;

import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.util.List;
import java.util.Set;
import java.util.stream.Collectors;
import java.util.stream.StreamSupport;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

class OpenApiMetadataNormalizerTest {

    private static NormalizedOpenApiMetadata metadata;

    @BeforeAll
    static void normalizeFixture() {
        try {
            metadata = new OpenApiMetadataNormalizer().normalize(
                    new OpenApiDocumentParser().parse(fixture()),
                    "api_doc_metadata_fixture",
                    41L,
                    (method, path) -> "api_" + method.toLowerCase()
                            + (path.equals("/rooted") ? "_rooted" : "")
            );
        } catch (OpenApiParseException exception) {
            throw new AssertionError(exception.parserMessages().toString(), exception);
        }
    }

    @Test
    void shouldCreateOneEndpointPerHttpOperationAndApplyInheritance() throws Exception {
        assertEquals(6, metadata.endpoints().size());
        assertEquals(Set.of("GET", "POST", "PUT", "DELETE", "PATCH"),
                metadata.endpoints().stream()
                        .map(ApiEndpoint::httpMethod)
                        .collect(Collectors.toSet()));

        ApiEndpoint get = endpoint("GET");
        assertEquals("getItem", get.operationId());
        assertEquals("Get item", get.summary());
        assertEquals(List.of("items", "read"), StreamSupport.stream(
                json(get.tagsJson()).spliterator(), false).map(JsonNode::asText).toList());
        assertEquals("https://operation.example.test",
                json(get.serversJson()).get(0).get("url").asText());
        assertTrue(json(get.securityJson()).isEmpty());
        assertTrue(get.deprecated());

        assertEquals("https://path.example.test",
                json(endpoint("POST").serversJson()).get(0).get("url").asText());
        assertEquals("oauth2", json(endpoint("POST").securityJson())
                .get(0).fieldNames().next());
        assertEquals("apiKeyAuth", json(endpoint("PUT").securityJson())
                .get(0).fieldNames().next());

        ApiEndpoint rooted = metadata.endpoints().stream()
                .filter(endpoint -> endpoint.path().equals("/rooted"))
                .findFirst().orElseThrow();
        assertEquals("https://root.example.test",
                json(rooted.serversJson()).get(0).get("url").asText());
        assertEquals("oauth2", json(rooted.securityJson()).get(0).fieldNames().next());
    }

    @Test
    void shouldMergeParametersByNameAndLocationWithOperationOverride() throws Exception {
        List<ApiParameter> parameters = metadata.parameters().stream()
                .filter(parameter -> parameter.apiId().equals("api_get"))
                .toList();
        assertEquals(7, parameters.size());
        assertEquals(Set.of("path", "query", "header", "cookie"),
                parameters.stream().map(ApiParameter::location).collect(Collectors.toSet()));

        ApiParameter id = parameter(parameters, "id", "path");
        assertEquals("operation-level id", id.description());
        assertEquals("item-42", json(id.exampleJson()).asText());
        assertEquals("item-43", json(id.schemaJson()).get("enum").get(1).asText());
        assertNotNull(parameter(parameters, "locale", "query"));
        assertNotNull(parameter(parameters, "token", "query"));
        assertNotNull(parameter(parameters, "token", "header"));
        assertNotNull(parameter(parameters, "trace", "header"));
        assertNotNull(parameter(parameters, "session", "cookie"));
    }

    @Test
    void shouldKeepRequestSchemaTreeAndMultipleMediaTypes() throws Exception {
        List<ApiRequestSchema> requests = metadata.requestSchemas().stream()
                .filter(schema -> schema.apiId().equals("api_post"))
                .toList();
        assertEquals(Set.of("application/json", "text/plain"),
                requests.stream().map(ApiRequestSchema::mediaType).collect(Collectors.toSet()));
        assertTrue(requests.stream().allMatch(ApiRequestSchema::required));

        JsonNode schema = json(requests.stream()
                .filter(value -> value.mediaType().equals("application/json"))
                .findFirst().orElseThrow().schemaJson());
        assertEquals(Set.of("name", "kind"), StreamSupport.stream(
                schema.get("required").spliterator(), false)
                .map(JsonNode::asText).collect(Collectors.toSet()));
        JsonNode properties = schema.get("properties");
        assertTrue(properties.get("name").get("nullable").asBoolean());
        assertEquals(2, properties.get("name").get("minLength").asInt());
        assertEquals(40, properties.get("name").get("maxLength").asInt());
        assertEquals("^[a-z]+$", properties.get("name").get("pattern").asText());
        assertEquals("sample", properties.get("name").get("default").asText());
        assertEquals("widget", properties.get("name").get("example").asText());
        assertEquals("PREMIUM", properties.get("kind").get("enum").get(1).asText());
        assertEquals(1, properties.get("quantity").get("minimum").asInt());
        assertEquals(100, properties.get("quantity").get("maximum").asInt());
        assertEquals("object", properties.get("children").get("items").get("type").asText());
        assertEquals(2, properties.get("choice").get("oneOf").size());
        assertEquals(2, properties.get("flexible").get("anyOf").size());
        assertEquals(2, properties.get("composed").get("allOf").size());
        JsonNode plain = json(requests.stream()
                .filter(value -> value.mediaType().equals("text/plain"))
                .findFirst().orElseThrow().schemaJson());
        assertEquals("string", plain.get("type").asText());
        assertEquals("plain", plain.get("format").asText());
    }

    @Test
    void shouldNormalizeAllResponseClassesMediaTypesAndInternalRef() throws Exception {
        List<ApiResponseSchema> getResponses = responses("api_get");
        assertEquals(Set.of("200", "400", "500", "default"), getResponses.stream()
                .map(ApiResponseSchema::statusCode).collect(Collectors.toSet()));
        assertEquals(2, getResponses.stream()
                .filter(response -> response.statusCode().equals("200")).count());
        assertTrue(responses("api_post").stream()
                .anyMatch(response -> response.statusCode().equals("201")));

        ApiResponseSchema noContent = responses("api_delete").getFirst();
        assertEquals("204", noContent.statusCode());
        assertEquals("", noContent.mediaType());
        assertTrue(json(noContent.schemaJson()).isNull());

        ApiResponseSchema resolved = responses("api_patch").getFirst();
        assertEquals("string", json(resolved.schemaJson())
                .at("/properties/message/type").asText());
    }

    @Test
    void shouldNormalizeSingleAndNamedRequestAndResponseExamplesWithOwners()
            throws Exception {
        Set<String> requestNames = metadata.examples().stream()
                .filter(example -> example.ownerType().equals("REQUEST_SCHEMA"))
                .map(ApiExample::exampleName)
                .collect(Collectors.toSet());
        assertEquals(Set.of("default", "minimal", "premium"), requestNames);

        ApiExample requestExample = example("REQUEST_SCHEMA", "minimal");
        ApiRequestSchema requestOwner = metadata.requestSchemas().stream()
                .filter(schema -> schema.id() == requestExample.ownerRefId())
                .findFirst().orElseThrow();
        assertEquals("application/json", requestOwner.mediaType());
        assertEquals("widget", json(requestExample.valueJson()).get("name").asText());

        ApiExample responseExample = example("RESPONSE_SCHEMA", "named");
        ApiResponseSchema responseOwner = metadata.responseSchemas().stream()
                .filter(schema -> schema.id() == responseExample.ownerRefId())
                .findFirst().orElseThrow();
        assertEquals("200", responseOwner.statusCode());
        assertEquals("application/json", responseOwner.mediaType());
        ApiExample parameterExample = example("PARAMETER", "common");
        ApiParameter parameterOwner = metadata.parameters().stream()
                .filter(parameter -> parameter.id() == parameterExample.ownerRefId())
                .findFirst().orElseThrow();
        assertEquals("q", parameterOwner.name());
        assertEquals("shoes", json(parameterExample.valueJson()).asText());
        assertFalse(metadata.examples().stream()
                .anyMatch(example -> example.ownerRefId() == 0));
    }

    @ParameterizedTest
    @NullAndEmptySource
    @ValueSource(strings = {" ", "\t"})
    void shouldRejectBlankOperationId(String operationId) {
        Operation operation = new Operation();
        operation.setOperationId(operationId);

        OpenApiNormalizationException exception = assertThrows(
                OpenApiNormalizationException.class,
                () -> normalize(paths("/blank", new PathItem().get(operation)))
        );

        assertEquals(OpenApiNormalizationException.Reason.BLANK_OPERATION_ID,
                exception.reason());
        assertEquals("BLANK_OPERATION_ID: operationId is blank at GET /blank",
                exception.getMessage());
    }

    @Test
    void shouldRejectDuplicateOperationId() {
        Paths paths = paths("/first", new PathItem().get(
                new Operation().operationId("sharedOperation")));
        paths.addPathItem("/second", new PathItem().post(
                new Operation().operationId("sharedOperation")));

        OpenApiNormalizationException exception = assertThrows(
                OpenApiNormalizationException.class,
                () -> normalize(paths)
        );

        assertEquals(OpenApiNormalizationException.Reason.DUPLICATE_OPERATION_ID,
                exception.reason());
        assertEquals("DUPLICATE_OPERATION_ID: 'sharedOperation' at POST /second"
                        + " duplicates GET /first",
                exception.getMessage());
    }

    private static ApiEndpoint endpoint(String method) {
        return metadata.endpoints().stream()
                .filter(endpoint -> endpoint.httpMethod().equals(method)
                        && endpoint.path().equals("/items/{id}"))
                .findFirst().orElseThrow();
    }

    private static ApiParameter parameter(
            List<ApiParameter> parameters, String name, String location) {
        return parameters.stream()
                .filter(parameter -> parameter.name().equals(name)
                        && parameter.location().equals(location))
                .findFirst().orElseThrow();
    }

    private static List<ApiResponseSchema> responses(String apiId) {
        return metadata.responseSchemas().stream()
                .filter(response -> response.apiId().equals(apiId))
                .toList();
    }

    private static ApiExample example(String ownerType, String name) {
        return metadata.examples().stream()
                .filter(example -> example.ownerType().equals(ownerType)
                        && example.exampleName().equals(name))
                .findFirst().orElseThrow();
    }

    private static JsonNode json(String value) throws Exception {
        return Json.mapper().readTree(value);
    }

    private static Paths paths(String path, PathItem pathItem) {
        return new Paths().addPathItem(path, pathItem);
    }

    private static NormalizedOpenApiMetadata normalize(Paths paths) {
        return new OpenApiMetadataNormalizer().normalize(
                new ParsedOpenApiDocument(
                        "3.0.3", new OpenAPI().paths(paths), List.of()),
                "api_doc_invalid_operation",
                41L,
                (method, path) -> "api_test"
        );
    }

    private static String fixture() {
        try (InputStream input = OpenApiMetadataNormalizerTest.class.getResourceAsStream(
                "/openapi/metadata-normalization.yaml")) {
            if (input == null) {
                throw new IllegalStateException("Missing normalization fixture");
            }
            return new String(input.readAllBytes(), StandardCharsets.UTF_8);
        } catch (IOException exception) {
            throw new IllegalStateException("Cannot read normalization fixture", exception);
        }
    }
}
