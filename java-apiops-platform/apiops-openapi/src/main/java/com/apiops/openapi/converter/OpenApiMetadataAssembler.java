package com.apiops.openapi.converter;

import com.apiops.openapi.domain.ApiDocument;
import com.apiops.openapi.domain.ApiEndpoint;
import com.apiops.openapi.domain.ApiExample;
import com.apiops.openapi.domain.ApiParameter;
import com.apiops.openapi.domain.ApiRequestSchema;
import com.apiops.openapi.domain.ApiResponseSchema;
import com.apiops.openapi.vo.ApiDocumentVO;
import com.apiops.openapi.vo.ApiMetadataDetailVO;
import com.apiops.openapi.vo.ApiMetadataSummaryVO;
import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.JsonNode;
import io.swagger.v3.core.util.Json;

import java.util.HashMap;
import java.util.List;
import java.util.Map;

public final class OpenApiMetadataAssembler {

    public ApiDocumentVO document(ApiDocument value) {
        return new ApiDocumentVO(
                value.apiDocId(), value.projectId(), value.sourceKey(), value.documentName(),
                value.openapiVersion(), value.title(), value.apiVersion(),
                value.documentFormat(), value.contentHash(), value.versionNo(),
                value.status(), value.createdAt(), value.updatedAt());
    }

    public ApiMetadataSummaryVO summary(ApiEndpoint value) {
        return new ApiMetadataSummaryVO(
                value.apiId(), value.apiDocId(), value.operationId(),
                value.httpMethod(), value.path(), value.summary(),
                json(value.tagsJson()), value.deprecated());
    }

    public ApiMetadataDetailVO detail(
            ApiEndpoint endpoint,
            List<ApiParameter> parameters,
            List<ApiRequestSchema> requestSchemas,
            List<ApiResponseSchema> responseSchemas,
            List<ApiExample> examples
    ) {
        Map<Long, ApiMetadataDetailVO.ExampleOwnerVO> owners = owners(
                parameters, requestSchemas, responseSchemas);
        return new ApiMetadataDetailVO(
                endpoint.apiId(), endpoint.apiDocId(), endpoint.operationId(),
                endpoint.httpMethod(), endpoint.path(), endpoint.summary(),
                endpoint.description(), json(endpoint.tagsJson()),
                json(endpoint.serversJson()), json(endpoint.securityJson()),
                endpoint.deprecated(),
                parameters.stream().map(this::parameter).toList(),
                requestSchemas.stream().map(this::requestSchema).toList(),
                responseSchemas.stream().map(this::responseSchema).toList(),
                examples.stream().map(value -> example(value, owners)).toList()
        );
    }

    private ApiMetadataDetailVO.ParameterVO parameter(ApiParameter value) {
        return new ApiMetadataDetailVO.ParameterVO(
                value.name(), value.location(), value.required(), value.description(),
                json(value.schemaJson()), json(value.exampleJson()));
    }

    private ApiMetadataDetailVO.RequestSchemaVO requestSchema(ApiRequestSchema value) {
        return new ApiMetadataDetailVO.RequestSchemaVO(
                value.required(), value.mediaType(), json(value.schemaJson()));
    }

    private ApiMetadataDetailVO.ResponseSchemaVO responseSchema(ApiResponseSchema value) {
        return new ApiMetadataDetailVO.ResponseSchemaVO(
                value.statusCode(), value.description(), value.mediaType(),
                json(value.schemaJson()));
    }

    private ApiMetadataDetailVO.ExampleVO example(
            ApiExample value,
            Map<Long, ApiMetadataDetailVO.ExampleOwnerVO> owners
    ) {
        ApiMetadataDetailVO.ExampleOwnerVO owner = owners.get(value.ownerRefId());
        if (owner == null) {
            throw new IllegalStateException("Example owner metadata is missing");
        }
        return new ApiMetadataDetailVO.ExampleVO(
                owner, value.exampleName(), value.summary(), value.description(),
                json(value.valueJson()));
    }

    private Map<Long, ApiMetadataDetailVO.ExampleOwnerVO> owners(
            List<ApiParameter> parameters,
            List<ApiRequestSchema> requestSchemas,
            List<ApiResponseSchema> responseSchemas
    ) {
        Map<Long, ApiMetadataDetailVO.ExampleOwnerVO> owners = new HashMap<>();
        parameters.forEach(value -> owners.put(value.id(),
                new ApiMetadataDetailVO.ExampleOwnerVO(
                        "PARAMETER", value.name(), value.location(), null, null)));
        requestSchemas.forEach(value -> owners.put(value.id(),
                new ApiMetadataDetailVO.ExampleOwnerVO(
                        "REQUEST_SCHEMA", null, null, value.mediaType(), null)));
        responseSchemas.forEach(value -> owners.put(value.id(),
                new ApiMetadataDetailVO.ExampleOwnerVO(
                        "RESPONSE_SCHEMA", null, null,
                        value.mediaType(), value.statusCode())));
        return owners;
    }

    private JsonNode json(String value) {
        if (value == null) {
            return null;
        }
        try {
            return Json.mapper().readTree(value);
        } catch (JsonProcessingException exception) {
            throw new IllegalStateException("Stored OpenAPI metadata contains invalid JSON",
                    exception);
        }
    }
}
