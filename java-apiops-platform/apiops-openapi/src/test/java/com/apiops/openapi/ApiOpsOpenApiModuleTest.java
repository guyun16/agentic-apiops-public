package com.apiops.openapi;

import com.apiops.common.result.Result;
import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

class ApiOpsOpenApiModuleTest {

    @Test
    void shouldParticipateInMavenTestLifecycleWithCommonDependency() {
        Result<String> result = Result.success("apiops-openapi");

        assertTrue(result.isSuccess());
        assertEquals("apiops-openapi", result.getData());
    }
}
