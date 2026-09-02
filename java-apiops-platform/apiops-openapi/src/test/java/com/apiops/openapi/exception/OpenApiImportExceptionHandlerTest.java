package com.apiops.openapi.exception;

import org.junit.jupiter.api.Test;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.multipart.MaxUploadSizeExceededException;

import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;

class OpenApiImportExceptionHandlerTest {

    private final OpenApiImportExceptionHandler handler =
            new OpenApiImportExceptionHandler();

    @Test
    void shouldReturnStableCodeForApplicationSizeLimit() {
        assertFileTooLarge(handler.handle(
                new OpenApiImportException(OpenApiImportErrorCode.FILE_TOO_LARGE)
        ));
    }

    @Test
    void shouldReturnTheSameStableCodeForServletSizeLimit() {
        assertFileTooLarge(handler.handleMaxUploadSizeExceeded(
                new MaxUploadSizeExceededException(1024)
        ));
    }

    private void assertFileTooLarge(ResponseEntity<Map<String, Object>> response) {
        assertEquals(HttpStatus.PAYLOAD_TOO_LARGE, response.getStatusCode());
        assertEquals("FILE_TOO_LARGE", response.getBody().get("code"));
    }
}
