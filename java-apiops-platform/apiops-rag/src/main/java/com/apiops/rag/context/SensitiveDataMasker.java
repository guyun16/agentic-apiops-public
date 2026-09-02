package com.apiops.rag.context;

import java.util.List;
import java.util.LinkedHashSet;
import java.util.Set;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

public class SensitiveDataMasker {

    private static final String REDACTED = "[REDACTED]";
    private static final List<Rule> RULES = List.of(
            rule("(?i)(\\bAuthorization\\b\\s*[\"']?\\s*[:=]\\s*[\"']?\\s*)(?:Bearer\\s+)?([^\"'\\s,;}\\]]+)", "$1" + REDACTED),
            rule("(?i)(\\bBearer\\s+)([A-Za-z0-9._~+/=-]+)", "$1" + REDACTED),
            rule("(?i)(\\b(?:Cookie|Set-Cookie)\\b\\s*[\"']?\\s*[:=]\\s*[\"']?\\s*)([^\"'\\r\\n}]+)", "$1" + REDACTED),
            rule("(?i)(\\b(?:password|passwd|api[-_ ]?key|secret)\\b\\s*[\"']?\\s*[:=]\\s*[\"']?\\s*)([^\"'\\s,;}&]+)", "$1" + REDACTED),
            rule("(?i)((?:jdbc:)?(?:mysql|postgresql|mariadb)://)([^/@\\s:]+):([^@\\s/]+)@", "$1" + REDACTED + ":" + REDACTED + "@")
    );
    private static final List<ValueRule> VALUE_RULES = List.of(
            valueRule("(?i)(\\bAuthorization\\b\\s*[\"']?\\s*[:=]\\s*[\"']?\\s*)(?:Bearer\\s+)?([^\"'\\s,;}\\]]+)", 2),
            valueRule("(?i)(\\bBearer\\s+)([A-Za-z0-9._~+/=-]+)", 2),
            valueRule("(?i)\\b(?:Cookie|Set-Cookie)\\b\\s*[\"']?\\s*[:=]\\s*[\"']?\\s*[^=;\"'\\r\\n]+[=:]([^;\"'\\r\\n]+)", 1),
            valueRule("(?i)(\\b(?:password|passwd|api[-_ ]?key|secret)\\b\\s*[\"']?\\s*[:=]\\s*[\"']?\\s*)([^\"'\\s,;}&]+)", 2),
            valueRule("(?i)((?:jdbc:)?(?:mysql|postgresql|mariadb)://)([^/@\\s:]+):([^@\\s/]+)@", 2),
            valueRule("(?i)((?:jdbc:)?(?:mysql|postgresql|mariadb)://)([^/@\\s:]+):([^@\\s/]+)@", 3)
    );

    public List<ContextItem> maskAll(List<ContextItem> items) {
        List<ContextItem> values = List.copyOf(items);
        Set<String> sensitiveValues = new LinkedHashSet<>();
        for (ContextItem item : values) {
            for (ValueRule rule : VALUE_RULES) {
                Matcher matcher = rule.pattern().matcher(item.content());
                while (matcher.find()) {
                    String value = matcher.group(rule.valueGroup()).trim();
                    if (!value.isEmpty()) {
                        sensitiveValues.add(value);
                    }
                }
            }
        }
        return values.stream()
                .map(item -> item.withContent(maskKnownValues(
                        mask(item.content()), sensitiveValues)))
                .toList();
    }

    public ContextItem mask(ContextItem item) {
        return item.withContent(mask(item.content()));
    }

    public String mask(String value) {
        String masked = value;
        for (Rule rule : RULES) {
            masked = rule.pattern().matcher(masked).replaceAll(rule.replacement());
        }
        return masked;
    }

    private static Rule rule(String expression, String replacement) {
        return new Rule(Pattern.compile(expression), replacement);
    }

    private static ValueRule valueRule(String expression, int valueGroup) {
        return new ValueRule(Pattern.compile(expression), valueGroup);
    }

    private String maskKnownValues(String value, Set<String> sensitiveValues) {
        String masked = value;
        for (String sensitiveValue : sensitiveValues) {
            masked = masked.replace(sensitiveValue, REDACTED);
        }
        return masked;
    }

    private record Rule(Pattern pattern, String replacement) {
    }

    private record ValueRule(Pattern pattern, int valueGroup) {
    }
}
