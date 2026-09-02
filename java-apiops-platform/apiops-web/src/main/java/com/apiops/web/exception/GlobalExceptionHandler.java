package com.apiops.web.exception;

import com.apiops.auth.exception.AuthenticationFailureException;
import com.apiops.auth.enums.AuthErrorCode;
import com.apiops.common.enums.ErrorCode;
import com.apiops.common.exception.BusinessException;
import com.apiops.common.result.Result;
import org.springframework.security.access.AccessDeniedException;
import com.apiops.web.project.exception.ProjectNotFoundException;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;
import org.springframework.web.servlet.resource.NoResourceFoundException;

import java.util.LinkedHashMap;
import java.util.Map;

/**
 * Maps controller exceptions to the platform's unified response contract.
 */
@RestControllerAdvice
public class GlobalExceptionHandler {

    private static final Logger LOGGER = LoggerFactory.getLogger(GlobalExceptionHandler.class);

    @ExceptionHandler(AuthenticationFailureException.class)
    public ResponseEntity<Map<String, Object>> handleAuthenticationFailure(
            AuthenticationFailureException exception
    ) {
        Map<String, Object> response = new LinkedHashMap<>();
        response.put("success", false);
        response.put("code", exception.getErrorCode().getCode());
        response.put("message", exception.getErrorCode().getMessage());
        response.put("data", null);
        return ResponseEntity.status(HttpStatus.UNAUTHORIZED)
                .body(response);
    }

    @ExceptionHandler(BusinessException.class)
    public ResponseEntity<Result<Void>> handleBusinessException(BusinessException exception) {
        Result<Void> result = Result.fail(exception.getErrorCode(), exception.getMessage());
        return ResponseEntity.status(HttpStatus.BAD_REQUEST).body(result);
    }

    @ExceptionHandler(AccessDeniedException.class)
    public ResponseEntity<Map<String, Object>> handleAccessDenied(AccessDeniedException exception) {
        Map<String, Object> response = new LinkedHashMap<>();
        response.put("success", false);
        response.put("code", AuthErrorCode.ACCESS_DENIED.getCode());
        response.put("message", AuthErrorCode.ACCESS_DENIED.getMessage());
        response.put("data", null);
        return ResponseEntity.status(HttpStatus.FORBIDDEN).body(response);
    }

    @ExceptionHandler(NoResourceFoundException.class)
    public ResponseEntity<Void> handleNoResourceFoundException(
            NoResourceFoundException exception
    ) {
        return ResponseEntity.notFound().build();
    }

    @ExceptionHandler(ProjectNotFoundException.class)
    public ResponseEntity<Result<Void>> handleProjectNotFound(ProjectNotFoundException exception) {
        return ResponseEntity.status(HttpStatus.NOT_FOUND)
                .body(Result.fail(ErrorCode.RESOURCE_NOT_FOUND));
    }

    @ExceptionHandler(Exception.class)
    public ResponseEntity<Result<Void>> handleUnknownException(Exception exception) {
        LOGGER.error("Unhandled exception while processing request", exception);
        return ResponseEntity.status(HttpStatus.INTERNAL_SERVER_ERROR)
                .body(Result.fail(ErrorCode.SYSTEM_ERROR));
    }
}
