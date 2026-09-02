package com.apiops.rag.context;

import org.springframework.boot.context.properties.ConfigurationProperties;

@ConfigurationProperties(prefix = "apiops.rag.context")
public class ContextPackProperties {

    private int maxTotalChars = 12_000;
    private int maxRagItemChars = 2_000;

    public int getMaxTotalChars() {
        return maxTotalChars;
    }

    public void setMaxTotalChars(int maxTotalChars) {
        if (maxTotalChars <= 0) {
            throw new IllegalArgumentException("maxTotalChars must be positive");
        }
        this.maxTotalChars = maxTotalChars;
    }

    public int getMaxRagItemChars() {
        return maxRagItemChars;
    }

    public void setMaxRagItemChars(int maxRagItemChars) {
        if (maxRagItemChars <= 0) {
            throw new IllegalArgumentException("maxRagItemChars must be positive");
        }
        this.maxRagItemChars = maxRagItemChars;
    }
}
