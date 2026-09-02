package com.apiops.report.exception;

import com.apiops.common.enums.ErrorCode;
import com.apiops.common.result.Result;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;

@RestControllerAdvice
public final class TestReportExceptionHandler {

    @ExceptionHandler(TestReportNotFoundException.class)
    public ResponseEntity<Result<Void>> handleNotFound(TestReportNotFoundException exception) {
        return ResponseEntity.status(HttpStatus.NOT_FOUND)
                .body(Result.fail(ErrorCode.RESOURCE_NOT_FOUND));
    }
}
