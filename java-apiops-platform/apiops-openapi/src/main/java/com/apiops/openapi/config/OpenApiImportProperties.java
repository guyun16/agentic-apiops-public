package com.apiops.openapi.config;

import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.util.unit.DataSize;

@ConfigurationProperties(prefix = "apiops.openapi.import")
public class OpenApiImportProperties {

    private DataSize maxFileSize = DataSize.ofMegabytes(1);

    public DataSize getMaxFileSize() {
        return maxFileSize;
    }

    public void setMaxFileSize(DataSize maxFileSize) {
        this.maxFileSize = maxFileSize;
    }
}
