package com.apiops.common.util;

import java.time.LocalDateTime;
import java.time.format.DateTimeFormatter;

public final class TimeUtils {

    public static final String DEFAULT_PATTERN = "yyyy-MM-dd HH:mm:ss";

    private static final DateTimeFormatter DEFAULT_FORMATTER =
            DateTimeFormatter.ofPattern(DEFAULT_PATTERN);

    private TimeUtils() {
        throw new AssertionError("No com.apiops.common.util.TimeUtils instances");
    }

    public static LocalDateTime now() {
        return LocalDateTime.now();
    }

    public static String format(LocalDateTime time) {
        if (time == null) {
            return null;
        }
        return time.format(DEFAULT_FORMATTER);
    }

    public static LocalDateTime parse(String timeText) {
        if (timeText == null || timeText.isBlank()) {
            return null;
        }
        return LocalDateTime.parse(timeText, DEFAULT_FORMATTER);
    }
}