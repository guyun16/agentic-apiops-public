package com.apiops.openapi.normalizer;

import com.apiops.openapi.domain.ApiEndpoint;
import com.apiops.openapi.domain.ApiExample;
import com.apiops.openapi.domain.ApiParameter;
import com.apiops.openapi.domain.ApiRequestSchema;
import com.apiops.openapi.domain.ApiResponseSchema;
import com.apiops.openapi.parser.ParsedOpenApiDocument;
import io.swagger.v3.oas.models.OpenAPI;
import io.swagger.v3.oas.models.Operation;
import io.swagger.v3.oas.models.PathItem;
import io.swagger.v3.oas.models.examples.Example;
import io.swagger.v3.oas.models.media.Content;
import io.swagger.v3.oas.models.media.MediaType;
import io.swagger.v3.oas.models.parameters.Parameter;
import io.swagger.v3.oas.models.parameters.RequestBody;
import io.swagger.v3.oas.models.responses.ApiResponse;
import io.swagger.v3.oas.models.security.SecurityRequirement;
import io.swagger.v3.oas.models.servers.Server;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.Set;
import java.util.function.BiFunction;

/** Converts Swagger's OpenAPI object model into the established Metadata records. */
public final class OpenApiMetadataNormalizer {

    private static final Set<String> PARAMETER_LOCATIONS =
            Set.of("path", "query", "header", "cookie");
    private static final String REQUEST_SCHEMA = "REQUEST_SCHEMA";
    private static final String RESPONSE_SCHEMA = "RESPONSE_SCHEMA";
    private static final String PARAMETER = "PARAMETER";

    private final SchemaNormalizer schemaNormalizer;

    public OpenApiMetadataNormalizer() {
        this(new SchemaNormalizer());
    }

    OpenApiMetadataNormalizer(SchemaNormalizer schemaNormalizer) {
        this.schemaNormalizer = Objects.requireNonNull(schemaNormalizer);
    }

    public NormalizedOpenApiMetadata normalize(
            ParsedOpenApiDocument parsedDocument,
            String apiDocId,
            long projectId,
            BiFunction<String, String, String> apiIdFactory
    ) {
        Objects.requireNonNull(parsedDocument, "parsedDocument must not be null");
        Objects.requireNonNull(apiDocId, "apiDocId must not be null");
        Objects.requireNonNull(apiIdFactory, "apiIdFactory must not be null");

        State state = new State();
        OpenAPI openApi = parsedDocument.openApi();
        if (openApi.getPaths() != null) {
            openApi.getPaths().forEach((path, pathItem) ->
                    normalizePath(openApi, path, pathItem, apiDocId,
                            projectId, apiIdFactory, state));
        }
        return state.result();
    }

    private void normalizePath(
            OpenAPI openApi,
            String path,
            PathItem pathItem,
            String apiDocId,
            long projectId,
            BiFunction<String, String, String> apiIdFactory,
            State state
    ) {
        if (pathItem == null) {
            return;
        }
        pathItem.readOperationsMap().forEach((method, operation) -> {
            String httpMethod = method.name();
            validateOperationId(operation, httpMethod, path, state);
            String apiId = Objects.requireNonNull(
                    apiIdFactory.apply(httpMethod, path), "apiIdFactory returned null");
            state.endpoints.add(endpoint(openApi, pathItem, operation,
                    apiId, apiDocId, projectId, httpMethod, path));
            normalizeParameters(openApi, pathItem, operation, apiId, projectId, state);
            normalizeRequest(openApi, operation.getRequestBody(), apiId, projectId, state);
            normalizeResponses(openApi, operation, apiId, projectId, state);
        });
    }

    private void validateOperationId(
            Operation operation,
            String method,
            String path,
            State state
    ) {
        String operationId = operation.getOperationId();
        if (operationId == null || operationId.isBlank()) {
            throw OpenApiNormalizationException.blankOperationId(method, path);
        }
        OperationLocation first = state.operationIds.putIfAbsent(
                operationId, new OperationLocation(method, path));
        if (first != null) {
            throw OpenApiNormalizationException.duplicateOperationId(
                    operationId, method, path, first.method(), first.path());
        }
    }

    private ApiEndpoint endpoint(
            OpenAPI openApi,
            PathItem pathItem,
            Operation operation,
            String apiId,
            String apiDocId,
            long projectId,
            String method,
            String path
    ) {
        List<Server> servers = operation.getServers() != null
                ? operation.getServers()
                : pathItem.getServers() != null ? pathItem.getServers() : openApi.getServers();
        List<SecurityRequirement> security = operation.getSecurity() != null
                ? operation.getSecurity() : openApi.getSecurity();
        return new ApiEndpoint(
                0, apiId, apiDocId, projectId, operation.getOperationId(), method, path,
                operation.getSummary(), operation.getDescription(),
                jsonOrNull(operation.getTags()), jsonOrNull(servers), jsonOrNull(security),
                Boolean.TRUE.equals(operation.getDeprecated()), null, null
        );
    }

    private void normalizeParameters(
            OpenAPI openApi,
            PathItem pathItem,
            Operation operation,
            String apiId,
            long projectId,
            State state
    ) {
        Map<ParameterKey, Parameter> merged = new LinkedHashMap<>();
        addParameters(merged, pathItem.getParameters());
        addParameters(merged, operation.getParameters());
        for (Parameter source : merged.values()) {
            long ownerId = state.nextOwnerId();
            Object example = source.getExample() != null
                    ? source.getExample()
                    : source.getSchema() == null ? null : source.getSchema().getExample();
            state.parameters.add(new ApiParameter(
                    ownerId, apiId, projectId, source.getName(), source.getIn(),
                    Boolean.TRUE.equals(source.getRequired()), source.getDescription(),
                    schemaNormalizer.toJson(source.getSchema(), openApi), jsonOrNull(example), null
            ));
            addNamedExamples(source.getExamples(), apiId, projectId,
                    PARAMETER, ownerId, state.examples);
        }
    }

    private void addParameters(
            Map<ParameterKey, Parameter> target,
            List<Parameter> parameters
    ) {
        if (parameters == null) {
            return;
        }
        parameters.stream()
                .filter(Objects::nonNull)
                .filter(parameter -> parameter.getName() != null)
                .filter(parameter -> PARAMETER_LOCATIONS.contains(parameter.getIn()))
                .forEach(parameter -> target.put(
                        new ParameterKey(parameter.getName(), parameter.getIn()), parameter));
    }

    private void normalizeRequest(
            OpenAPI openApi,
            RequestBody requestBody,
            String apiId,
            long projectId,
            State state
    ) {
        if (requestBody == null || requestBody.getContent() == null) {
            return;
        }
        requestBody.getContent().forEach((mediaTypeName, mediaType) -> {
            long ownerId = state.nextOwnerId();
            state.requestSchemas.add(new ApiRequestSchema(
                    ownerId, apiId, projectId, Boolean.TRUE.equals(requestBody.getRequired()),
                    mediaTypeName, schemaNormalizer.toJson(mediaType.getSchema(), openApi), null
            ));
            addMediaTypeExamples(mediaType, apiId, projectId,
                    REQUEST_SCHEMA, ownerId, state.examples);
        });
    }

    private void normalizeResponses(
            OpenAPI openApi,
            Operation operation,
            String apiId,
            long projectId,
            State state
    ) {
        if (operation.getResponses() == null) {
            return;
        }
        operation.getResponses().forEach((statusCode, response) -> {
            Content content = response.getContent();
            if (content == null || content.isEmpty()) {
                state.responseSchemas.add(new ApiResponseSchema(
                        state.nextOwnerId(), apiId, projectId, statusCode,
                        response.getDescription(), "", schemaNormalizer.toJson(null), null));
                return;
            }
            content.forEach((mediaTypeName, mediaType) ->
                    normalizeResponseMediaType(openApi, statusCode, response, mediaTypeName,
                            mediaType, apiId, projectId, state));
        });
    }

    private void normalizeResponseMediaType(
            OpenAPI openApi,
            String statusCode,
            ApiResponse response,
            String mediaTypeName,
            MediaType mediaType,
            String apiId,
            long projectId,
            State state
    ) {
        long ownerId = state.nextOwnerId();
        state.responseSchemas.add(new ApiResponseSchema(
                ownerId, apiId, projectId, statusCode, response.getDescription(),
                mediaTypeName, schemaNormalizer.toJson(mediaType.getSchema(), openApi), null));
        addMediaTypeExamples(mediaType, apiId, projectId,
                RESPONSE_SCHEMA, ownerId, state.examples);
    }

    private void addMediaTypeExamples(
            MediaType mediaType,
            String apiId,
            long projectId,
            String ownerType,
            long ownerId,
            List<ApiExample> target
    ) {
        if (mediaType.getExample() != null) {
            target.add(new ApiExample(
                    0, apiId, projectId, ownerType, ownerId, "default",
                    null, null, schemaNormalizer.toJson(mediaType.getExample()), null));
        }
        addNamedExamples(mediaType.getExamples(), apiId, projectId,
                ownerType, ownerId, target);
    }

    private void addNamedExamples(
            Map<String, Example> examples,
            String apiId,
            long projectId,
            String ownerType,
            long ownerId,
            List<ApiExample> target
    ) {
        if (examples == null) {
            return;
        }
        examples.forEach((name, example) -> {
            Object value = example.getValue() != null ? example.getValue() : example;
            target.add(new ApiExample(
                    0, apiId, projectId, ownerType, ownerId, name,
                    example.getSummary(), example.getDescription(),
                    schemaNormalizer.toJson(value), null));
        });
    }

    private String jsonOrNull(Object value) {
        return value == null ? null : schemaNormalizer.toJson(value);
    }

    private record ParameterKey(String name, String location) {
    }

    private record OperationLocation(String method, String path) {
    }

    private static final class State {
        private final List<ApiEndpoint> endpoints = new ArrayList<>();
        private final List<ApiParameter> parameters = new ArrayList<>();
        private final List<ApiRequestSchema> requestSchemas = new ArrayList<>();
        private final List<ApiResponseSchema> responseSchemas = new ArrayList<>();
        private final List<ApiExample> examples = new ArrayList<>();
        private final Map<String, OperationLocation> operationIds = new LinkedHashMap<>();
        // ponytail: negative ids only correlate examples in memory; Day 10 remaps generated DB ids.
        private long nextOwnerId = -1;

        private long nextOwnerId() {
            return nextOwnerId--;
        }

        private NormalizedOpenApiMetadata result() {
            return new NormalizedOpenApiMetadata(
                    endpoints, parameters, requestSchemas, responseSchemas, examples);
        }
    }
}
