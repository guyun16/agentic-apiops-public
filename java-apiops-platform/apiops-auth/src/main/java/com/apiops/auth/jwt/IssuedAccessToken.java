package com.apiops.auth.jwt;

import java.time.Instant;
import java.util.Objects;

/** The access token and the expiration instant encoded into its JWT claims. */
public record IssuedAccessToken(String accessToken, Instant expiresAt) {

    public IssuedAccessToken {
        if (accessToken == null || accessToken.isBlank()) {
            throw new IllegalArgumentException("accessToken must not be blank");
        }
        Objects.requireNonNull(expiresAt, "expiresAt must not be null");
    }
}
