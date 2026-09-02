package com.apiops.auth.security;

import com.apiops.auth.config.ApiOpsSecurityConfiguration;
import org.junit.jupiter.api.Test;
import org.springframework.security.crypto.password.PasswordEncoder;

import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

class PasswordEncoderTest {

    private final PasswordEncoder passwordEncoder =
            new ApiOpsSecurityConfiguration().passwordEncoder();

    @Test
    void shouldMatchCorrectPassword() {
        String encoded = passwordEncoder.encode("correct-password");

        assertTrue(passwordEncoder.matches("correct-password", encoded));
    }

    @Test
    void shouldRejectWrongPassword() {
        String encoded = passwordEncoder.encode("correct-password");

        assertFalse(passwordEncoder.matches("wrong-password", encoded));
    }

    @Test
    void shouldNotStoreRawPassword() {
        String rawPassword = "correct-password";

        assertNotEquals(rawPassword, passwordEncoder.encode(rawPassword));
    }

    @Test
    void shouldSaltEachEncoding() {
        String rawPassword = "correct-password";
        String firstEncoded = passwordEncoder.encode(rawPassword);
        String secondEncoded = passwordEncoder.encode(rawPassword);

        assertNotEquals(firstEncoded, secondEncoded);
        assertTrue(passwordEncoder.matches(rawPassword, firstEncoded));
        assertTrue(passwordEncoder.matches(rawPassword, secondEncoded));
    }
}
