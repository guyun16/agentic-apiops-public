package com.apiops.demo.order.user;

import com.apiops.demo.order.common.web.GlobalExceptionHandler;
import com.apiops.demo.order.user.application.UserApplicationService;
import com.apiops.demo.order.user.controller.UserController;
import com.apiops.demo.order.user.vo.UserVO;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.WebMvcTest;
import org.springframework.boot.test.context.TestConfiguration;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Import;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;

import static org.assertj.core.api.Assertions.assertThat;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.put;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

@WebMvcTest(controllers = UserController.class)
@Import({GlobalExceptionHandler.class, UserWebBoundaryTest.StubConfig.class})
class UserWebBoundaryTest {

    @TestConfiguration
    static class StubConfig {
        @Bean
        UserApplicationService userApplicationService() {
            return new UserApplicationService(null) {
                @Override
                public UserVO createUser(String userNo, String userName) {
                    UserVO vo = new UserVO();
                    vo.setId(100L);
                    vo.setUserNo(userNo);
                    vo.setUserName(userName);
                    vo.setStatus("ENABLED");
                    return vo;
                }

                @Override
                public UserVO queryById(Long id) {
                    if (id == 999L) {
                        throw new com.apiops.demo.order.common.exception
                                .ResourceNotFoundException("user id 999 not found");
                    }
                    UserVO vo = new UserVO();
                    vo.setId(id);
                    vo.setUserNo("usr_test");
                    vo.setUserName("Test User");
                    vo.setStatus("ENABLED");
                    return vo;
                }

                @Override
                public UserVO disableUser(Long id) {
                    if (id == 999L) {
                        throw new com.apiops.demo.order.common.exception
                                .ResourceNotFoundException("user id 999 not found");
                    }
                    UserVO vo = new UserVO();
                    vo.setId(id);
                    vo.setUserNo("usr_test");
                    vo.setUserName("Test User");
                    vo.setStatus("DISABLED");
                    return vo;
                }
            };
        }
    }

    @Autowired
    private MockMvc mockMvc;

    @Test
    void createUserReturnsSuccessWithVO() throws Exception {
        String body = """
                {"userNo":"usr_test","userName":"Test User"}""";
        String response = mockMvc.perform(post("/users")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(body))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.success").value(true))
                .andExpect(jsonPath("$.code").value("ORDER_SUCCESS"))
                .andExpect(jsonPath("$.data.userNo").value("usr_test"))
                .andExpect(jsonPath("$.data.userName").value("Test User"))
                .andExpect(jsonPath("$.data.status").value("ENABLED"))
                .andReturn()
                .getResponse()
                .getContentAsString();
        assertThat(response).doesNotContain("password");
    }

    @Test
    void createUserWithBlankFieldsReturnsBadRequest() throws Exception {
        String body = """
                {"userNo":"","userName":" "}""";
        mockMvc.perform(post("/users")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(body))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.success").value(false))
                .andExpect(jsonPath("$.code").value("ORDER_PARAM_INVALID"));
    }

    @Test
    void queryUserReturnsSuccessWithVO() throws Exception {
        mockMvc.perform(get("/users/1"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.success").value(true))
                .andExpect(jsonPath("$.data.id").value(1))
                .andExpect(jsonPath("$.data.status").value("ENABLED"));
    }

    @Test
    void queryMissingUserReturnsNotFound() throws Exception {
        mockMvc.perform(get("/users/999"))
                .andExpect(status().isNotFound())
                .andExpect(jsonPath("$.success").value(false))
                .andExpect(jsonPath("$.code").value("ORDER_RESOURCE_NOT_FOUND"))
                .andExpect(jsonPath("$.message").value("user id 999 not found"));
    }

    @Test
    void disableUserReturnsDisabledState() throws Exception {
        mockMvc.perform(put("/users/1/disable"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.success").value(true))
                .andExpect(jsonPath("$.data.status").value("DISABLED"));
    }

    @Test
    void disableMissingUserReturnsNotFound() throws Exception {
        mockMvc.perform(put("/users/999/disable"))
                .andExpect(status().isNotFound())
                .andExpect(jsonPath("$.success").value(false))
                .andExpect(jsonPath("$.code").value("ORDER_RESOURCE_NOT_FOUND"));
    }
}
