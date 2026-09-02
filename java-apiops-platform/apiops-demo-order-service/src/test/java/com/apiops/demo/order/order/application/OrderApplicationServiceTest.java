package com.apiops.demo.order.order.application;

import com.apiops.demo.order.common.exception.DemoOrderBusinessException;
import com.apiops.demo.order.common.exception.ResourceNotFoundException;
import com.apiops.demo.order.order.domain.OrderStateTransitionPolicy;
import com.apiops.demo.order.order.entity.OrderEntity;
import com.apiops.demo.order.order.enums.OrderEvent;
import com.apiops.demo.order.order.enums.OrderStatus;
import com.apiops.demo.order.order.mapper.OrderMapper;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoMoreInteractions;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
class OrderApplicationServiceTest {

    @Mock
    private OrderMapper orderMapper;

    private final OrderStateTransitionPolicy policy = new OrderStateTransitionPolicy();

    @Test
    void appliesPaySuccessWithExpectedStatus() {
        OrderEntity order = order(10L, OrderStatus.PENDING_PAYMENT);
        when(orderMapper.selectById(10L)).thenReturn(order);
        when(orderMapper.updateStatusIfExpected(10L, "PENDING_PAYMENT", "PAID"))
                .thenReturn(1);

        OrderStatus result = service().transition(10L, OrderEvent.PAY_SUCCESS);

        assertThat(result).isEqualTo(OrderStatus.PAID);
        verify(orderMapper).updateStatusIfExpected(10L, "PENDING_PAYMENT", "PAID");
        verifyNoMoreInteractions(orderMapper);
    }

    @Test
    void rowsZeroAndExistingOrderBecomeStatusConflict() {
        when(orderMapper.selectById(10L))
                .thenReturn(order(10L, OrderStatus.PENDING_PAYMENT), order(10L, OrderStatus.PAID));
        when(orderMapper.updateStatusIfExpected(10L, "PENDING_PAYMENT", "PAID"))
                .thenReturn(0);

        assertThatThrownBy(() -> service().transition(10L, OrderEvent.PAY_SUCCESS))
                .isInstanceOf(DemoOrderBusinessException.class)
                .hasMessage("order status conflict");
        verify(orderMapper, times(2)).selectById(10L);
        verify(orderMapper).updateStatusIfExpected(10L, "PENDING_PAYMENT", "PAID");
    }

    @Test
    void rowsZeroAndMissingOrderBecomeNotFound() {
        when(orderMapper.selectById(10L))
                .thenReturn(order(10L, OrderStatus.PENDING_PAYMENT))
                .thenReturn(null);
        when(orderMapper.updateStatusIfExpected(10L, "PENDING_PAYMENT", "PAID"))
                .thenReturn(0);

        assertThatThrownBy(() -> service().transition(10L, OrderEvent.PAY_SUCCESS))
                .isInstanceOf(ResourceNotFoundException.class)
                .hasMessage("order not found");
    }

    private OrderApplicationService service() {
        return new OrderApplicationService(orderMapper, policy);
    }

    private OrderEntity order(Long id, OrderStatus status) {
        OrderEntity order = new OrderEntity();
        order.setId(id);
        order.setStatus(status.name());
        return order;
    }
}
