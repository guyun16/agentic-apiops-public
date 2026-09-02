package com.apiops.demo.order.web;

import com.apiops.demo.order.common.web.GlobalExceptionHandler;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.WebMvcTest;
import org.springframework.context.annotation.Import;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;

import static org.assertj.core.api.Assertions.assertThat;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

@WebMvcTest(controllers = OrderFixtureController.class)
@Import(GlobalExceptionHandler.class)
class OrderWebBoundaryTest {

    private static final String INVALID_ORDER_JSON = """
            {
              "userId": 1,
              "items": [
                {
                  "productId": 10,
                  "quantity": 0
                }
              ]
            }
            """;

    @Autowired
    private MockMvc mockMvc;

    @Test
    void invalidNestedQuantityReturnsParameterError() throws Exception {
        mockMvc.perform(post("/fixture/orders")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(INVALID_ORDER_JSON))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.success").value(false))
                .andExpect(jsonPath("$.code").value("ORDER_PARAM_INVALID"));
    }

    @Test
    void missingResourceReturnsNotFoundError() throws Exception {
        mockMvc.perform(get("/fixture/missing-resource"))
                .andExpect(status().isNotFound())
                .andExpect(jsonPath("$.success").value(false))
                .andExpect(jsonPath("$.code").value("ORDER_RESOURCE_NOT_FOUND"));
    }

    @Test
    void businessExceptionReturnsConflictError() throws Exception {
        mockMvc.perform(get("/fixture/conflict"))
                .andExpect(status().isConflict())
                .andExpect(jsonPath("$.success").value(false))
                .andExpect(jsonPath("$.code").value("ORDER_BUSINESS_CONFLICT"))
                .andExpect(jsonPath("$.message").value("business conflict"));
    }

    @Test
    void unknownExceptionReturnsSanitizedSystemError() throws Exception {
        String responseBody = mockMvc.perform(get("/fixture/system-error"))
                .andExpect(status().isInternalServerError())
                .andExpect(jsonPath("$.success").value(false))
                .andExpect(jsonPath("$.code").value("ORDER_SYSTEM_ERROR"))
                .andExpect(jsonPath("$.message").value("internal server error"))
                .andReturn()
                .getResponse()
                .getContentAsString();

        assertThat(responseBody)
                .doesNotContain("database password")
                .doesNotContain("IllegalStateException")
                .doesNotContain("password")
                .doesNotContain("secret")
                .doesNotContain("config.yml")
                .doesNotContain("C:\\secret");
    }
}
