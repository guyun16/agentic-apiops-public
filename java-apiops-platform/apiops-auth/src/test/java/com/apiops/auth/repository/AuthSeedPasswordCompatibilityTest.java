package com.apiops.auth.repository;

import org.junit.jupiter.api.Test;
import org.springframework.security.crypto.bcrypt.BCryptPasswordEncoder;
import org.springframework.security.crypto.password.PasswordEncoder;

import java.io.IOException;
import java.io.InputStream;
import java.io.UncheckedIOException;
import java.nio.charset.StandardCharsets;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

import static org.junit.jupiter.api.Assertions.assertTrue;

class AuthSeedPasswordCompatibilityTest {

    private static final Pattern BCRYPT_HASH = Pattern.compile(
            "\\$2[aby]\\$\\d{2}\\$[^'\\s,]+"
    );

    @Test
    void shouldMatchTestProofPasswordAgainstEncodedSeedHash() {
        PasswordEncoder passwordEncoder = new BCryptPasswordEncoder();

        assertTrue(passwordEncoder.matches(
                demoPasswordFromProof(),
                seedHash()
        ));
    }

    private static String seedHash() {
        Matcher matcher = BCRYPT_HASH.matcher(resource("db/auth-seed.sql"));
        if (!matcher.find()) {
            throw new IllegalStateException("Missing BCrypt hash in auth seed");
        }
        return matcher.group();
    }

    private static String demoPasswordFromProof() {
        String marker = "<!-- demo-password: ";
        return resource("auth-demo-password-proof.md").lines()
                .filter(line -> line.startsWith(marker))
                .map(line -> line.substring(marker.length(), line.length() - " -->".length()))
                .findFirst()
                .orElseThrow(() -> new IllegalStateException("Missing demonstration password proof"));
    }

    private static String resource(String name) {
        try (InputStream input = AuthSeedPasswordCompatibilityTest.class
                .getClassLoader().getResourceAsStream(name)) {
            if (input == null) {
                throw new IllegalStateException("Missing test resource: " + name);
            }
            return new String(input.readAllBytes(), StandardCharsets.UTF_8);
        } catch (IOException exception) {
            throw new UncheckedIOException(exception);
        }
    }
}
