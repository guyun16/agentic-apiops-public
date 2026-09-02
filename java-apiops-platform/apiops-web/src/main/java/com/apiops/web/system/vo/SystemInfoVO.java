package com.apiops.web.system.vo;

import java.time.Instant;

public record SystemInfoVO(
        String serviceName,
        String version,
        String status,
        Instant generatedAt
) {
}
