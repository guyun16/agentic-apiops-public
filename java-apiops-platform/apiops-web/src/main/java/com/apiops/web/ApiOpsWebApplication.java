package com.apiops.web;

import com.apiops.auth.config.ApiOpsSecurityConfiguration;
import com.apiops.agent.model.springai.AgentModelConfiguration;
import com.apiops.openapi.config.OpenApiImportConfiguration;
import com.apiops.rag.config.RagConfiguration;
import com.apiops.report.config.TestReportConfiguration;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.boot.context.properties.ConfigurationPropertiesScan;
import org.springframework.context.annotation.Import;

@SpringBootApplication
@ConfigurationPropertiesScan
@Import({
        ApiOpsSecurityConfiguration.class,
        AgentModelConfiguration.class,
        OpenApiImportConfiguration.class,
        TestReportConfiguration.class,
        RagConfiguration.class
})
public class ApiOpsWebApplication {

    public static void main(String[] args) {

        SpringApplication.run(ApiOpsWebApplication.class, args);
    }
}
