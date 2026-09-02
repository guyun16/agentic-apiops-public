package com.apiops.agent.prompt;

import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.util.Set;

public final class PromptTemplateService {

    private static final Set<String> NAMES = Set.of("generate-testcase", "diagnosis");
    private static final Set<String> VERSIONS = Set.of("v1");

    public PromptDefinition load(String name, String version) {
        if (!NAMES.contains(name) || !VERSIONS.contains(version)) {
            throw new IllegalArgumentException("Unsupported prompt: " + name + "/" + version);
        }
        String root = "/prompts/" + name + "/" + version + "/";
        return new PromptDefinition(name, version,
                read(root + "system.txt"), read(root + "user.txt"));
    }

    private String read(String path) {
        try (InputStream input = PromptTemplateService.class.getResourceAsStream(path)) {
            if (input == null) {
                throw new IllegalStateException("Prompt resource not found: " + path);
            }
            return new String(input.readAllBytes(), StandardCharsets.UTF_8).strip();
        } catch (IOException exception) {
            throw new IllegalStateException("Unable to read prompt resource: " + path);
        }
    }
}
