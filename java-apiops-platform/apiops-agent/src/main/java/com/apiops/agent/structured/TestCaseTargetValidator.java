package com.apiops.agent.structured;

import com.apiops.runner.dsl.TestCase;

import java.util.List;
import java.util.Objects;
import java.net.URI;

public final class TestCaseTargetValidator {

    public TestCase validate(TestCase candidate, long projectId, String apiId) {
        return validate(candidate, projectId, apiId,
                candidate.environment().baseUrl());
    }

    public void validateRequestedTarget(
            long projectId, String apiId, String trustedBaseUrl) {
        Objects.requireNonNull(apiId, "apiId");
        Objects.requireNonNull(trustedBaseUrl, "trustedBaseUrl");
        if (projectId <= 0 || apiId.isBlank() || !validHttpBaseUrl(trustedBaseUrl)) {
            throw new IllegalArgumentException("requested target must be valid");
        }
    }

    public TestCase validate(
            TestCase candidate, long projectId, String apiId,
            String trustedBaseUrl) {
        Objects.requireNonNull(candidate, "candidate");
        validateRequestedTarget(projectId, apiId, trustedBaseUrl);
        if (candidate.projectId() != projectId
                || !candidate.apiId().equals(apiId)
                || !candidate.environment().baseUrl().equals(trustedBaseUrl)) {
            throw new StructuredOutputException(
                    StructuredOutputFailureType.TARGET_MISMATCH,
                    List.of("Candidate projectId/apiId/baseUrl does not match requested target"));
        }
        return candidate;
    }

    private boolean validHttpBaseUrl(String value) {
        try {
            URI uri = URI.create(value);
            return uri.isAbsolute() && uri.getRawAuthority() != null
                    && ("http".equalsIgnoreCase(uri.getScheme())
                    || "https".equalsIgnoreCase(uri.getScheme()))
                    && uri.getRawQuery() == null && uri.getRawFragment() == null;
        } catch (IllegalArgumentException exception) {
            return false;
        }
    }
}
