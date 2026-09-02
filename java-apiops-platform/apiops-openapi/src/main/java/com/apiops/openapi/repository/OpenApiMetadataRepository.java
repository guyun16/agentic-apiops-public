package com.apiops.openapi.repository;

import com.apiops.openapi.domain.ApiDocument;
import com.apiops.openapi.domain.ApiEndpoint;
import com.apiops.openapi.domain.ApiExample;
import com.apiops.openapi.domain.ApiParameter;
import com.apiops.openapi.domain.ApiRequestSchema;
import com.apiops.openapi.domain.ApiResponseSchema;

import java.util.List;
import java.util.Optional;

/** Persistence boundary used by metadata import and lookup. */
public interface OpenApiMetadataRepository {

    ApiDocument save(ApiDocument document);

    Optional<ApiDocument> findDocument(long projectId, String apiDocId);

    Optional<ApiDocument> findDocument(
            long projectId, String sourceKey, String contentHash);

    Optional<ApiDocument> findLatestDocument(long projectId, String sourceKey);

    List<ApiDocument> findDocuments(long projectId);

    ApiEndpoint save(ApiEndpoint endpoint);

    Optional<ApiEndpoint> findEndpoint(long projectId, String apiId);

    List<ApiEndpoint> findEndpoints(long projectId);

    ApiParameter save(ApiParameter parameter);

    List<ApiParameter> findParameters(long projectId, String apiId);

    ApiRequestSchema save(ApiRequestSchema requestSchema);

    List<ApiRequestSchema> findRequestSchemas(long projectId, String apiId);

    ApiResponseSchema save(ApiResponseSchema responseSchema);

    List<ApiResponseSchema> findResponseSchemas(long projectId, String apiId);

    ApiExample save(ApiExample example);

    List<ApiExample> findExamples(long projectId, String apiId);
}
