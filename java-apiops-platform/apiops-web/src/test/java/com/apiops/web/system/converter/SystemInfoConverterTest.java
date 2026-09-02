package com.apiops.web.system.converter;

import com.apiops.web.system.domain.SystemInfo;
import com.apiops.web.system.vo.SystemInfoVO;
import org.junit.jupiter.api.Test;

import java.time.Instant;

import static org.junit.jupiter.api.Assertions.assertEquals;

class SystemInfoConverterTest {

    @Test
    void shouldMapAllSystemInfoFieldsToVO() {
        Instant generatedAt =
                Instant.parse("2026-07-24T08:00:00Z");

        SystemInfo source = new SystemInfo(
                "Agentic APIOps Java Platform Test",
                "0.1.0-SNAPSHOT",
                "UP",
                generatedAt
        );

        SystemInfoVO result =
                new SystemInfoConverter().toVO(source);

        assertEquals(source.serviceName(), result.serviceName());
        assertEquals(source.version(), result.version());
        assertEquals(source.status(), result.status());
        assertEquals(source.generatedAt(), result.generatedAt());
    }
}
