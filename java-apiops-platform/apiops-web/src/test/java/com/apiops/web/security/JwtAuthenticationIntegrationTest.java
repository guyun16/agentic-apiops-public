package com.apiops.web.security;

import com.apiops.auth.config.JwtProperties;
import com.apiops.auth.jwt.JwtTokenService;
import com.apiops.auth.repository.AuthUserRepository;
import com.apiops.auth.security.ApiOpsPrincipal;
import com.apiops.auth.web.JwtAuthenticationFilter;
import com.apiops.auth.web.RestAccessDeniedHandler;
import com.apiops.auth.web.RestAuthenticationEntryPoint;
import com.apiops.common.result.Result;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.TestConfiguration;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.context.TestComponent;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Import;
import org.springframework.core.Ordered;
import org.springframework.core.annotation.Order;
import org.springframework.security.config.annotation.web.builders.HttpSecurity;
import org.springframework.security.config.annotation.web.configurers.AbstractHttpConfigurer;
import org.springframework.security.config.http.SessionCreationPolicy;
import org.springframework.security.core.GrantedAuthority;
import org.springframework.security.web.SecurityFilterChain;
import org.springframework.security.web.access.intercept.AuthorizationFilter;
import org.springframework.test.context.ActiveProfiles;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.context.annotation.Primary;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.nio.charset.StandardCharsets;
import java.time.Clock;
import java.time.Duration;
import java.time.Instant;
import java.time.ZoneOffset;
import java.util.Base64;
import java.util.List;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.atomic.AtomicInteger;

import static org.hamcrest.Matchers.containsString;
import static org.hamcrest.Matchers.not;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.springframework.http.MediaType.APPLICATION_JSON;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.content;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

@SpringBootTest
@AutoConfigureMockMvc
@ActiveProfiles("test")
@Import({
        JwtAuthenticationIntegrationTest.TestOnlyController.class,
        JwtAuthenticationIntegrationTest.SecurityTestConfiguration.class
})
class JwtAuthenticationIntegrationTest {

    private static final String ISSUER = "apiops-platform-test";
    private static final String SECRET = Base64.getEncoder().encodeToString(
            "test-only-jwt-secret-material-2026-08-07".getBytes(StandardCharsets.UTF_8)
    );
    private static final Duration TTL = Duration.ofMinutes(15);
    private static final String DEMO_USERNAME = "demo-user";
    private static final String ADMIN_USERNAME = "admin-user";

    @Autowired
    private MockMvc mockMvc;

    @Autowired
    private JwtTokenService jwtTokenService;

    @Autowired
    private CountingAuthUserRepository userRepository;

    @BeforeEach
    void resetUserLoadCount() {
        userRepository.resetCount();
    }

    @AfterEach
    void clearSecurityContext() {
        org.springframework.security.core.context.SecurityContextHolder.clearContext();
    }

    @Test
    void shouldAllowPublicHealthEndpointWithoutToken() throws Exception {
        mockMvc.perform(get("/actuator/health"))
                .andExpect(status().isOk());
    }

    @Test
    void shouldReturnStable401ForProtectedEndpointWithoutToken() throws Exception {
        mockMvc.perform(get("/test/security/principal"))
                .andExpect(status().isUnauthorized())
                .andExpect(content().contentTypeCompatibleWith(APPLICATION_JSON))
                .andExpect(jsonPath("$.success").value(false))
                .andExpect(jsonPath("$.code").value("A0004"))
                .andExpect(jsonPath("$.message").value("authentication required"))
                .andExpect(jsonPath("$.data").value((Object) null));
    }

    @Test
    void shouldRestorePrincipalFromRealJwtForProtectedEndpoint() throws Exception {
        mockMvc.perform(get("/test/security/principal")
                        .header("Authorization", bearerToken(DEMO_USERNAME)))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.success").value(true))
                .andExpect(jsonPath("$.data.userId").value(1))
                .andExpect(jsonPath("$.data.username").value(DEMO_USERNAME));
    }

    @Test
    void shouldReturn401ForExpiredJwt() throws Exception {
        JwtTokenService oldIssuer = new JwtTokenService(
                new JwtProperties(ISSUER, TTL, SECRET),
                Clock.fixed(Instant.parse("2020-01-01T00:00:00Z"), ZoneOffset.UTC)
        );
        String expiredToken = oldIssuer.generateAccessToken(demoPrincipal());

        mockMvc.perform(get("/test/security/principal")
                        .header("Authorization", "Bearer " + expiredToken))
                .andExpect(status().isUnauthorized())
                .andExpect(content().contentTypeCompatibleWith(APPLICATION_JSON))
                .andExpect(jsonPath("$.code").value("A0004"))
                .andExpect(jsonPath("$.message").value("authentication required"));
    }

    @Test
    void shouldReturn401ForTamperedJwt() throws Exception {
        String token = jwtTokenService.generateAccessToken(demoPrincipal());
        String tamperedToken = tamperSignature(token);

        mockMvc.perform(get("/test/security/principal")
                        .header("Authorization", "Bearer " + tamperedToken))
                .andExpect(status().isUnauthorized())
                .andExpect(content().contentTypeCompatibleWith(APPLICATION_JSON))
                .andExpect(jsonPath("$.code").value("A0004"))
                .andExpect(content().string(not(containsString("invalid JWT signature"))));
    }

    @Test
    void shouldReturn401ForMalformedJwt() throws Exception {
        mockMvc.perform(get("/test/security/principal")
                        .header("Authorization", "Bearer not-a-jwt"))
                .andExpect(status().isUnauthorized())
                .andExpect(content().contentTypeCompatibleWith(APPLICATION_JSON))
                .andExpect(jsonPath("$.code").value("A0004"))
                .andExpect(jsonPath("$.message").value("authentication required"));
    }

    @Test
    void shouldReturn403ForRegularUserOnAdminEndpoint() throws Exception {
        mockMvc.perform(get("/test/security/admin")
                        .header("Authorization", bearerToken(DEMO_USERNAME)))
                .andExpect(status().isForbidden())
                .andExpect(content().contentTypeCompatibleWith(APPLICATION_JSON))
                .andExpect(jsonPath("$.success").value(false))
                .andExpect(jsonPath("$.code").value("A0005"))
                .andExpect(jsonPath("$.message").value("access denied"))
                .andExpect(jsonPath("$.data").value((Object) null));
    }

    @Test
    void shouldAllowAdminAuthorityOnAdminEndpoint() throws Exception {
        mockMvc.perform(get("/test/security/admin")
                        .header("Authorization", bearerToken(ADMIN_USERNAME)))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.success").value(true))
                .andExpect(jsonPath("$.data").value("admin-ok"));
    }

    @Test
    void shouldNotReuseJwtIdentityForFollowingRequestWithoutHeader() throws Exception {
        mockMvc.perform(get("/test/security/principal")
                        .header("Authorization", bearerToken(DEMO_USERNAME)))
                .andExpect(status().isOk());

        mockMvc.perform(get("/test/security/principal"))
                .andExpect(status().isUnauthorized())
                .andExpect(jsonPath("$.code").value("A0004"));
    }

    @Test
    void shouldLoadUserOnceForOneJwtRequest() throws Exception {
        mockMvc.perform(get("/test/security/principal")
                        .header("Authorization", bearerToken(DEMO_USERNAME)))
                .andExpect(status().isOk());

        assertEquals(1, userRepository.loadCount());
    }

    private String bearerToken(String username) {
        return "Bearer " + jwtTokenService.generateAccessToken(
                username.equals(ADMIN_USERNAME) ? adminPrincipal() : demoPrincipal()
        );
    }

    private String tamperSignature(String token) {
        String[] parts = token.split("\\.", -1);
        byte[] signature = Base64.getUrlDecoder().decode(parts[2]);
        signature[signature.length - 1] ^= 0x01;
        parts[2] = Base64.getUrlEncoder()
                .withoutPadding()
                .encodeToString(signature);
        return String.join(".", parts);
    }

    private ApiOpsPrincipal demoPrincipal() {
        return new ApiOpsPrincipal(
                1L,
                DEMO_USERNAME,
                "test-password-hash",
                true,
                List.of()
        );
    }

    private ApiOpsPrincipal adminPrincipal() {
        return new ApiOpsPrincipal(
                2L,
                ADMIN_USERNAME,
                "test-password-hash",
                true,
                List.of(new org.springframework.security.core.authority.SimpleGrantedAuthority(
                        "ROLE_ADMIN"
                ))
        );
    }

    @TestConfiguration(proxyBeanMethods = false)
    static class SecurityTestConfiguration {

        @Bean
        @Primary
        CountingAuthUserRepository jwtIntegrationAuthUserRepository() {
            return new CountingAuthUserRepository();
        }

        @Bean
        @Order(1)
        SecurityFilterChain jwtIntegrationAdminSecurityFilterChain(
                HttpSecurity http,
                JwtTokenService jwtTokenService,
                org.springframework.security.core.userdetails.UserDetailsService userDetailsService,
                RestAuthenticationEntryPoint authenticationEntryPoint,
                RestAccessDeniedHandler accessDeniedHandler
        ) throws Exception {
            JwtAuthenticationFilter jwtAuthenticationFilter = new JwtAuthenticationFilter(
                    jwtTokenService,
                    userDetailsService,
                    authenticationEntryPoint
            );
            http
                    .securityMatcher("/test/security/admin")
                    .csrf(AbstractHttpConfigurer::disable)
                    .formLogin(AbstractHttpConfigurer::disable)
                    .httpBasic(AbstractHttpConfigurer::disable)
                    .sessionManagement(session -> session
                            .sessionCreationPolicy(SessionCreationPolicy.STATELESS))
                    .exceptionHandling(exceptionHandling -> exceptionHandling
                            .authenticationEntryPoint(authenticationEntryPoint)
                            .accessDeniedHandler(accessDeniedHandler))
                    .addFilterBefore(jwtAuthenticationFilter, AuthorizationFilter.class)
                    .authorizeHttpRequests(authorize -> authorize
                            .anyRequest().hasAuthority("ROLE_ADMIN"));
            return http.build();
        }
    }

    static final class CountingAuthUserRepository implements AuthUserRepository {

        private final Map<String, ApiOpsPrincipal> principals = new ConcurrentHashMap<>(Map.of(
                DEMO_USERNAME, new ApiOpsPrincipal(
                        1L, DEMO_USERNAME, "test-password-hash", true, List.of()
                ),
                ADMIN_USERNAME, new ApiOpsPrincipal(
                        2L,
                        ADMIN_USERNAME,
                        "test-password-hash",
                        true,
                        List.of(new org.springframework.security.core.authority.SimpleGrantedAuthority(
                                "ROLE_ADMIN"
                        ))
                )
        ));
        private final AtomicInteger loads = new AtomicInteger();

        @Override
        public java.util.Optional<ApiOpsPrincipal> findByUsername(String username) {
            loads.incrementAndGet();
            return java.util.Optional.ofNullable(principals.get(username));
        }

        void resetCount() {
            loads.set(0);
        }

        int loadCount() {
            return loads.get();
        }
    }

    @TestComponent
    @RestController
    @RequestMapping("/test/security")
    static class TestOnlyController {

        @GetMapping("/principal")
        Result<Map<String, Object>> principal(org.springframework.security.core.Authentication authentication) {
            ApiOpsPrincipal principal = (ApiOpsPrincipal) authentication.getPrincipal();
            return Result.success(Map.of(
                    "userId", principal.getUserId(),
                    "username", principal.getUsername(),
                    "authorities", principal.getAuthorities().stream()
                            .map(GrantedAuthority::getAuthority)
                            .toList()
            ));
        }

        @GetMapping("/admin")
        Result<String> admin() {
            return Result.success("admin-ok");
        }
    }
}
