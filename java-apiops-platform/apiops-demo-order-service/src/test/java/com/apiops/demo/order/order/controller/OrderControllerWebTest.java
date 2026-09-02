package com.apiops.demo.order.order.controller;

import com.apiops.demo.order.common.exception.DemoOrderBusinessException;
import com.apiops.demo.order.common.exception.DemoOrderErrorCode;
import com.apiops.demo.order.common.web.GlobalExceptionHandler;
import com.apiops.demo.order.order.application.CreateOrderApplicationService;
import com.apiops.demo.order.order.application.OrderApplicationService;
import com.apiops.demo.order.order.enums.OrderEvent;
import com.apiops.demo.order.order.enums.OrderStatus;
import com.apiops.demo.order.order.vo.OrderDetailVO;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.WebMvcTest;
import org.springframework.context.annotation.Import;
import org.springframework.http.MediaType;
import org.springframework.test.context.bean.override.mockito.MockitoBean;
import org.springframework.test.web.servlet.MockMvc;

import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

@WebMvcTest(controllers = OrderController.class)
@Import(GlobalExceptionHandler.class)
class OrderControllerWebTest {

    @Autowired
    private MockMvc mockMvc;

    @MockitoBean
    private CreateOrderApplicationService createOrderApplicationService;

    @MockitoBean
    private OrderApplicationService orderApplicationService;

    @Test
    void createOrderReturnsOrderDetail() throws Exception {
        when(createOrderApplicationService.createOrder(any()))
                .thenReturn(order(10L, OrderStatus.PENDING_PAYMENT));

        mockMvc.perform(post("/orders")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(validCreateOrderJson()))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.success").value(true))
                .andExpect(jsonPath("$.code").value("ORDER_SUCCESS"))
                .andExpect(jsonPath("$.data.id").value(10))
                .andExpect(jsonPath("$.data.status").value("PENDING_PAYMENT"));

        verify(createOrderApplicationService).createOrder(any());
    }

    @Test
    void createOrderValidationFailureReturnsParameterError() throws Exception {
        mockMvc.perform(post("/orders")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                {
                                  "userId": 1,
                                  "items": [{"productId": 10, "quantity": 0}]
                                }
                                """))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.success").value(false))
                .andExpect(jsonPath("$.code").value("ORDER_PARAM_INVALID"));

        verify(createOrderApplicationService, never()).createOrder(any());
    }

    @Test
    void queryOrderReturnsOrderDetail() throws Exception {
        when(orderApplicationService.queryDetail(10L))
                .thenReturn(order(10L, OrderStatus.PENDING_PAYMENT));

        mockMvc.perform(get("/orders/10"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.success").value(true))
                .andExpect(jsonPath("$.data.id").value(10))
                .andExpect(jsonPath("$.data.status").value("PENDING_PAYMENT"));

        verify(orderApplicationService).queryDetail(10L);
    }

    @Test
    void cancelOrderAlwaysUsesCancelEvent() throws Exception {
        when(orderApplicationService.transition(10L, OrderEvent.CANCEL))
                .thenReturn(OrderStatus.CANCELLED);
        when(orderApplicationService.queryDetail(10L))
                .thenReturn(order(10L, OrderStatus.CANCELLED));

        mockMvc.perform(post("/orders/10/cancel"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.success").value(true))
                .andExpect(jsonPath("$.data.status").value("CANCELLED"));

        verify(orderApplicationService).transition(10L, OrderEvent.CANCEL);
        verify(orderApplicationService).queryDetail(10L);
    }

    @Test
    void businessExceptionUsesGlobalExceptionHandler() throws Exception {
        when(createOrderApplicationService.createOrder(any()))
                .thenThrow(new DemoOrderBusinessException(
                        DemoOrderErrorCode.BUSINESS_CONFLICT,
                        "insufficient inventory for product id 10"));

        mockMvc.perform(post("/orders")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(validCreateOrderJson()))
                .andExpect(status().isConflict())
                .andExpect(jsonPath("$.success").value(false))
                .andExpect(jsonPath("$.code").value("ORDER_BUSINESS_CONFLICT"))
                .andExpect(jsonPath("$.message")
                        .value("insufficient inventory for product id 10"));
    }

    private String validCreateOrderJson() {
        return """
                {
                  "userId": 1,
                  "items": [{"productId": 10, "quantity": 1}]
                }
                """;
    }

    private OrderDetailVO order(Long id, OrderStatus status) {
        OrderDetailVO order = new OrderDetailVO();
        order.setId(id);
        order.setStatus(status.name());
        return order;
    }
}
