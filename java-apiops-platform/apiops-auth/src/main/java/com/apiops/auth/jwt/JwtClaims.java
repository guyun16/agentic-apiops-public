package com.apiops.auth.jwt;

import java.time.Instant;

/** Claims exposed by a validated access token. */
public record JwtClaims(
        long userId,
        String username,
        Instant issuedAt,
        Instant expiresAt
) {
}
