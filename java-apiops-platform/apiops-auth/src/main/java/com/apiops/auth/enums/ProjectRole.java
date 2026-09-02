package com.apiops.auth.enums;

import java.util.Optional;

/** Project-scoped roles; global roles do not bypass this membership boundary. */
public enum ProjectRole {

    OWNER,
    EDITOR,
    VIEWER;

    public static Optional<ProjectRole> fromCode(String code) {
        if (code == null || code.isBlank()) {
            return Optional.empty();
        }
        try {
            return Optional.of(valueOf(code));
        } catch (IllegalArgumentException exception) {
            return Optional.empty();
        }
    }
}
