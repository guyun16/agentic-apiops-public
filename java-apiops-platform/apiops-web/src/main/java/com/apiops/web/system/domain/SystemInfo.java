package com.apiops.web.system.domain;

import java.time.Instant;

public record SystemInfo(
        String serviceName,
        String version,
        String status,
        Instant generatedAt
) {
}
