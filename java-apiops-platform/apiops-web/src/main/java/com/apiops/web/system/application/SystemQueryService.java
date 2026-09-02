package com.apiops.web.system.application;

import com.apiops.web.config.ApiOpsProperties;
import com.apiops.web.system.domain.SystemInfo;
import org.springframework.stereotype.Service;

import java.time.Clock;

@Service
public class SystemQueryService {

    private final ApiOpsProperties properties;
    private final Clock clock;

    public SystemQueryService(
            ApiOpsProperties properties,
            Clock clock
    ) {
        this.properties = properties;
        this.clock = clock;
    }

    public SystemInfo query() {
        return new SystemInfo(
                properties.application().name(),
                properties.application().version(),
                "UP",
                clock.instant()
        );
    }
}
