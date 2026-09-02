package com.apiops.openapi.exception;

import com.apiops.common.enums.ErrorCode;
import com.apiops.common.result.Result;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;

@RestControllerAdvice
public final class OpenApiQueryExceptionHandler {

    @ExceptionHandler(OpenApiMetadataNotFoundException.class)
    public ResponseEntity<Result<Void>> handleNotFound(
            OpenApiMetadataNotFoundException exception
    ) {
        return ResponseEntity.status(HttpStatus.NOT_FOUND)
                .body(Result.fail(ErrorCode.RESOURCE_NOT_FOUND));
    }
}
