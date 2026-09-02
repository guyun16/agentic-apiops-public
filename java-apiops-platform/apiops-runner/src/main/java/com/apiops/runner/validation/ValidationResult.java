package com.apiops.runner.validation;

import java.util.List;

public record ValidationResult(
        boolean valid,
        List<ValidationError> errors
) {
    public ValidationResult {
        errors = List.copyOf(errors);
    }

    public static ValidationResult success() {
        return new ValidationResult(true, List.of());
    }

    public static ValidationResult invalid(List<ValidationError> errors) {
        return new ValidationResult(false, errors);
    }
}
