package com.apiops.auth.config;

import com.apiops.auth.jwt.JwtTokenService;
import org.springframework.boot.autoconfigure.condition.ConditionalOnMissingBean;
import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

import java.time.Clock;

/** Explicit JWT properties and service assembly for importing applications. */
@Configuration(proxyBeanMethods = false)
@EnableConfigurationProperties(JwtProperties.class)
public class JwtConfiguration {

    @Bean
    @ConditionalOnMissingBean(Clock.class)
    public Clock jwtClock() {
        return Clock.systemUTC();
    }

    @Bean
    public JwtTokenService jwtTokenService(JwtProperties properties, Clock clock) {
        return new JwtTokenService(properties, clock);
    }
}
