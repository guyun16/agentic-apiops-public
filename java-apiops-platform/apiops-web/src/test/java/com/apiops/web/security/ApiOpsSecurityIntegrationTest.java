package com.apiops.web.security;

import com.apiops.auth.security.ApiOpsUserDetailsService;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.context.ApplicationContext;
import org.hamcrest.MatcherAssert;
import org.springframework.security.test.web.servlet.request.SecurityMockMvcRequestPostProcessors;
import org.springframework.security.web.SecurityFilterChain;
import org.springframework.test.context.ActiveProfiles;
import org.springframework.test.web.servlet.MockMvc;

import static org.hamcrest.Matchers.containsString;
import static org.hamcrest.Matchers.not;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertNotEquals;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.content;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

@SpringBootTest
@AutoConfigureMockMvc
@ActiveProfiles("test")
class ApiOpsSecurityIntegrationTest {

    @Autowired
    private MockMvc mockMvc;

    @Autowired
    private ApplicationContext applicationContext;

    @Test
    void shouldStartApplicationContextWithSecurityBaseline() {
        // ApplicationContext startup is covered by SpringBootTest construction.
        assertEquals(1, applicationContext.getBeansOfType(SecurityFilterChain.class).size());
        assertNotNull(applicationContext.getBean("passwordEncoder"));
        assertNotNull(applicationContext.getBean(ApiOpsUserDetailsService.class));
    }

    @Test
    void shouldAllowAnonymousHealthCheck() throws Exception {
        mockMvc.perform(get("/actuator/health"))
                .andExpect(status().isOk());
    }

    @Test
    void shouldRejectAnonymousExistingApiEndpoint() throws Exception {
        mockMvc.perform(get("/api/v1/system/info"))
                .andExpect(status().is4xxClientError());
    }

    @Test
    void shouldReturnBadRequestForEmptyLoginFields() throws Exception {
        mockMvc.perform(post("/api/v1/auth/login")
                        .contentType("application/json")
                        .content("{\"username\":\"\",\"password\":\"ignored\"}"))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.success").value(false))
                .andExpect(jsonPath("$.code").value("A0001"));
    }

    @Test
    void shouldReturnBadRequestForEmptyPassword() throws Exception {
        mockMvc.perform(post("/api/v1/auth/login")
                        .contentType("application/json")
                        .content("{\"username\":\"demo-user\",\"password\":\"\"}"))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.success").value(false))
                .andExpect(jsonPath("$.code").value("A0001"));
    }

    @Test
    void shouldUseSameAuthenticationFailureCodeForMissingUserAndWrongPassword() throws Exception {
        var missingUser = mockMvc.perform(post("/api/v1/auth/login")
                        .contentType("application/json")
                        .content("{\"username\":\"missing\",\"password\":\"wrong-password\"}"))
                .andExpect(status().isUnauthorized())
                .andExpect(jsonPath("$.success").value(false))
                .andExpect(jsonPath("$.code").value("A0003"))
                .andExpect(jsonPath("$.message").value("authentication failed"))
                .andReturn()
                .getResponse();

        var wrongPassword = mockMvc.perform(post("/api/v1/auth/login")
                        .contentType("application/json")
                        .content("{\"username\":\"demo-user\",\"password\":\"wrong-password\"}"))
                .andExpect(status().isUnauthorized())
                .andExpect(jsonPath("$.success").value(false))
                .andExpect(jsonPath("$.code").value("A0003"))
                .andExpect(jsonPath("$.message").value("authentication failed"))
                .andReturn()
                .getResponse();

        assertEquals(
                missingUser.getContentAsString(),
                wrongPassword.getContentAsString()
        );
        MatcherAssert.assertThat(
                missingUser.getContentAsString(),
                not(containsString("tokenType"))
        );
        MatcherAssert.assertThat(
                missingUser.getContentAsString(),
                not(containsString("accessToken"))
        );
        MatcherAssert.assertThat(
                missingUser.getContentAsString(),
                not(containsString("expiresAt"))
        );
        assertNotEquals("A0001", "A0003");
    }

    @Test
    void shouldReturnLoginVOWithoutPasswordFields() throws Exception {
        mockMvc.perform(post("/api/v1/auth/login")
                        .contentType("application/json")
                        .content("{\"username\":\"demo-user\",\"password\":\"stage5-demo-password\"}"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.success").value(true))
                .andExpect(jsonPath("$.data.userId").value(1))
                .andExpect(jsonPath("$.data.username").value("demo-user"))
                .andExpect(jsonPath("$.data.tokenType").value("Bearer"))
                .andExpect(jsonPath("$.data.accessToken").isNotEmpty())
                .andExpect(jsonPath("$.data.expiresAt").isNotEmpty())
                .andExpect(content().string(not(containsString("password"))))
                .andExpect(content().string(not(containsString("passwordHash"))))
                .andExpect(content().string(not(containsString("password_hash"))));
    }

    @Test
    void shouldNotPermitOtherMethodsOnExactLoginPath() throws Exception {
        mockMvc.perform(get("/api/v1/auth/login"))
                .andExpect(status().is4xxClientError());
    }

    @Test
    void shouldAllowAuthenticatedRequestToReachExistingApiEndpoint() throws Exception {
        mockMvc.perform(get("/api/v1/system/info")
                        .with(SecurityMockMvcRequestPostProcessors.user("test-user")))
                .andExpect(status().isOk());
    }
}
