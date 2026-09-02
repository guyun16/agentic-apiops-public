package com.apiops.demo.order.openapi;

import io.swagger.v3.oas.models.Components;
import io.swagger.v3.oas.models.OpenAPI;
import io.swagger.v3.oas.models.info.Info;
import io.swagger.v3.oas.models.security.SecurityScheme;
import io.swagger.v3.oas.models.tags.Tag;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

import java.util.List;

/** OpenAPI baseline shared by the machine contract and Knife4j UI. */
@Configuration(proxyBeanMethods = false)
public class OpenApiConfiguration {

    @Bean
    public OpenAPI demoOrderOpenAPI() {
        return new OpenAPI()
                .info(new Info()
                        .title("Agentic APIOps Demo Order Service API")
                        .version("0.1.0"))
                .tags(List.of(
                        new Tag().name("Orders").description("Order lifecycle operations."),
                        new Tag().name("Products").description("Product catalog operations."),
                        new Tag().name("Inventory").description("Inventory operations."),
                        new Tag().name("Payments").description("Payment callback operations."),
                        new Tag().name("Coupons").description("Coupon operations."),
                        new Tag().name("Users").description("User operations."),
                        new Tag().name("Faults").description("Local/test fault-injection operations.")))
                .components(new Components()
                        .addSecuritySchemes("bearerAuth", new SecurityScheme()
                                .type(SecurityScheme.Type.HTTP)
                                .scheme("bearer")
                                .bearerFormat("JWT")));
    }
}
