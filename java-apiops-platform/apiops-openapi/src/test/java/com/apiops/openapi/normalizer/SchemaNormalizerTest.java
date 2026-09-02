package com.apiops.openapi.normalizer;

import com.apiops.openapi.parser.OpenApiDocumentParser;
import com.fasterxml.jackson.databind.JsonNode;
import io.swagger.v3.core.util.Json;
import io.swagger.v3.oas.models.Components;
import io.swagger.v3.oas.models.OpenAPI;
import io.swagger.v3.oas.models.media.ObjectSchema;
import io.swagger.v3.oas.models.media.Schema;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;

import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertThrows;

class SchemaNormalizerTest {

    private static OpenAPI openApi;

    private final SchemaNormalizer normalizer = new SchemaNormalizer();

    @BeforeAll
    static void parseFixture() {
        openApi = new OpenApiDocumentParser().parse(fixture()).openApi();
    }

    @Test
    void shouldResolveInternalSchemaReference() throws Exception {
        JsonNode schema = normalize("DirectAddress");

        assertEquals("object", schema.get("type").asText());
        assertEquals("string", schema.at("/properties/city/type").asText());
        assertFalse(schema.has("$ref"));
    }

    @Test
    void shouldResolveNestedReferences() throws Exception {
        JsonNode schema = normalize("Order");

        assertEquals("string",
                schema.at("/properties/customer/properties/address/properties/city/type")
                        .asText());
    }

    @Test
    void shouldResolveSharedReferenceInBothSiblingBranches() throws Exception {
        JsonNode schema = normalize("Order");

        assertEquals("string",
                schema.at("/properties/billingAddress/properties/city/type").asText());
        assertEquals("string",
                schema.at("/properties/shippingAddress/properties/city/type").asText());
    }

    @Test
    void shouldStopSelfCycleAndKeepCanonicalReference() throws Exception {
        JsonNode schema = normalize("TreeNodeRequest");

        assertEquals("#/components/schemas/TreeNode",
                schema.at("/properties/child/$ref").asText());
    }

    @Test
    void shouldStopMutualCycleAndKeepCanonicalReference() throws Exception {
        JsonNode schema = normalize("ARequest");

        assertEquals("#/components/schemas/A",
                schema.at("/properties/b/properties/a/$ref").asText());
    }

    @Test
    void shouldRejectMissingInternalReference() {
        OpenApiNormalizationException exception = assertThrows(
                OpenApiNormalizationException.class,
                () -> normalize(new Schema<>().$ref(
                        "#/components/schemas/DoesNotExist"))
        );

        assertEquals(OpenApiNormalizationException.Reason.MISSING_INTERNAL_REFERENCE,
                exception.reason());
        assertEquals("MISSING_INTERNAL_REFERENCE: '#/components/schemas/DoesNotExist'",
                exception.getMessage());
    }

    @ParameterizedTest
    @ValueSource(strings = {"HttpRoot", "HttpsRoot"})
    void shouldRejectRemoteHttpReferences(String schemaName) {
        OpenApiNormalizationException exception = assertThrows(
                OpenApiNormalizationException.class,
                () -> normalize(schemaName)
        );

        assertEquals(OpenApiNormalizationException.Reason.REMOTE_REFERENCE_NOT_ALLOWED,
                exception.reason());
    }

    @Test
    void shouldNotAffectLaterIndependentNormalizationAfterFailure() throws Exception {
        OpenAPI brokenDocument = new OpenAPI().components(new Components().addSchemas(
                "Broken",
                new ObjectSchema().addProperty("missing", new Schema<>().$ref(
                        "#/components/schemas/DoesNotExist"))
        ));
        assertThrows(OpenApiNormalizationException.class,
                () -> normalize(new Schema<>().$ref(
                        "#/components/schemas/Broken"), brokenDocument));

        assertEquals("string",
                normalize("DirectAddress").at("/properties/city/type").asText());
    }

    private JsonNode normalize(String schemaName) throws Exception {
        return normalize(openApi.getComponents().getSchemas().get(schemaName));
    }

    private JsonNode normalize(Schema<?> schema) throws Exception {
        return normalize(schema, openApi);
    }

    private JsonNode normalize(Schema<?> schema, OpenAPI document) throws Exception {
        return Json.mapper().readTree(normalizer.toJson(schema, document));
    }

    private static String fixture() {
        try (InputStream input = SchemaNormalizerTest.class.getResourceAsStream(
                "/openapi/schema-refs.yaml")) {
            if (input == null) {
                throw new IllegalStateException("Missing schema ref fixture");
            }
            return new String(input.readAllBytes(), StandardCharsets.UTF_8);
        } catch (IOException exception) {
            throw new IllegalStateException("Cannot read schema ref fixture", exception);
        }
    }
}
