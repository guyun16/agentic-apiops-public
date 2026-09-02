package com.apiops.demo.order.payment.application;

import com.apiops.demo.order.common.exception.DemoOrderBusinessException;
import com.apiops.demo.order.common.exception.DemoOrderErrorCode;
import com.apiops.demo.order.common.exception.ResourceNotFoundException;
import com.apiops.demo.order.order.entity.OrderEntity;
import com.apiops.demo.order.order.enums.OrderStatus;
import com.apiops.demo.order.order.mapper.OrderMapper;
import com.apiops.demo.order.payment.dto.PaymentCallbackRequest;
import com.apiops.demo.order.payment.entity.PaymentCallbackEntity;
import com.apiops.demo.order.payment.entity.PaymentEntity;
import com.apiops.demo.order.payment.enums.PaymentStatus;
import com.apiops.demo.order.payment.mapper.PaymentCallbackMapper;
import com.apiops.demo.order.payment.mapper.PaymentMapper;
import com.apiops.demo.order.payment.vo.PaymentCallbackResultVO;
import com.baomidou.mybatisplus.core.toolkit.Wrappers;
import org.springframework.dao.DuplicateKeyException;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.transaction.annotation.Isolation;

import java.math.BigDecimal;
import java.time.LocalDateTime;
import java.util.Locale;
import java.util.Objects;

@Service
@ConditionalOnProperty(name = "spring.datasource.url")
public class PaymentCallbackApplicationService {

    private static final String PROCESSING = "PROCESSING";
    private static final String PROCESSED = "SUCCESS";
    private static final String FIRST_SUCCESS = "FIRST_SUCCESS";
    private static final String IDEMPOTENT_REPLAY = "IDEMPOTENT_REPLAY";
    private static final String SUCCESS_RESULT = "SUCCESS";

    private final PaymentMapper paymentMapper;
    private final PaymentCallbackMapper paymentCallbackMapper;
    private final OrderMapper orderMapper;

    public PaymentCallbackApplicationService(
            PaymentMapper paymentMapper,
            PaymentCallbackMapper paymentCallbackMapper,
            OrderMapper orderMapper
    ) {
        this.paymentMapper = paymentMapper;
        this.paymentCallbackMapper = paymentCallbackMapper;
        this.orderMapper = orderMapper;
    }

    /**
     * Handles one payment success callback in one local transaction.
     * Duplicate-key exceptions are recoverable only after the callback row is re-read.
     */
    @Transactional(isolation = Isolation.READ_COMMITTED, noRollbackFor = DuplicateKeyException.class)
    public PaymentCallbackResultVO handle(PaymentCallbackRequest request) {
        validateRequest(request);
        String fingerprint = requestFingerprint(request);

        PaymentCallbackEntity existing = findCallback(request.getCallbackId());
        if (existing != null) {
            return reuseExistingOrConflict(existing, request, fingerprint);
        }

        PaymentEntity payment = requirePayment(request.getPaymentId());
        OrderEntity order = requireOrder(request.getOrderId());
        try {
            validatePaymentOrder(payment, order, request);
            validateSuccessResult(request);
        } catch (DemoOrderBusinessException validationFailure) {
            // A matching callback may have committed while this request was reading
            // the payment. Re-read it so a racing conflicting delivery is classified
            // as an idempotency conflict rather than as a payment validation error.
            PaymentCallbackEntity concurrent = findCallback(request.getCallbackId());
            if (concurrent != null) {
                return reuseExistingOrConflict(concurrent, request, fingerprint);
            }
            throw validationFailure;
        }

        PaymentCallbackEntity callback = newCallback(request, fingerprint);
        try {
            requireInserted(paymentCallbackMapper.insert(callback), "payment callback");
        } catch (DuplicateKeyException duplicateKeyException) {
            PaymentCallbackEntity concurrent = findCallback(request.getCallbackId());
            if (concurrent == null) {
                throw duplicateKeyException;
            }
            return reuseExistingOrConflict(concurrent, request, fingerprint);
        }

        if (!PaymentStatus.PENDING.name().equals(payment.getStatus())) {
            throw paymentStatusConflict();
        }

        LocalDateTime processedAt = LocalDateTime.now();
        int paymentRows = paymentMapper.markSuccessIfPending(
                payment.getId(), processedAt);
        if (paymentRows != 1) {
            throw classifyPaymentUpdateFailure(payment.getId());
        }

        int orderRows = orderMapper.updateStatusIfExpected(
                order.getId(),
                OrderStatus.PENDING_PAYMENT.name(),
                OrderStatus.PAID.name());
        if (orderRows != 1) {
            throw classifyOrderUpdateFailure(order.getId());
        }

        int callbackRows = paymentCallbackMapper.markProcessed(
                request.getCallbackId(), fingerprint, PROCESSED,
                "payment callback accepted", processedAt);
        requireUpdated(callbackRows, "payment callback");

        return result(request, FIRST_SUCCESS, false);
    }

    /** Alias with an application-service naming convention used by callers. */
    @Transactional(isolation = Isolation.READ_COMMITTED, noRollbackFor = DuplicateKeyException.class)
    public PaymentCallbackResultVO process(PaymentCallbackRequest request) {
        return handle(request);
    }

    static String requestFingerprint(PaymentCallbackRequest request) {
        return "orderId=" + request.getOrderId()
                + "|paymentId=" + request.getPaymentId()
                + "|amount=" + normalizeAmount(request.getPaymentAmount())
                + "|result=" + normalizeResult(request.getResult());
    }

    private PaymentCallbackEntity findCallback(String callbackId) {
        return paymentCallbackMapper.selectOne(
                Wrappers.<PaymentCallbackEntity>lambdaQuery()
                        .eq(PaymentCallbackEntity::getCallbackNo, callbackId));
    }

    private PaymentCallbackResultVO reuseExistingOrConflict(
            PaymentCallbackEntity existing,
            PaymentCallbackRequest request,
            String fingerprint
    ) {
        if (!Objects.equals(existing.getRequestFingerprint(), fingerprint)
                || existing.getCallbackAmount() == null
                || existing.getCallbackAmount().compareTo(request.getPaymentAmount()) != 0) {
            throw idempotencyConflict();
        }
        if (!PROCESSED.equals(existing.getProcessStatus())) {
            throw businessConflict("payment callback is not completed");
        }
        return result(request, IDEMPOTENT_REPLAY, true);
    }

    private PaymentEntity requirePayment(Long paymentId) {
        PaymentEntity payment = paymentMapper.selectById(paymentId);
        if (payment == null) {
            throw new ResourceNotFoundException("payment not found");
        }
        return payment;
    }

    private OrderEntity requireOrder(Long orderId) {
        OrderEntity order = orderMapper.selectById(orderId);
        if (order == null) {
            throw new ResourceNotFoundException("order not found");
        }
        return order;
    }

    private void validatePaymentOrder(
            PaymentEntity payment,
            OrderEntity order,
            PaymentCallbackRequest request
    ) {
        if (!Objects.equals(payment.getOrderId(), request.getOrderId())
                || !Objects.equals(payment.getOrderId(), order.getId())) {
            throw businessConflict("payment and order conflict");
        }
        if (payment.getPaymentAmount() == null
                || payment.getPaymentAmount().compareTo(request.getPaymentAmount()) != 0) {
            throw businessConflict("payment callback amount conflict");
        }
    }

    private void validateSuccessResult(PaymentCallbackRequest request) {
        if (!SUCCESS_RESULT.equals(normalizeResult(request.getResult()))) {
            throw businessConflict("payment callback result is not SUCCESS");
        }
    }

    private PaymentCallbackEntity newCallback(
            PaymentCallbackRequest request,
            String fingerprint
    ) {
        LocalDateTime now = LocalDateTime.now();
        PaymentCallbackEntity callback = new PaymentCallbackEntity();
        callback.setCallbackNo(request.getCallbackId());
        callback.setPaymentId(request.getPaymentId());
        callback.setCallbackAmount(request.getPaymentAmount());
        callback.setRequestFingerprint(fingerprint);
        callback.setProcessStatus(PROCESSING);
        callback.setResultCode(normalizeResult(request.getResult()));
        callback.setReceivedAt(request.getCallbackTime() == null
                ? now : request.getCallbackTime());
        callback.setCreatedAt(now);
        callback.setUpdatedAt(now);
        return callback;
    }

    private PaymentCallbackResultVO result(
            PaymentCallbackRequest request,
            String outcome,
            boolean replay
    ) {
        PaymentCallbackResultVO result = new PaymentCallbackResultVO();
        result.setCallbackId(request.getCallbackId());
        result.setPaymentId(request.getPaymentId());
        result.setOrderId(request.getOrderId());
        result.setPaymentAmount(request.getPaymentAmount());
        result.setResult(normalizeResult(request.getResult()));
        result.setOutcome(outcome);
        result.setReplay(replay);
        return result;
    }

    private RuntimeException classifyPaymentUpdateFailure(Long paymentId) {
        PaymentEntity latest = paymentMapper.selectById(paymentId);
        if (latest == null) {
            return new ResourceNotFoundException("payment not found");
        }
        if (PaymentStatus.PENDING.name().equals(latest.getStatus())) {
            return new IllegalStateException("payment success update affected unexpected rows");
        }
        return paymentStatusConflict();
    }

    private RuntimeException classifyOrderUpdateFailure(Long orderId) {
        OrderEntity latest = orderMapper.selectById(orderId);
        if (latest == null) {
            return new ResourceNotFoundException("order not found");
        }
        if (OrderStatus.PENDING_PAYMENT.name().equals(latest.getStatus())) {
            return new IllegalStateException("order paid update affected unexpected rows");
        }
        return businessConflict("order status conflict");
    }

    private void validateRequest(PaymentCallbackRequest request) {
        if (request == null || isBlank(request.getCallbackId())
                || request.getPaymentId() == null || request.getPaymentId() <= 0
                || request.getOrderId() == null || request.getOrderId() <= 0
                || request.getPaymentAmount() == null
                || request.getPaymentAmount().signum() < 0
                || isBlank(request.getResult())) {
            throw new IllegalArgumentException("invalid payment callback request");
        }
    }

    private static String normalizeAmount(BigDecimal amount) {
        return amount.stripTrailingZeros().toPlainString();
    }

    private static String normalizeResult(String result) {
        return result.trim().toUpperCase(Locale.ROOT);
    }

    private static boolean isBlank(String value) {
        return value == null || value.isBlank();
    }

    private static void requireInserted(int rows, String resource) {
        if (rows != 1) {
            throw new IllegalStateException("expected one " + resource + " row, got " + rows);
        }
    }

    private static void requireUpdated(int rows, String resource) {
        if (rows != 1) {
            throw new IllegalStateException("expected one " + resource + " update, got " + rows);
        }
    }

    private static DemoOrderBusinessException idempotencyConflict() {
        return businessConflict("payment callback idempotency conflict");
    }

    private static DemoOrderBusinessException paymentStatusConflict() {
        return businessConflict("payment status conflict");
    }

    private static DemoOrderBusinessException businessConflict(String message) {
        return new DemoOrderBusinessException(DemoOrderErrorCode.BUSINESS_CONFLICT, message);
    }
}
