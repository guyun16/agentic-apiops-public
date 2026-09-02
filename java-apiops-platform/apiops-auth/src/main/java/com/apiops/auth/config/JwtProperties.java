package com.apiops.auth.config;

import org.springframework.boot.context.properties.ConfigurationProperties;

import java.time.Duration;
import java.util.Base64;
import java.util.Objects;

/** Immutable settings used by the JWT access-token service. */
@ConfigurationProperties(prefix = "apiops.auth.jwt")
public final class JwtProperties {

    private final String issuer;
    private final Duration accessTokenTtl;
    private final String secret;

    public JwtProperties(String issuer, Duration accessTokenTtl, String secret) {
        this.issuer = requireNonBlank(issuer, "issuer must not be blank");
        this.accessTokenTtl = Objects.requireNonNull(
                accessTokenTtl,
                "accessTokenTtl must not be null"
        );
        if (accessTokenTtl.isZero() || accessTokenTtl.isNegative()) {
            throw new IllegalArgumentException("accessTokenTtl must be greater than zero");
        }
        this.secret = requireNonBlank(secret, "secret must not be blank");
        validateSecret(this.secret);
    }

    public String getIssuer() {
        return issuer;
    }

    public Duration getAccessTokenTtl() {
        return accessTokenTtl;
    }

    public String getSecret() {
        return secret;
    }

    private static String requireNonBlank(String value, String message) {
        if (value == null || value.isBlank()) {
            throw new IllegalArgumentException(message);
        }
        return value;
    }

    private static void validateSecret(String secret) {
        final byte[] decoded;
        try {
            decoded = Base64.getDecoder().decode(secret);
        } catch (IllegalArgumentException exception) {
            throw new IllegalArgumentException(
                    "secret must be valid Base64 and decode to at least 32 bytes"
            );
        }
        if (decoded.length < 32) {
            throw new IllegalArgumentException(
                    "secret must decode to at least 32 bytes"
            );
        }
    }
}
