package com.apiops.auth.config;

import com.apiops.auth.jwt.JwtClaims;
import com.apiops.auth.jwt.JwtTokenService;
import com.apiops.auth.security.ApiOpsPrincipal;
import org.junit.jupiter.api.Test;
import org.springframework.boot.test.context.runner.ApplicationContextRunner;

import java.nio.charset.StandardCharsets;
import java.time.Clock;
import java.time.Duration;
import java.time.Instant;
import java.time.ZoneOffset;
import java.util.Base64;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertSame;

class JwtConfigurationTest {

    private static final String ISSUER = "apiops-platform-test";
    private static final String TEST_SECRET = base64Secret(
            "configuration-test-jwt-secret-material-2026"
    );
    private static final Instant FIXED_TIME = Instant.parse("2035-01-01T00:00:00Z");
    private static final Clock FIXED_CLOCK = Clock.fixed(FIXED_TIME, ZoneOffset.UTC);

    private final ApplicationContextRunner contextRunner = new ApplicationContextRunner()
            .withUserConfiguration(JwtConfiguration.class);

    @Test
    void shouldBindPropertiesAndCreateJwtServiceBean() {
        contextRunner
                .withPropertyValues(validProperties())
                .run(context -> {
                    assertThat(context).hasNotFailed();
                    assertThat(context).hasSingleBean(JwtProperties.class);
                    assertThat(context).hasSingleBean(JwtTokenService.class);

                    JwtProperties properties = context.getBean(JwtProperties.class);
                    assertEquals(ISSUER, properties.getIssuer());
                    assertEquals(Duration.ofMinutes(15), properties.getAccessTokenTtl());
                    assertEquals(TEST_SECRET, properties.getSecret());
                });
    }

    @Test
    void shouldUseProvidedClockAndKeepOneClockBean() {
        contextRunner
                .withBean(Clock.class, () -> FIXED_CLOCK)
                .withPropertyValues(validProperties())
                .run(context -> {
                    assertThat(context).hasSingleBean(Clock.class);
                    assertSame(FIXED_CLOCK, context.getBean(Clock.class));

                    JwtTokenService service = context.getBean(JwtTokenService.class);
                    JwtClaims claims = service.parseAndValidate(
                            service.generateAccessToken(principal())
                    );
                    assertEquals(FIXED_TIME, claims.issuedAt());
                });
    }

    @Test
    void shouldCreateDefaultClockWhenNoClockBeanExists() {
        contextRunner
                .withPropertyValues(validProperties())
                .run(context -> assertThat(context).hasSingleBean(Clock.class));
    }

    @Test
    void shouldFailWhenSecretIsMissing() {
        assertStartupFailureWithoutSecret(
                "apiops.auth.jwt.issuer=" + ISSUER,
                "apiops.auth.jwt.access-token-ttl=15m"
        );
    }

    @Test
    void shouldFailWhenSecretIsBlank() {
        assertStartupFailureWithoutSecret(
                "apiops.auth.jwt.issuer=" + ISSUER,
                "apiops.auth.jwt.access-token-ttl=15m",
                "apiops.auth.jwt.secret=   "
        );
    }

    @Test
    void shouldFailWhenSecretIsNotBase64() {
        assertStartupFailureWithoutValues(
                "not-base64",
                "apiops.auth.jwt.issuer=" + ISSUER,
                "apiops.auth.jwt.access-token-ttl=15m",
                "apiops.auth.jwt.secret=not-base64"
        );
    }

    @Test
    void shouldFailWhenDecodedSecretIsTooShort() {
        String shortSecret = Base64.getEncoder().encodeToString(new byte[31]);

        assertStartupFailureWithoutValues(
                shortSecret,
                "apiops.auth.jwt.issuer=" + ISSUER,
                "apiops.auth.jwt.access-token-ttl=15m",
                "apiops.auth.jwt.secret=" + shortSecret
        );
    }

    @Test
    void shouldFailWhenIssuerIsBlank() {
        assertStartupFailureWithoutSecret(
                "apiops.auth.jwt.issuer= ",
                "apiops.auth.jwt.access-token-ttl=15m",
                "apiops.auth.jwt.secret=" + TEST_SECRET
        );
    }

    @Test
    void shouldFailWhenTtlIsZero() {
        assertStartupFailureWithoutSecret(
                "apiops.auth.jwt.issuer=" + ISSUER,
                "apiops.auth.jwt.access-token-ttl=0s",
                "apiops.auth.jwt.secret=" + TEST_SECRET
        );
    }

    @Test
    void shouldFailWhenTtlIsNegative() {
        assertStartupFailureWithoutSecret(
                "apiops.auth.jwt.issuer=" + ISSUER,
                "apiops.auth.jwt.access-token-ttl=-1s",
                "apiops.auth.jwt.secret=" + TEST_SECRET
        );
    }

    private void assertStartupFailureWithoutSecret(String... properties) {
        assertStartupFailureWithoutValues(TEST_SECRET, properties);
    }

    private void assertStartupFailureWithoutValues(
            String forbiddenValue,
            String... properties
    ) {
        contextRunner
                .withPropertyValues(properties)
                .run(context -> {
                    assertThat(context).hasFailed();
                    String failure = String.valueOf(context.getStartupFailure());
                    assertFalse(failure.contains(forbiddenValue));
                });
    }

    private String[] validProperties() {
        return new String[]{
                "apiops.auth.jwt.issuer=" + ISSUER,
                "apiops.auth.jwt.access-token-ttl=15m",
                "apiops.auth.jwt.secret=" + TEST_SECRET
        };
    }

    private ApiOpsPrincipal principal() {
        return new ApiOpsPrincipal(42L, "alice", "test-password-hash", true, List.of());
    }

    private static String base64Secret(String value) {
        return Base64.getEncoder().encodeToString(value.getBytes(StandardCharsets.UTF_8));
    }
}
