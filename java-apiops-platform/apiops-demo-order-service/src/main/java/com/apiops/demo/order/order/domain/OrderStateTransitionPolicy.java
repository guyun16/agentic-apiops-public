package com.apiops.demo.order.order.domain;

import com.apiops.demo.order.common.exception.DemoOrderBusinessException;
import com.apiops.demo.order.common.exception.DemoOrderErrorCode;
import com.apiops.demo.order.order.enums.OrderEvent;
import com.apiops.demo.order.order.enums.OrderStatus;
import org.springframework.stereotype.Component;

/**
 * The application-level order state transition rules for the current stage.
 */
@Component
public class OrderStateTransitionPolicy {

    public OrderStatus targetStatus(OrderStatus currentStatus, OrderEvent event) {
        if (currentStatus == OrderStatus.PENDING_PAYMENT && event == OrderEvent.PAY_SUCCESS) {
            return OrderStatus.PAID;
        }
        if (currentStatus == OrderStatus.PENDING_PAYMENT && event == OrderEvent.CANCEL) {
            return OrderStatus.CANCELLED;
        }
        throw statusConflict();
    }

    private DemoOrderBusinessException statusConflict() {
        return new DemoOrderBusinessException(
                DemoOrderErrorCode.BUSINESS_CONFLICT,
                "order status conflict"
        );
    }
}
