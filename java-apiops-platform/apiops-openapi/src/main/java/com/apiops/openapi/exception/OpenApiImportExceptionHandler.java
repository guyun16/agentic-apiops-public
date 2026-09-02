package com.apiops.openapi.exception;

import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;
import org.springframework.web.multipart.MaxUploadSizeExceededException;

import java.util.LinkedHashMap;
import java.util.Map;

@RestControllerAdvice
public class OpenApiImportExceptionHandler {

    @ExceptionHandler(OpenApiImportException.class)
    public ResponseEntity<Map<String, Object>> handle(OpenApiImportException exception) {
        return response(exception.errorCode());
    }

    @ExceptionHandler(MaxUploadSizeExceededException.class)
    public ResponseEntity<Map<String, Object>> handleMaxUploadSizeExceeded(
            MaxUploadSizeExceededException exception
    ) {
        return response(OpenApiImportErrorCode.FILE_TOO_LARGE);
    }

    private ResponseEntity<Map<String, Object>> response(OpenApiImportErrorCode errorCode) {
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("success", false);
        body.put("code", errorCode.name());
        body.put("message", message(errorCode));
        body.put("data", null);
        return ResponseEntity.status(status(errorCode)).body(body);
    }

    private HttpStatus status(OpenApiImportErrorCode errorCode) {
        return errorCode == OpenApiImportErrorCode.FILE_TOO_LARGE
                ? HttpStatus.PAYLOAD_TOO_LARGE
                : HttpStatus.BAD_REQUEST;
    }

    private String message(OpenApiImportErrorCode errorCode) {
        return switch (errorCode) {
            case EMPTY_FILE -> "OpenAPI file must not be empty";
            case FILE_TOO_LARGE -> "OpenAPI file exceeds the configured size limit";
            case FILE_READ_FAILED -> "OpenAPI file could not be read";
            case INVALID_SOURCE_KEY -> "sourceKey must not be blank";
            case INVALID_OPENAPI -> "Uploaded content is not a valid supported OpenAPI document";
            case UNSUPPORTED_OPENAPI_VERSION -> "OpenAPI version is not supported";
            case REMOTE_REF_NOT_ALLOWED -> "Remote OpenAPI references are not allowed";
        };
    }
}
