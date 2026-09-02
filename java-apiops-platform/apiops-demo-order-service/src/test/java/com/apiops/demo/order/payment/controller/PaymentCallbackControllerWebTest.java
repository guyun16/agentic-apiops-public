package com.apiops.demo.order.payment.controller;

import com.apiops.demo.order.common.web.GlobalExceptionHandler;
import com.apiops.demo.order.payment.application.PaymentCallbackApplicationService;
import com.apiops.demo.order.payment.vo.PaymentCallbackResultVO;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.WebMvcTest;
import org.springframework.context.annotation.Import;
import org.springframework.http.MediaType;
import org.springframework.test.context.TestPropertySource;
import org.springframework.test.context.bean.override.mockito.MockitoBean;
import org.springframework.test.web.servlet.MockMvc;

import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

@WebMvcTest(controllers = PaymentCallbackController.class)
@Import(GlobalExceptionHandler.class)
@TestPropertySource(properties = "spring.datasource.url=jdbc:test")
class PaymentCallbackControllerWebTest {

    @Autowired
    private MockMvc mockMvc;

    @MockitoBean
    private PaymentCallbackApplicationService paymentCallbackApplicationService;

    @Test
    void callbackReturnsPaymentCallbackResult() throws Exception {
        PaymentCallbackResultVO result = new PaymentCallbackResultVO();
        result.setCallbackId("callback-1");
        result.setPaymentId(20L);
        result.setOrderId(10L);
        result.setResult("SUCCESS");
        result.setOutcome("FIRST_SUCCESS");
        result.setReplay(false);
        when(paymentCallbackApplicationService.handle(any())).thenReturn(result);

        mockMvc.perform(post("/payments/callback")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(validCallbackJson()))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.success").value(true))
                .andExpect(jsonPath("$.code").value("ORDER_SUCCESS"))
                .andExpect(jsonPath("$.data.callbackId").value("callback-1"))
                .andExpect(jsonPath("$.data.outcome").value("FIRST_SUCCESS"))
                .andExpect(jsonPath("$.data.replay").value(false));

        verify(paymentCallbackApplicationService).handle(any());
    }

    @Test
    void malformedCallbackReturnsParameterError() throws Exception {
        mockMvc.perform(post("/payments/callback")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                {
                                  "callbackId": "callback-1",
                                  "paymentId": 20,
                                  "orderId": 10,
                                  "paymentAmount": "not-a-number",
                                  "result": "SUCCESS"
                                }
                                """))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.success").value(false))
                .andExpect(jsonPath("$.code").value("ORDER_PARAM_INVALID"));

        verify(paymentCallbackApplicationService, never()).handle(any());
    }

    @Test
    void blankCallbackIdReturnsParameterError() throws Exception {
        mockMvc.perform(post("/payments/callback")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                {
                                  "callbackId": " ",
                                  "paymentId": 20,
                                  "orderId": 10,
                                  "paymentAmount": 99.00,
                                  "result": "SUCCESS"
                                }
                                """))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.success").value(false))
                .andExpect(jsonPath("$.code").value("ORDER_PARAM_INVALID"));

        verify(paymentCallbackApplicationService, never()).handle(any());
    }

    private String validCallbackJson() {
        return """
                {
                  "callbackId": "callback-1",
                  "paymentId": 20,
                  "orderId": 10,
                  "paymentAmount": 99.00,
                  "result": "SUCCESS"
                }
                """;
    }
}
