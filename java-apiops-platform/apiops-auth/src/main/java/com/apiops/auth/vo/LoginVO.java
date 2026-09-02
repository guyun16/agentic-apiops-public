package com.apiops.auth.vo;

import java.time.Instant;

public record LoginVO(
        Long userId,
        String username,
        String tokenType,
        String accessToken,
        Instant expiresAt
) {
}
