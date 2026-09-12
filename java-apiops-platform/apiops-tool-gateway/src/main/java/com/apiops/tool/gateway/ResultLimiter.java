package com.apiops.tool.gateway;

import java.util.ArrayList;
import java.util.Collection;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Objects;

/** Applies a small output character budget after sanitization. */
public final class ResultLimiter {

    public static final String TRUNCATED_MARKER = "[TRUNCATED]";
    public static final String TRUNCATED_FIELD = "_resultTruncated";

    private final int maxCharacters;

    public ResultLimiter(int maxCharacters) {
        if (maxCharacters <= 0) {
            throw new IllegalArgumentException("maxCharacters must be positive");
        }
        this.maxCharacters = maxCharacters;
    }

    public LimitedResult limit(Object sanitizedResult) {
        Budget budget = new Budget(maxCharacters);
        Object value = limit(sanitizedResult, budget);
        if (budget.truncated && value instanceof Map<?, ?> map) {
            Map<Object, Object> topLevel = new LinkedHashMap<>(map);
            topLevel.put(TRUNCATED_FIELD, true);
            value = topLevel;
        }
        return new LimitedResult(value, budget.truncated);
    }

    public int maxCharacters() {
        return maxCharacters;
    }

    private Object limit(Object value, Budget budget) {
        if (value == null) {
            return value;
        }
        if (value instanceof Number || value instanceof Boolean || value instanceof Enum<?>) {
            String text = String.valueOf(value);
            if (text.length() <= budget.remaining) {
                budget.remaining -= text.length();
                return value;
            }
            return limitString(text, budget);
        }
        if (value instanceof String string) {
            return limitString(string, budget);
        }
        if (value instanceof Map<?, ?> map) {
            Map<Object, Object> limited = new LinkedHashMap<>();
            for (Map.Entry<?, ?> entry : map.entrySet()) {
                if (budget.remaining <= 0) {
                    budget.truncated = true;
                    break;
                }
                limited.put(entry.getKey(), limit(entry.getValue(), budget));
            }
            return limited;
        }
        if (value instanceof Collection<?> collection) {
            List<Object> limited = new ArrayList<>();
            for (Object item : collection) {
                if (budget.remaining <= 0) {
                    budget.truncated = true;
                    break;
                }
                Budget candidateBudget = budget.copy();
                Object candidate = limit(item, candidateBudget);
                if (candidateBudget.truncated) {
                    budget.truncated = true;
                    break;
                }
                limited.add(candidate);
                budget.remaining = candidateBudget.remaining;
            }
            return limited;
        }
        return limitString(Objects.toString(value), budget);
    }

    private static String limitString(String value, Budget budget) {
        if (value.length() <= budget.remaining) {
            budget.remaining -= value.length();
            return value;
        }
        budget.truncated = true;
        int prefixLength = Math.max(0, budget.remaining - TRUNCATED_MARKER.length());
        String prefix = value.substring(0, Math.min(prefixLength, value.length()));
        budget.remaining = 0;
        return prefix + TRUNCATED_MARKER;
    }

    private static final class Budget {
        private int remaining;
        private boolean truncated;

        private Budget(int remaining) {
            this.remaining = remaining;
        }

        private Budget copy() {
            return new Budget(remaining);
        }
    }

    public record LimitedResult(Object value, boolean truncated) {
    }
}
