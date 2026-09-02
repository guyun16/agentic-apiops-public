package com.apiops.web.actuator;

import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.test.context.ActiveProfiles;
import org.springframework.test.web.servlet.MockMvc;
import io.micrometer.core.instrument.Counter;
import io.micrometer.core.instrument.MeterRegistry;
import io.micrometer.core.instrument.Timer;
import com.apiops.runner.application.RunnerMetrics;
import com.apiops.tool.gateway.Metrics;
import java.time.Duration;

import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.security.test.web.servlet.request.SecurityMockMvcRequestPostProcessors.user;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.content;

@SpringBootTest
@AutoConfigureMockMvc
@ActiveProfiles("test")
class ActuatorHealthTest {

    @Autowired
    private MockMvc mockMvc;

    @Autowired
    private MeterRegistry meterRegistry;

    @Test
    void shouldExposeHealthWithoutComponentDetails() throws Exception {
        mockMvc.perform(get("/actuator/health"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.status").value("UP"))
                .andExpect(jsonPath("$.components").doesNotExist());
    }

    @Test
    void shouldNotExposeInfo() throws Exception {
        mockMvc.perform(get("/actuator/info").with(user("actuator-reader")))
                .andExpect(status().isNotFound());
    }

    @Test
    void shouldExposePrometheusAndCustomMeters() throws Exception {
        Timer.builder(RunnerMetrics.EXECUTION_TIMER)
                .tags("status", "SUCCESS", "failureType", "NONE")
                .register(meterRegistry)
                .record(Duration.ofNanos(1));
        Timer.builder(Metrics.TOOL_CALL_TIMER)
                .tags("tool", "rag.search", "status", "SUCCESS")
                .register(meterRegistry)
                .record(Duration.ofNanos(1));
        Counter.builder(Metrics.SAFETY_VIOLATION_COUNTER)
                .tags("tool", "sql.read", "violationCode", "RESOURCE_GUARD_REJECTED")
                .register(meterRegistry)
                .increment();

        mockMvc.perform(get("/actuator/prometheus"))
                .andExpect(status().isOk())
                .andExpect(content().string(org.hamcrest.Matchers.containsString(
                        "apiops_runner_executions")))
                .andExpect(content().string(org.hamcrest.Matchers.containsString(
                        "apiops_tool_calls")))
                .andExpect(content().string(org.hamcrest.Matchers.containsString(
                        "apiops_tool_safety_violations")));
    }

    @Test
    void shouldNotExposeEnvironmentEndpoint() throws Exception {
        mockMvc.perform(get("/actuator/env").with(user("actuator-reader")))
                .andExpect(status().isNotFound());
    }

    @Test
    void shouldNotExposeConfigurationPropertiesEndpoint() throws Exception {
        mockMvc.perform(get("/actuator/configprops").with(user("actuator-reader")))
                .andExpect(status().isNotFound());
    }

    @Test
    void shouldReturnNotFoundForUnknownPath() throws Exception {
        mockMvc.perform(get("/path-that-does-not-exist").with(user("test-user")))
                .andExpect(status().isNotFound());
    }
}
