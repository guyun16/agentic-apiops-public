package com.apiops.demo.order.order.domain;

import com.apiops.demo.order.common.exception.DemoOrderBusinessException;
import com.apiops.demo.order.order.enums.OrderEvent;
import com.apiops.demo.order.order.enums.OrderStatus;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

class OrderStateTransitionPolicyTest {

    private final OrderStateTransitionPolicy policy = new OrderStateTransitionPolicy();

    @Test
    void paySuccessMovesPendingPaymentToPaid() {
        assertThat(policy.targetStatus(OrderStatus.PENDING_PAYMENT, OrderEvent.PAY_SUCCESS))
                .isEqualTo(OrderStatus.PAID);
    }

    @Test
    void cancelMovesPendingPaymentToCancelled() {
        assertThat(policy.targetStatus(OrderStatus.PENDING_PAYMENT, OrderEvent.CANCEL))
                .isEqualTo(OrderStatus.CANCELLED);
    }

    @Test
    void paidCannotBeTransitioned() {
        assertStatusConflict(OrderStatus.PAID, OrderEvent.CANCEL);
        assertStatusConflict(OrderStatus.PAID, OrderEvent.PAY_SUCCESS);
    }

    @Test
    void cancelledCannotBeTransitioned() {
        assertStatusConflict(OrderStatus.CANCELLED, OrderEvent.CANCEL);
        assertStatusConflict(OrderStatus.CANCELLED, OrderEvent.PAY_SUCCESS);
    }

    private void assertStatusConflict(OrderStatus status, OrderEvent event) {
        assertThatThrownBy(() -> policy.targetStatus(status, event))
                .isInstanceOf(DemoOrderBusinessException.class)
                .hasMessage("order status conflict");
    }
}
