package com.apiops.auth.jwt;

import com.apiops.auth.config.JwtProperties;
import com.apiops.auth.security.ApiOpsPrincipal;
import com.nimbusds.jose.JOSEException;
import com.nimbusds.jose.crypto.MACVerifier;
import com.nimbusds.jwt.SignedJWT;
import org.springframework.security.oauth2.core.DelegatingOAuth2TokenValidator;
import org.springframework.security.oauth2.core.OAuth2Error;
import org.springframework.security.oauth2.core.OAuth2TokenValidator;
import org.springframework.security.oauth2.jose.jws.MacAlgorithm;
import org.springframework.security.oauth2.jwt.Jwt;
import org.springframework.security.oauth2.jwt.JwtDecoder;
import org.springframework.security.oauth2.jwt.JwtEncoder;
import org.springframework.security.oauth2.jwt.JwtEncoderParameters;
import org.springframework.security.oauth2.jwt.JwtException;
import org.springframework.security.oauth2.jwt.JwtClaimsSet;
import org.springframework.security.oauth2.jwt.JwsHeader;
import org.springframework.security.oauth2.jwt.JwtIssuerValidator;
import org.springframework.security.oauth2.jwt.JwtTimestampValidator;
import org.springframework.security.oauth2.jwt.JwtValidationException;
import org.springframework.security.oauth2.jwt.NimbusJwtDecoder;
import org.springframework.security.oauth2.jwt.NimbusJwtEncoder;
import org.springframework.security.oauth2.core.OAuth2TokenValidatorResult;
import com.nimbusds.jose.jwk.source.ImmutableSecret;

import javax.crypto.SecretKey;
import javax.crypto.spec.SecretKeySpec;
import java.text.ParseException;
import java.time.Clock;
import java.time.Duration;
import java.time.Instant;
import java.time.temporal.ChronoUnit;
import java.util.Base64;
import java.util.Objects;

/** Issues and validates HS256 access tokens without coupling to HTTP concerns. */
public final class JwtTokenService {

    private static final String USERNAME_CLAIM = "username";
    private static final String INVALID_ISSUER_ERROR = "apiops.invalid_issuer";
    private static final String EXPIRED_ERROR = "apiops.expired";
    private static final String INVALID_CLAIMS_ERROR = "apiops.invalid_claims";

    private final JwtProperties properties;
    private final Clock clock;
    private final SecretKey secretKey;
    private final JwtEncoder encoder;
    private final JwtDecoder decoder;

    public JwtTokenService(JwtProperties properties, Clock clock) {
        this.properties = Objects.requireNonNull(properties, "properties must not be null");
        this.clock = Objects.requireNonNull(clock, "clock must not be null");
        this.secretKey = new SecretKeySpec(
                Base64.getDecoder().decode(properties.getSecret()),
                "HmacSHA256"
        );
        this.encoder = new NimbusJwtEncoder(new ImmutableSecret<>(secretKey));
        NimbusJwtDecoder nimbusDecoder = NimbusJwtDecoder.withSecretKey(secretKey)
                .macAlgorithm(MacAlgorithm.HS256)
                .build();
        nimbusDecoder.setJwtValidator(new DelegatingOAuth2TokenValidator<>(
                classifiedIssuerValidator(),
                classifiedTimestampValidator(),
                issuedAtValidator()
        ));
        this.decoder = nimbusDecoder;
    }

    public String generateAccessToken(ApiOpsPrincipal principal) {
        return issueAccessToken(principal).accessToken();
    }

    /**
     * Issues an access token and returns the exact second-precision expiration
     * instant encoded in its JWT exp claim.
     */
    public IssuedAccessToken issueAccessToken(ApiOpsPrincipal principal) {
        Objects.requireNonNull(principal, "principal must not be null");
        if (principal.getUserId() == null || principal.getUserId() <= 0
                || principal.getUsername() == null || principal.getUsername().isBlank()) {
            throw invalidClaims();
        }

        Instant issuedAt = clock.instant().truncatedTo(ChronoUnit.SECONDS);
        Instant expiresAt = issuedAt.plus(properties.getAccessTokenTtl())
                .truncatedTo(ChronoUnit.SECONDS);
        if (!expiresAt.isAfter(issuedAt)) {
            throw invalidClaims();
        }
        JwtClaimsSet claims = JwtClaimsSet.builder()
                .issuer(properties.getIssuer())
                .subject(String.valueOf(principal.getUserId()))
                .claim(USERNAME_CLAIM, principal.getUsername())
                .issuedAt(issuedAt)
                .expiresAt(expiresAt)
                .build();
        String accessToken = encoder.encode(
                JwtEncoderParameters.from(
                        JwsHeader.with(MacAlgorithm.HS256).build(),
                        claims
                )
        ).getTokenValue();
        return new IssuedAccessToken(accessToken, expiresAt);
    }

    public JwtClaims parseAndValidate(String token) {
        SignedJWT parsed = parseFormat(token);
        if (!MacAlgorithm.HS256.getName().equals(parsed.getHeader().getAlgorithm().getName())) {
            throw invalidClaims();
        }

        Jwt jwt;
        try {
            jwt = decoder.decode(token);
        } catch (JwtValidationException exception) {
            throw validationFailure(exception);
        } catch (JwtException | IllegalArgumentException exception) {
            if (hasValidSignature(parsed)) {
                throw invalidClaims();
            }
            throw invalidSignature();
        }

        return validateClaims(jwt);
    }

    private JwtClaims validateClaims(Jwt jwt) {
        Instant issuedAt;
        Instant expiresAt;
        try {
            issuedAt = jwt.getIssuedAt();
            expiresAt = jwt.getExpiresAt();
        } catch (RuntimeException exception) {
            throw invalidClaims();
        }
        if (issuedAt == null || expiresAt == null) {
            throw invalidClaims();
        }
        if (!expiresAt.isAfter(issuedAt)) {
            throw invalidClaims();
        }

        Object subjectClaim = jwt.getClaims().get("sub");
        if (!(subjectClaim instanceof String subject) || subject.isBlank()) {
            throw invalidClaims();
        }
        long userId;
        try {
            userId = Long.parseLong(subject);
        } catch (NumberFormatException exception) {
            throw invalidClaims();
        }
        if (userId <= 0) {
            throw invalidClaims();
        }

        Object usernameClaim = jwt.getClaims().get(USERNAME_CLAIM);
        if (!(usernameClaim instanceof String username) || username.isBlank()) {
            throw invalidClaims();
        }
        return new JwtClaims(userId, username, issuedAt, expiresAt);
    }

    private OAuth2TokenValidator<Jwt> classifiedIssuerValidator() {
        JwtIssuerValidator delegate = new JwtIssuerValidator(properties.getIssuer());
        return jwt -> {
            Object issuer = jwt.getClaims().get("iss");
            if (!(issuer instanceof String value) || value.isBlank()) {
                return failureResult(INVALID_CLAIMS_ERROR);
            }
            return classify(delegate.validate(jwt), INVALID_ISSUER_ERROR);
        };
    }

    private OAuth2TokenValidator<Jwt> classifiedTimestampValidator() {
        JwtTimestampValidator delegate = new JwtTimestampValidator(Duration.ZERO);
        delegate.setClock(clock);
        return jwt -> {
            OAuth2TokenValidatorResult result = delegate.validate(jwt);
            if (!result.hasErrors()) {
                return result;
            }
            Instant expiresAt;
            try {
                expiresAt = jwt.getExpiresAt();
            } catch (RuntimeException exception) {
                return failureResult(INVALID_CLAIMS_ERROR);
            }
            return expiresAt != null && !expiresAt.isAfter(clock.instant())
                    ? failureResult(EXPIRED_ERROR)
                    : failureResult(INVALID_CLAIMS_ERROR);
        };
    }

    private OAuth2TokenValidator<Jwt> issuedAtValidator() {
        return jwt -> {
            Instant issuedAt;
            try {
                issuedAt = jwt.getIssuedAt();
            } catch (RuntimeException exception) {
                return failureResult(INVALID_CLAIMS_ERROR);
            }
            return issuedAt != null && !issuedAt.isAfter(clock.instant())
                    ? OAuth2TokenValidatorResult.success()
                    : failureResult(INVALID_CLAIMS_ERROR);
        };
    }

    private static OAuth2TokenValidatorResult classify(
            OAuth2TokenValidatorResult result,
            String errorCode
    ) {
        return result.hasErrors() ? failureResult(errorCode) : result;
    }

    private static OAuth2TokenValidatorResult failureResult(String errorCode) {
        return OAuth2TokenValidatorResult.failure(new OAuth2Error(errorCode));
    }

    private JwtTokenValidationException validationFailure(JwtValidationException exception) {
        for (OAuth2Error error : exception.getErrors()) {
            switch (error.getErrorCode()) {
                case INVALID_ISSUER_ERROR -> throw invalidIssuer();
                case EXPIRED_ERROR -> throw expired();
                case INVALID_CLAIMS_ERROR -> throw invalidClaims();
                default -> {
                    // Continue so a later classified error can provide a stable reason.
                }
            }
        }
        return invalidClaims();
    }

    private SignedJWT parseFormat(String token) {
        if (token == null || token.isBlank()) {
            throw malformed();
        }
        try {
            return SignedJWT.parse(token);
        } catch (ParseException exception) {
            throw malformed();
        }
    }

    private boolean hasValidSignature(SignedJWT token) {
        try {
            return token.verify(new MACVerifier(secretKey.getEncoded()));
        } catch (JOSEException exception) {
            return false;
        }
    }

    private static JwtTokenValidationException malformed() {
        return failure(FailureReason.MALFORMED, "malformed JWT");
    }

    private static JwtTokenValidationException invalidSignature() {
        return failure(FailureReason.INVALID_SIGNATURE, "invalid JWT signature");
    }

    private static JwtTokenValidationException invalidIssuer() {
        return failure(FailureReason.INVALID_ISSUER, "invalid JWT issuer");
    }

    private static JwtTokenValidationException expired() {
        return failure(FailureReason.EXPIRED, "JWT has expired");
    }

    private static JwtTokenValidationException invalidClaims() {
        return failure(FailureReason.INVALID_CLAIMS, "invalid JWT claims");
    }

    private static JwtTokenValidationException failure(
            FailureReason reason,
            String message
    ) {
        return new JwtTokenValidationException(reason, message);
    }

    public enum FailureReason {
        MALFORMED,
        INVALID_SIGNATURE,
        INVALID_ISSUER,
        EXPIRED,
        INVALID_CLAIMS
    }

    /** Internal validation failure classification kept independent from HTTP 401 handling. */
    public static final class JwtTokenValidationException extends RuntimeException {

        private final FailureReason reason;

        private JwtTokenValidationException(FailureReason reason, String message) {
            super(message);
            this.reason = reason;
        }

        public FailureReason getReason() {
            return reason;
        }
    }
}
