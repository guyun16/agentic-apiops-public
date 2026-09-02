package com.apiops.auth.jwt;

import com.apiops.auth.config.JwtProperties;
import com.apiops.auth.security.ApiOpsPrincipal;
import com.nimbusds.jose.JOSEException;
import com.nimbusds.jose.JWSAlgorithm;
import com.nimbusds.jose.JWSHeader;
import com.nimbusds.jose.JWSObject;
import com.nimbusds.jose.Payload;
import com.nimbusds.jose.crypto.MACSigner;
import com.nimbusds.jose.jwk.source.ImmutableSecret;
import org.junit.jupiter.api.Test;
import org.springframework.security.oauth2.jose.jws.MacAlgorithm;
import org.springframework.security.oauth2.jwt.JwsHeader;
import org.springframework.security.oauth2.jwt.JwtClaimsSet;
import org.springframework.security.oauth2.jwt.JwtEncoder;
import org.springframework.security.oauth2.jwt.JwtEncoderParameters;
import org.springframework.security.oauth2.jwt.NimbusJwtEncoder;

import javax.crypto.spec.SecretKeySpec;
import java.nio.charset.StandardCharsets;
import java.time.Clock;
import java.time.Duration;
import java.time.Instant;
import java.time.ZoneOffset;
import java.util.Base64;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertThrows;

class JwtTokenServiceTest {

    private static final String ISSUER = "https://auth.apiops.test";
    private static final String SECRET = base64Secret(
            "primary-jwt-secret-with-at-least-32-bytes"
    );
    private static final String OTHER_SECRET = base64Secret(
            "another-jwt-secret-with-at-least-32-bytes"
    );
    private static final Duration TTL = Duration.ofMinutes(15);
    private static final Instant ISSUED_AT = Instant.parse("2025-01-01T00:00:00Z");
    private static final Instant EXPIRES_AT = ISSUED_AT.plus(TTL);
    private static final Instant FAR_FUTURE_ISSUED_AT = Instant.parse("2035-01-01T00:00:00Z");
    private static final Instant FAR_FUTURE_EXPIRES_AT = FAR_FUTURE_ISSUED_AT.plus(TTL);
    private static final Clock FIXED_CLOCK = Clock.fixed(ISSUED_AT, ZoneOffset.UTC);

    @Test
    void shouldGenerateAndParseAccessTokenWithContractClaims() {
        JwtTokenService service = service(SECRET, FIXED_CLOCK);

        JwtClaims claims = service.parseAndValidate(service.generateAccessToken(principal()));

        assertEquals(42L, claims.userId());
        assertEquals("alice", claims.username());
        assertEquals(ISSUED_AT, claims.issuedAt());
        assertEquals(ISSUED_AT.plus(TTL), claims.expiresAt());
    }

    @Test
    void shouldRejectTokenWithTamperedPayload() {
        JwtTokenService service = service(SECRET, FIXED_CLOCK);
        String token = service.generateAccessToken(principal());
        String[] segments = token.split("\\.", -1);
        String changedPayload = Base64.getUrlEncoder().withoutPadding().encodeToString(
                "{\"iss\":\"https://auth.apiops.test\",\"sub\":\"99\",\"username\":\"mallory\",\"iat\":1735689600,\"exp\":1735690500}"
                        .getBytes(StandardCharsets.UTF_8)
        );
        assertFalse(segments[1].equals(changedPayload));
        String tamperedToken = segments[0] + "." + changedPayload + "." + segments[2];

        JwtTokenService.JwtTokenValidationException failure = assertThrows(
                JwtTokenService.JwtTokenValidationException.class,
                () -> service.parseAndValidate(tamperedToken)
        );

        assertEquals(JwtTokenService.FailureReason.INVALID_SIGNATURE, failure.getReason());
    }

    @Test
    void shouldRejectTokenSignedWithAnotherSecret() {
        JwtTokenService issuingService = service(SECRET, FIXED_CLOCK);
        JwtTokenService validatingService = service(OTHER_SECRET, FIXED_CLOCK);

        JwtTokenService.JwtTokenValidationException failure = assertThrows(
                JwtTokenService.JwtTokenValidationException.class,
                () -> validatingService.parseAndValidate(
                        issuingService.generateAccessToken(principal())
                )
        );

        assertEquals(JwtTokenService.FailureReason.INVALID_SIGNATURE, failure.getReason());
    }

    @Test
    void shouldRejectExpiredToken() {
        Clock issuingClock = Clock.fixed(FAR_FUTURE_ISSUED_AT, ZoneOffset.UTC);
        JwtTokenService issuingService = service(SECRET, issuingClock);
        JwtTokenService validatingService = service(
                SECRET,
                Clock.fixed(FAR_FUTURE_EXPIRES_AT.plusSeconds(1), ZoneOffset.UTC)
        );

        JwtTokenService.JwtTokenValidationException failure = assertThrows(
                JwtTokenService.JwtTokenValidationException.class,
                () -> validatingService.parseAndValidate(
                        issuingService.generateAccessToken(principal())
                )
        );

        assertEquals(JwtTokenService.FailureReason.EXPIRED, failure.getReason());
    }

    @Test
    void shouldUseInjectedClockForFarFutureTokenImmediately() {
        Clock farFutureClock = Clock.fixed(FAR_FUTURE_ISSUED_AT, ZoneOffset.UTC);
        JwtTokenService service = service(SECRET, farFutureClock);

        JwtClaims claims = service.parseAndValidate(service.generateAccessToken(principal()));

        assertEquals(FAR_FUTURE_ISSUED_AT, claims.issuedAt());
        assertEquals(FAR_FUTURE_EXPIRES_AT, claims.expiresAt());
    }

    @Test
    void shouldUseInjectedClockWhenFarFutureTokenExpires() {
        Clock issuingClock = Clock.fixed(FAR_FUTURE_ISSUED_AT, ZoneOffset.UTC);
        Clock afterExpirationClock = Clock.fixed(
                FAR_FUTURE_EXPIRES_AT.plusSeconds(1),
                ZoneOffset.UTC
        );
        JwtTokenService issuingService = service(SECRET, issuingClock);
        JwtTokenService validatingService = service(SECRET, afterExpirationClock);

        JwtTokenService.JwtTokenValidationException failure = assertThrows(
                JwtTokenService.JwtTokenValidationException.class,
                () -> validatingService.parseAndValidate(
                        issuingService.generateAccessToken(principal())
                )
        );

        assertEquals(JwtTokenService.FailureReason.EXPIRED, failure.getReason());
    }

    @Test
    void shouldRejectTokenWithWrongIssuer() {
        JwtTokenService service = service(SECRET, FIXED_CLOCK);
        String token = signedToken(SECRET, claimsWith("iss", "https://other.apiops.test"));

        JwtTokenService.JwtTokenValidationException failure = assertThrows(
                JwtTokenService.JwtTokenValidationException.class,
                () -> service.parseAndValidate(token)
        );

        assertEquals(JwtTokenService.FailureReason.INVALID_ISSUER, failure.getReason());
    }

    @Test
    void shouldRejectMalformedToken() {
        JwtTokenService.JwtTokenValidationException failure = assertThrows(
                JwtTokenService.JwtTokenValidationException.class,
                () -> service(SECRET, FIXED_CLOCK).parseAndValidate("not-a-jwt")
        );

        assertEquals(JwtTokenService.FailureReason.MALFORMED, failure.getReason());
    }

    @Test
    void shouldRejectTokenMissingRequiredClaims() {
        Map<String, Object> claims = validClaims();
        for (String requiredClaim : List.of("iss", "sub", "username", "iat", "exp")) {
            Map<String, Object> missingClaim = new LinkedHashMap<>(claims);
            missingClaim.remove(requiredClaim);

            JwtTokenService.JwtTokenValidationException failure = assertThrows(
                    JwtTokenService.JwtTokenValidationException.class,
                    () -> service(SECRET, FIXED_CLOCK)
                            .parseAndValidate(signedToken(SECRET, missingClaim))
            );

            assertEquals(JwtTokenService.FailureReason.INVALID_CLAIMS, failure.getReason());
        }
    }

    @Test
    void shouldRejectTokenWithIllegalRequiredClaims() {
        Map<String, Object> futureIssuedAt = validClaims();
        futureIssuedAt.put("iat", ISSUED_AT.plusSeconds(1));

        for (String subject : List.of("not-a-positive-user-id", "0", "-1")) {
            Map<String, Object> illegalSubject = validClaims();
            illegalSubject.put("sub", subject);
            assertInvalidClaims(illegalSubject);
        }
        for (String username : List.of("", " ")) {
            Map<String, Object> illegalUsername = validClaims();
            illegalUsername.put("username", username);
            assertInvalidClaims(illegalUsername);
        }
        assertInvalidToken(signedTokenWithNullUsername(SECRET));
        for (Map<String, Object> claims : List.of(futureIssuedAt)) {
            assertInvalidClaims(claims);
        }
    }

    private void assertInvalidClaims(Map<String, Object> claims) {
        assertInvalidToken(signedToken(SECRET, claims));
    }

    private void assertInvalidToken(String token) {
        JwtTokenService.JwtTokenValidationException failure = assertThrows(
                JwtTokenService.JwtTokenValidationException.class,
                () -> service(SECRET, FIXED_CLOCK)
                        .parseAndValidate(token)
        );

        assertEquals(JwtTokenService.FailureReason.INVALID_CLAIMS, failure.getReason());
    }

    @Test
    void shouldRejectWeakSecretConfiguration() {
        String weakSecret = Base64.getEncoder().encodeToString(new byte[31]);

        assertThrows(
                IllegalArgumentException.class,
                () -> new JwtProperties(ISSUER, TTL, weakSecret)
        );
    }

    @Test
    void shouldRejectInvalidJwtPropertyValues() {
        assertThrows(
                IllegalArgumentException.class,
                () -> new JwtProperties(" ", TTL, SECRET)
        );
        assertThrows(
                IllegalArgumentException.class,
                () -> new JwtProperties(ISSUER, Duration.ZERO, SECRET)
        );
        assertThrows(
                IllegalArgumentException.class,
                () -> new JwtProperties(ISSUER, TTL, "not-base64")
        );
    }

    @Test
    void shouldNotExposeSecretInPropertiesText() {
        JwtProperties properties = new JwtProperties(ISSUER, TTL, SECRET);

        assertFalse(properties.toString().contains(SECRET));
    }

    private JwtTokenService service(String secret, Clock clock) {
        return new JwtTokenService(new JwtProperties(ISSUER, TTL, secret), clock);
    }

    private ApiOpsPrincipal principal() {
        return new ApiOpsPrincipal(42L, "alice", "test-password-hash", true, List.of());
    }

    private Map<String, Object> validClaims() {
        return claimsWith();
    }

    private Map<String, Object> claimsWith(String... overrides) {
        Map<String, Object> claims = new LinkedHashMap<>();
        claims.put("iss", ISSUER);
        claims.put("sub", "42");
        claims.put("username", "alice");
        claims.put("iat", ISSUED_AT);
        claims.put("exp", EXPIRES_AT);
        for (int index = 0; index < overrides.length; index += 2) {
            claims.put(overrides[index], overrides[index + 1]);
        }
        return claims;
    }

    private static String signedToken(String secret, Map<String, Object> claims) {
        JwtClaimsSet.Builder claimsBuilder = JwtClaimsSet.builder();
        claims.forEach(claimsBuilder::claim);
        JwtEncoder encoder = new NimbusJwtEncoder(
                new ImmutableSecret<>(new SecretKeySpec(
                        Base64.getDecoder().decode(secret), "HmacSHA256"
                ))
        );
        return encoder.encode(
                JwtEncoderParameters.from(
                        JwsHeader.with(MacAlgorithm.HS256).build(),
                        claimsBuilder.build()
                )
        ).getTokenValue();
    }

    private static String signedTokenWithNullUsername(String secret) {
        JWSObject jws = new JWSObject(
                new JWSHeader(JWSAlgorithm.HS256),
                new Payload(
                        "{\"iss\":\"https://auth.apiops.test\",\"sub\":\"42\",\"username\":null,\"iat\":1735689600,\"exp\":1735690500}"
                )
        );
        try {
            jws.sign(new MACSigner(Base64.getDecoder().decode(secret)));
            return jws.serialize();
        } catch (JOSEException exception) {
            throw new AssertionError("failed to create null-claim test token", exception);
        }
    }

    private static String base64Secret(String value) {
        return Base64.getEncoder().encodeToString(value.getBytes(StandardCharsets.UTF_8));
    }
}
