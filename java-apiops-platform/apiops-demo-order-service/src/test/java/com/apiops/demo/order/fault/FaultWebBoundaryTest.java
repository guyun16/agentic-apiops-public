package com.apiops.demo.order.fault;

import com.apiops.demo.order.common.web.GlobalExceptionHandler;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.WebMvcTest;
import org.springframework.context.annotation.Import;
import org.springframework.test.context.ActiveProfiles;
import org.springframework.test.context.bean.override.mockito.MockitoBean;
import org.springframework.test.web.servlet.MockMvc;

import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

@WebMvcTest(controllers = FaultController.class)
@Import(GlobalExceptionHandler.class)
@ActiveProfiles("test")
class FaultWebBoundaryTest {

    @Autowired
    private MockMvc mockMvc;

    @MockitoBean
    private FaultService faultService;

    @Test
    void tokenExpiredReturns401() throws Exception {
        mockMvc.perform(post("/api/faults/token-expired"))
                .andExpect(status().isUnauthorized())
                .andExpect(jsonPath("$.success").value(false))
                .andExpect(jsonPath("$.code").value("ORDER_TOKEN_EXPIRED"))
                .andExpect(jsonPath("$.message").value("token expired"))
                .andExpect(jsonPath("$.data").isEmpty());
    }

    @Test
    void slowSqlDefaultDelayUses500ms() throws Exception {
        when(faultService.executeSlowSql(500)).thenReturn(501L);

        mockMvc.perform(get("/api/faults/slow-sql"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.success").value(true))
                .andExpect(jsonPath("$.data.requestedDelayMs").value(500))
                .andExpect(jsonPath("$.data.elapsedMs").isNumber());
        verify(faultService).executeSlowSql(500);
    }

    @Test
    void slowSqlWith100ms() throws Exception {
        when(faultService.executeSlowSql(100)).thenReturn(101L);
        mockMvc.perform(get("/api/faults/slow-sql?delayMs=100"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.requestedDelayMs").value(100));
    }

    @Test
    void slowSqlWith2000ms() throws Exception {
        when(faultService.executeSlowSql(2000)).thenReturn(2001L);
        mockMvc.perform(get("/api/faults/slow-sql?delayMs=2000"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.requestedDelayMs").value(2000));
    }

    @Test
    void slowSqlWith99msReturnsParamInvalid() throws Exception {
        mockMvc.perform(get("/api/faults/slow-sql?delayMs=99"))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.success").value(false))
                .andExpect(jsonPath("$.code").value("ORDER_PARAM_INVALID"));
        verify(faultService, never()).executeSlowSql(99);
    }

    @Test
    void slowSqlWith2001msReturnsParamInvalid() throws Exception {
        mockMvc.perform(get("/api/faults/slow-sql?delayMs=2001"))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.success").value(false))
                .andExpect(jsonPath("$.code").value("ORDER_PARAM_INVALID"));
        verify(faultService, never()).executeSlowSql(2001);
    }
}
