package com.apiops.demo.order.fault;

import jakarta.validation.constraints.Max;
import jakarta.validation.constraints.Min;
import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.validation.annotation.Validated;

@Validated
@ConfigurationProperties(prefix = "apiops.fault.slow-sql")
public class FaultProperties {

    /** Default delay in milliseconds when the caller omits delayMs. */
    @Min(100)
    @Max(2000)
    private int defaultDelayMs = 500;

    public int getDefaultDelayMs() {
        return defaultDelayMs;
    }

    public void setDefaultDelayMs(int defaultDelayMs) {
        this.defaultDelayMs = defaultDelayMs;
    }
}
