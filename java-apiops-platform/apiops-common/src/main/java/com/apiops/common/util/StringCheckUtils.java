package com.apiops.common.util;

public final class StringCheckUtils {

    private StringCheckUtils() {
    }

    public static boolean hasText(String value) {
        return value != null && !value.trim().isEmpty();
    }

    public static boolean isBlank(String value) {
        return !hasText(value);
    }
}