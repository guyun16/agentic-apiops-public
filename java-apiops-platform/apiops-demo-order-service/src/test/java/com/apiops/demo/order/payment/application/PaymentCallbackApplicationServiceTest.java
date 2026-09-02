package com.apiops.demo.order.payment.application;

import com.apiops.demo.order.common.exception.DemoOrderBusinessException;
import com.apiops.demo.order.order.entity.OrderEntity;
import com.apiops.demo.order.order.enums.OrderStatus;
import com.apiops.demo.order.order.mapper.OrderMapper;
import com.apiops.demo.order.payment.dto.PaymentCallbackRequest;
import com.apiops.demo.order.payment.entity.PaymentCallbackEntity;
import com.apiops.demo.order.payment.entity.PaymentEntity;
import com.apiops.demo.order.payment.mapper.PaymentCallbackMapper;
import com.apiops.demo.order.payment.mapper.PaymentMapper;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.dao.DuplicateKeyException;

import java.math.BigDecimal;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
class PaymentCallbackApplicationServiceTest {

    @Mock
    private PaymentMapper paymentMapper;
    @Mock
    private PaymentCallbackMapper paymentCallbackMapper;
    @Mock
    private OrderMapper orderMapper;

    @Test
    void fingerprintNormalizesAmountAndExcludesDeliveryTime() {
        PaymentCallbackRequest first = request("cb-1", "99.0", "SUCCESS");
        PaymentCallbackRequest second = request("cb-1", "99.00", " success ");
        first.setCallbackTime(java.time.LocalDateTime.of(2026, 1, 1, 1, 1));
        second.setCallbackTime(java.time.LocalDateTime.of(2026, 2, 2, 2, 2));

        assertThat(PaymentCallbackApplicationService.requestFingerprint(first))
                .isEqualTo(PaymentCallbackApplicationService.requestFingerprint(second))
                .isEqualTo("orderId=20|paymentId=10|amount=99|result=SUCCESS");
    }

    @Test
    void existingCallbackWithDifferentFingerprintIsIdempotencyConflict() {
        PaymentCallbackRequest request = request("cb-2", "100.00", "SUCCESS");
        PaymentCallbackEntity existing = new PaymentCallbackEntity();
        existing.setCallbackNo("cb-2");
        existing.setCallbackAmount(new BigDecimal("99.00"));
        existing.setRequestFingerprint("orderId=20|paymentId=10|amount=99|result=SUCCESS");
        existing.setProcessStatus("SUCCESS");
        when(paymentCallbackMapper.selectOne(org.mockito.ArgumentMatchers.any()))
                .thenReturn(existing);

        assertThatThrownBy(() -> service().handle(request))
                .isInstanceOf(DemoOrderBusinessException.class)
                .hasMessage("payment callback idempotency conflict");
    }

    @Test
    void duplicateCallbackInsertReReadsDifferentFingerprintAndReturnsConflict() {
        PaymentCallbackRequest request = request("cb-duplicate", "99.00", "SUCCESS");
        PaymentEntity payment = payment(10L, 20L, "99.00", "PENDING");
        OrderEntity order = order(20L, OrderStatus.PENDING_PAYMENT);
        PaymentCallbackEntity concurrent = new PaymentCallbackEntity();
        concurrent.setCallbackNo("cb-duplicate");
        concurrent.setPaymentId(10L);
        concurrent.setCallbackAmount(new BigDecimal("100.00"));
        concurrent.setRequestFingerprint("orderId=20|paymentId=10|amount=100|result=SUCCESS");
        concurrent.setProcessStatus("SUCCESS");

        when(paymentCallbackMapper.selectOne(any())).thenReturn(null, concurrent);
        when(paymentMapper.selectById(10L)).thenReturn(payment);
        when(orderMapper.selectById(20L)).thenReturn(order);
        when(paymentCallbackMapper.insert(any(PaymentCallbackEntity.class)))
                .thenThrow(new DuplicateKeyException("duplicate callback_no"));

        assertThatThrownBy(() -> service().handle(request))
                .isInstanceOf(DemoOrderBusinessException.class)
                .hasMessage("payment callback idempotency conflict");
        verify(paymentCallbackMapper, times(2)).selectOne(any());
        verify(paymentCallbackMapper).insert(any(PaymentCallbackEntity.class));
    }

    private PaymentCallbackApplicationService service() {
        return new PaymentCallbackApplicationService(paymentMapper, paymentCallbackMapper, orderMapper);
    }

    private PaymentCallbackRequest request(String callbackId, String amount, String result) {
        PaymentCallbackRequest request = new PaymentCallbackRequest();
        request.setCallbackId(callbackId);
        request.setPaymentId(10L);
        request.setOrderId(20L);
        request.setPaymentAmount(new BigDecimal(amount));
        request.setResult(result);
        return request;
    }

    private PaymentEntity payment(Long id, Long orderId, String amount, String status) {
        PaymentEntity payment = new PaymentEntity();
        payment.setId(id);
        payment.setOrderId(orderId);
        payment.setPaymentAmount(new BigDecimal(amount));
        payment.setStatus(status);
        return payment;
    }

    private OrderEntity order(Long id, OrderStatus status) {
        OrderEntity order = new OrderEntity();
        order.setId(id);
        order.setStatus(status.name());
        return order;
    }
}
