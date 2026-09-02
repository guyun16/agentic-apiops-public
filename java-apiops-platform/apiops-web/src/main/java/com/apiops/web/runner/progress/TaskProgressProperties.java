package com.apiops.web.runner.progress;

import org.springframework.boot.context.properties.ConfigurationProperties;
import java.time.Duration;

@ConfigurationProperties(prefix = "apiops.runner.progress")
public class TaskProgressProperties {
    private boolean enabled;
    private Duration ttl = Duration.ofHours(24);
    private Duration sseTimeout = Duration.ofMinutes(30);
    public boolean isEnabled() { return enabled; }
    public void setEnabled(boolean enabled) { this.enabled = enabled; }
    public Duration getTtl() { return ttl; }
    public void setTtl(Duration ttl) { this.ttl = ttl; }
    public Duration getSseTimeout() { return sseTimeout; }
    public void setSseTimeout(Duration sseTimeout) { this.sseTimeout = sseTimeout; }
}
