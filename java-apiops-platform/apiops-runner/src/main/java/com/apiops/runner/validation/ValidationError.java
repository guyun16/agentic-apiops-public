package com.apiops.runner.validation;

public record ValidationError(
        String path,
        String code,
        String message
) {
}
