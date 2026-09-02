package com.apiops.agent.prompt;

import com.apiops.agent.model.AgentModelRequest;

import java.util.Map;
import java.util.Objects;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

public record PromptDefinition(
        String name,
        String version,
        String systemTemplate,
        String userTemplate
) {
    private static final Pattern VARIABLE = Pattern.compile(
            "\\{\\{([A-Za-z0-9_-]+)}}");

    public PromptDefinition {
        name = requireText(name, "name");
        version = requireText(version, "version");
        systemTemplate = requireText(systemTemplate, "systemTemplate");
        userTemplate = requireText(userTemplate, "userTemplate");
    }

    public AgentModelRequest render(Map<String, String> variables, String context) {
        Objects.requireNonNull(variables, "variables");
        Matcher matcher = VARIABLE.matcher(userTemplate);
        StringBuilder rendered = new StringBuilder();
        while (matcher.find()) {
            String value = variables.get(matcher.group(1));
            if (value == null) {
                throw new IllegalArgumentException(
                        "Prompt variable is missing: " + matcher.group(1));
            }
            matcher.appendReplacement(rendered, Matcher.quoteReplacement(value));
        }
        matcher.appendTail(rendered);
        return new AgentModelRequest(name, version, systemTemplate, rendered.toString(),
                Objects.requireNonNull(context, "context"));
    }

    private static String requireText(String value, String name) {
        Objects.requireNonNull(value, name + " must not be null");
        if (value.isBlank()) {
            throw new IllegalArgumentException(name + " must not be blank");
        }
        return value;
    }
}
