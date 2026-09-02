package com.apiops.openapi.controller;

import com.apiops.common.result.Result;
import com.apiops.openapi.application.OpenApiQueryApplicationService;
import com.apiops.openapi.vo.ApiDocumentVO;
import com.apiops.openapi.vo.ApiMetadataDetailVO;
import com.apiops.openapi.vo.ApiMetadataSummaryVO;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;

@RestController
@RequestMapping("/api/v1/projects/{projectId}/openapi")
public final class OpenApiMetadataQueryController {

    private final OpenApiQueryApplicationService queryService;

    public OpenApiMetadataQueryController(OpenApiQueryApplicationService queryService) {
        this.queryService = queryService;
    }

    @GetMapping("/documents")
    public Result<List<ApiDocumentVO>> documents(@PathVariable long projectId) {
        return Result.success(queryService.listDocuments(projectId));
    }

    @GetMapping("/documents/{apiDocId}")
    public Result<ApiDocumentVO> document(
            @PathVariable long projectId,
            @PathVariable String apiDocId
    ) {
        return Result.success(queryService.getDocument(projectId, apiDocId));
    }

    @GetMapping("/apis")
    public Result<List<ApiMetadataSummaryVO>> apis(@PathVariable long projectId) {
        return Result.success(queryService.listApis(projectId));
    }

    @GetMapping("/apis/{apiId}")
    public Result<ApiMetadataDetailVO> api(
            @PathVariable long projectId,
            @PathVariable String apiId
    ) {
        return Result.success(queryService.getApi(projectId, apiId));
    }
}
