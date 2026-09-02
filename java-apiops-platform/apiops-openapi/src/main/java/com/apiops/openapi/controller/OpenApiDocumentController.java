package com.apiops.openapi.controller;

import com.apiops.common.result.Result;
import com.apiops.openapi.application.OpenApiImportApplicationService;
import com.apiops.openapi.application.OpenApiImportResult;
import org.springframework.http.MediaType;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.multipart.MultipartFile;

@RestController
@RequestMapping("/api/v1/projects/{projectId}/openapi/documents")
public class OpenApiDocumentController {

    private final OpenApiImportApplicationService importService;

    public OpenApiDocumentController(OpenApiImportApplicationService importService) {
        this.importService = importService;
    }

    @PostMapping(consumes = MediaType.MULTIPART_FORM_DATA_VALUE)
    public Result<OpenApiImportResponse> upload(
            @PathVariable long projectId,
            @RequestParam String sourceKey,
            @RequestParam MultipartFile file
    ) {
        OpenApiImportResult imported = importService.importDocument(projectId, sourceKey, file);
        return Result.success(new OpenApiImportResponse(
                imported.projectId(),
                imported.sourceKey(),
                imported.filename(),
                imported.fileSize(),
                imported.contentHash(),
                imported.parsedDocument().openapiVersion()
        ));
    }
}
