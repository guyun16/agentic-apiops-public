package com.apiops.web.config;

import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

import java.time.Clock;

@Configuration(proxyBeanMethods = false)
public class WebSupportConfiguration {

    @Bean
    public Clock clock() {
        return Clock.systemUTC();
    }
}
