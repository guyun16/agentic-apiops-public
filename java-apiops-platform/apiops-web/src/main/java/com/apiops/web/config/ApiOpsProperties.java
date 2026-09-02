package com.apiops.web.config;

import org.springframework.boot.context.properties.ConfigurationProperties;

@ConfigurationProperties(prefix = "apiops")
public record ApiOpsProperties(
        Application application,
        Tracing tracing
) {

    public record Application(
            String name,
            String version
    ) {
    }

    public record Tracing(
            String headerName
    ) {
    }
}
