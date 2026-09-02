package com.apiops.demo.order.payment.application;

import com.apiops.demo.order.common.exception.DemoOrderBusinessException;
import com.apiops.demo.order.payment.dto.PaymentCallbackRequest;
import com.apiops.demo.order.payment.vo.PaymentCallbackResultVO;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.Assertions;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.test.context.ActiveProfiles;

import java.math.BigDecimal;
import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.List;
import java.util.UUID;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.ExecutionException;
import java.util.concurrent.Future;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.NONE)
@ActiveProfiles("local")
@EnabledIfEnvironmentVariable(named = "APIOPS_ORDER_DB_URL", matches = ".+")
class PaymentCallbackMySqlIntegrationTest {

    @Autowired
    private PaymentCallbackApplicationService callbackService;

    @Autowired
    private JdbcTemplate jdbcTemplate;

    private final List<Long> userIds = new ArrayList<>();
    private final List<Long> orderIds = new ArrayList<>();
    private final List<Long> paymentIds = new ArrayList<>();
    private final List<String> callbackIds = new ArrayList<>();

    @AfterEach
    void cleanup() {
        for (String callbackId : callbackIds) {
            jdbcTemplate.update("DELETE FROM demo_payment_callback WHERE callback_no = ?", callbackId);
        }
        for (Long paymentId : paymentIds) {
            jdbcTemplate.update("DELETE FROM demo_payment WHERE id = ?", paymentId);
        }
        for (Long orderId : orderIds) {
            jdbcTemplate.update("DELETE FROM demo_order WHERE id = ?", orderId);
        }
        for (Long userId : userIds) {
            jdbcTemplate.update("DELETE FROM demo_user WHERE id = ?", userId);
        }
        callbackIds.clear();
        paymentIds.clear();
        orderIds.clear();
        userIds.clear();
    }

    @Test
    void firstSuccessCallbackUpdatesPaymentOrderAndStoresOneRecord() {
        Fixture fixture = fixture("99.00", "PENDING_PAYMENT", "PENDING");
        PaymentCallbackRequest request = request("first-success", fixture, "99.00", "SUCCESS");

        PaymentCallbackResultVO result = callbackService.handle(request);

        assertThat(result.getOutcome()).isEqualTo("FIRST_SUCCESS");
        assertThat(result.isReplay()).isFalse();
        assertThat(paymentStatus(fixture.paymentId())).isEqualTo("SUCCESS");
        assertThat(orderStatus(fixture.orderId())).isEqualTo("PAID");
        assertThat(callbackCount(request.getCallbackId())).isEqualTo(1L);
        assertThat(callbackProcessStatus(request.getCallbackId())).isEqualTo("SUCCESS");
    }

    @Test
    void sequentialIdenticalCallbackReusesFirstResultAndKeepsOneRecord() {
        Fixture fixture = fixture("99.00", "PENDING_PAYMENT", "PENDING");
        PaymentCallbackRequest request = request("sequential-replay", fixture, "99.00", "SUCCESS");

        PaymentCallbackResultVO first = callbackService.handle(request);
        PaymentCallbackResultVO replay = callbackService.handle(request);

        assertThat(first.getOutcome()).isEqualTo("FIRST_SUCCESS");
        assertThat(replay.getOutcome()).isEqualTo("IDEMPOTENT_REPLAY");
        assertThat(replay.isReplay()).isTrue();
        assertThat(callbackCount(request.getCallbackId())).isEqualTo(1L);
    }

    @Test
    void sameCallbackIdWithDifferentOrderIsIdempotencyConflict() {
        Fixture first = fixture("99.00", "PENDING_PAYMENT", "PENDING");
        Fixture second = fixture("99.00", "PENDING_PAYMENT", "PENDING");
        PaymentCallbackRequest firstRequest = request("order-conflict", first, "99.00", "SUCCESS");
        callbackService.handle(firstRequest);

        PaymentCallbackRequest conflicting = request("order-conflict", second, "99.00", "SUCCESS");
        assertThatThrownBy(() -> callbackService.handle(conflicting))
                .isInstanceOf(DemoOrderBusinessException.class)
                .hasMessage("payment callback idempotency conflict");

        assertThat(paymentStatus(second.paymentId())).isEqualTo("PENDING");
        assertThat(orderStatus(second.orderId())).isEqualTo("PENDING_PAYMENT");
    }

    @Test
    void sameCallbackIdWithDifferentAmountIsIdempotencyConflict() {
        Fixture fixture = fixture("99.00", "PENDING_PAYMENT", "PENDING");
        PaymentCallbackRequest first = request("amount-conflict", fixture, "99.00", "SUCCESS");
        callbackService.handle(first);

        PaymentCallbackRequest conflicting = request("amount-conflict", fixture, "100.00", "SUCCESS");
        assertThatThrownBy(() -> callbackService.handle(conflicting))
                .isInstanceOf(DemoOrderBusinessException.class)
                .hasMessage("payment callback idempotency conflict");
    }

    @Test
    void sameCallbackIdWithDifferentResultIsIdempotencyConflict() {
        Fixture fixture = fixture("99.00", "PENDING_PAYMENT", "PENDING");
        PaymentCallbackRequest first = request("result-conflict", fixture, "99.00", "SUCCESS");
        callbackService.handle(first);

        PaymentCallbackRequest conflicting = request("result-conflict", fixture, "99.00", "FAILED");
        assertThatThrownBy(() -> callbackService.handle(conflicting))
                .isInstanceOf(DemoOrderBusinessException.class)
                .hasMessage("payment callback idempotency conflict");
    }

    @Test
    void numericallyEqualAmountsAreIdenticalForReplay() {
        Fixture fixture = fixture("99.00", "PENDING_PAYMENT", "PENDING");
        callbackService.handle(request("scale-replay", fixture, "99.0", "SUCCESS"));

        PaymentCallbackResultVO replay = callbackService.handle(
                request("scale-replay", fixture, "99.00", "SUCCESS"));

        assertThat(replay.getOutcome()).isEqualTo("IDEMPOTENT_REPLAY");
        assertThat(callbackCount("scale-replay")).isEqualTo(1L);
    }

    @Test
    void illegalPaymentStatusIsRejected() {
        Fixture fixture = fixture("99.00", "PENDING_PAYMENT", "SUCCESS");

        assertThatThrownBy(() -> callbackService.handle(
                request("payment-illegal", fixture, "99.00", "SUCCESS")))
                .isInstanceOf(DemoOrderBusinessException.class)
                .hasMessage("payment status conflict");

        assertThat(callbackCount("payment-illegal")).isZero();
        assertThat(orderStatus(fixture.orderId())).isEqualTo("PENDING_PAYMENT");
    }

    @Test
    void illegalOrderStatusRollsBackPaymentUpdate() {
        Fixture fixture = fixture("99.00", "PAID", "PENDING");

        assertThatThrownBy(() -> callbackService.handle(
                request("order-illegal", fixture, "99.00", "SUCCESS")))
                .isInstanceOf(DemoOrderBusinessException.class)
                .hasMessage("order status conflict");

        assertThat(paymentStatus(fixture.paymentId())).isEqualTo("PENDING");
        assertThat(callbackCount("order-illegal")).isZero();
    }

    @Test
    void concurrentIdenticalCallbacksShareOneSuccessResult() throws Exception {
        Fixture fixture = fixture("99.00", "PENDING_PAYMENT", "PENDING");
        PaymentCallbackRequest request = request("concurrent-same", fixture, "99.00", "SUCCESS");
        ExecutorService executor = Executors.newFixedThreadPool(2);
        CountDownLatch ready = new CountDownLatch(2);
        CountDownLatch start = new CountDownLatch(1);

        try {
            Future<PaymentCallbackResultVO> first = submit(executor, ready, start, request);
            Future<PaymentCallbackResultVO> second = submit(executor, ready, start, request);
            ready.await();
            start.countDown();

            PaymentCallbackResultVO firstResult = first.get();
            PaymentCallbackResultVO secondResult = second.get();
            assertThat(List.of(firstResult.getOutcome(), secondResult.getOutcome()))
                    .containsExactlyInAnyOrder("FIRST_SUCCESS", "IDEMPOTENT_REPLAY");
            assertThat(callbackCount(request.getCallbackId())).isEqualTo(1L);
            assertThat(paymentStatus(fixture.paymentId())).isEqualTo("SUCCESS");
            assertThat(orderStatus(fixture.orderId())).isEqualTo("PAID");
        } finally {
            executor.shutdownNow();
        }
    }

    @Test
    void concurrentDifferentAmountsAllowOnlyTheMatchingRequestToSucceed() throws Exception {
        Fixture fixture = fixture("99.00", "PENDING_PAYMENT", "PENDING");
        PaymentCallbackRequest successfulRequest = request(
                "concurrent-amount-conflict", fixture, "99.00", "SUCCESS");
        PaymentCallbackRequest conflictingRequest = request(
                "concurrent-amount-conflict", fixture, "100.00", "SUCCESS");
        ExecutorService executor = Executors.newFixedThreadPool(2);
        CountDownLatch ready = new CountDownLatch(2);
        CountDownLatch start = new CountDownLatch(1);

        try {
            Future<PaymentCallbackResultVO> successful = submit(
                    executor, ready, start, successfulRequest, 0L);
            // Both tasks are released by the same latch; the short skew makes the
            // matching request win deterministically so the second request observes
            // the committed callback fingerprint.
            Future<PaymentCallbackResultVO> conflicting = submit(
                    executor, ready, start, conflictingRequest, 100L);
            ready.await();
            start.countDown();

            PaymentCallbackResultVO result = successful.get();
            ExecutionException conflict = Assertions.assertThrows(
                    ExecutionException.class, conflicting::get);

            assertThat(result.getOutcome()).isEqualTo("FIRST_SUCCESS");
            assertThat(conflict.getCause())
                    .isInstanceOf(DemoOrderBusinessException.class)
                    .hasMessage("payment callback idempotency conflict");
            assertThat(callbackCount(successfulRequest.getCallbackId())).isEqualTo(1L);
            assertThat(paymentStatus(fixture.paymentId())).isEqualTo("SUCCESS");
            assertThat(orderStatus(fixture.orderId())).isEqualTo("PAID");
            assertThat(callbackFingerprint(successfulRequest.getCallbackId()))
                    .isEqualTo(PaymentCallbackApplicationService.requestFingerprint(successfulRequest));
            assertThat(callbackProcessStatus(successfulRequest.getCallbackId())).isEqualTo("SUCCESS");
        } finally {
            executor.shutdownNow();
        }
    }

    private Future<PaymentCallbackResultVO> submit(
            ExecutorService executor,
            CountDownLatch ready,
            CountDownLatch start,
            PaymentCallbackRequest request
    ) {
        return submit(executor, ready, start, request, 0L);
    }

    private Future<PaymentCallbackResultVO> submit(
            ExecutorService executor,
            CountDownLatch ready,
            CountDownLatch start,
            PaymentCallbackRequest request,
            long delayMillis
    ) {
        return executor.submit(() -> {
            ready.countDown();
            start.await();
            if (delayMillis > 0) {
                Thread.sleep(delayMillis);
            }
            return callbackService.handle(request);
        });
    }

    private PaymentCallbackRequest request(
            String callbackId,
            Fixture fixture,
            String amount,
            String result
    ) {
        PaymentCallbackRequest request = new PaymentCallbackRequest();
        request.setCallbackId(callbackId);
        request.setPaymentId(fixture.paymentId());
        request.setOrderId(fixture.orderId());
        request.setPaymentAmount(new BigDecimal(amount));
        request.setResult(result);
        request.setCallbackTime(LocalDateTime.now());
        callbackIds.add(callbackId);
        return request;
    }

    private Fixture fixture(String amount, String orderStatus, String paymentStatus) {
        Long userId = insertUser();
        LocalDateTime now = LocalDateTime.now();
        jdbcTemplate.update(
                "INSERT INTO demo_order (order_no, user_id, original_amount, discount_amount, "
                        + "payable_amount, status, created_at, updated_at) VALUES (?, ?, ?, 0.00, ?, ?, ?, ?)",
                "callback_order_" + UUID.randomUUID(), userId, new BigDecimal(amount),
                new BigDecimal(amount), orderStatus, now, now);
        Long orderId = jdbcTemplate.queryForObject(
                "SELECT id FROM demo_order WHERE user_id = ? ORDER BY id DESC LIMIT 1", Long.class, userId);
        orderIds.add(orderId);
        jdbcTemplate.update(
                "INSERT INTO demo_payment (payment_no, order_id, payment_amount, status, created_at, updated_at) "
                        + "VALUES (?, ?, ?, ?, ?, ?)",
                "callback_payment_" + UUID.randomUUID(), orderId, new BigDecimal(amount),
                paymentStatus, now, now);
        Long paymentId = jdbcTemplate.queryForObject(
                "SELECT id FROM demo_payment WHERE order_id = ?", Long.class, orderId);
        paymentIds.add(paymentId);
        return new Fixture(orderId, paymentId);
    }

    private Long insertUser() {
        LocalDateTime now = LocalDateTime.now();
        String userNo = "callback_user_" + UUID.randomUUID();
        jdbcTemplate.update(
                "INSERT INTO demo_user (user_no, user_name, status, created_at, updated_at) "
                        + "VALUES (?, 'Callback test user', 'ENABLED', ?, ?)", userNo, now, now);
        Long userId = jdbcTemplate.queryForObject(
                "SELECT id FROM demo_user WHERE user_no = ?", Long.class, userNo);
        userIds.add(userId);
        return userId;
    }

    private String paymentStatus(Long paymentId) {
        return jdbcTemplate.queryForObject(
                "SELECT status FROM demo_payment WHERE id = ?", String.class, paymentId);
    }

    private String orderStatus(Long orderId) {
        return jdbcTemplate.queryForObject(
                "SELECT status FROM demo_order WHERE id = ?", String.class, orderId);
    }

    private long callbackCount(String callbackId) {
        return jdbcTemplate.queryForObject(
                "SELECT COUNT(*) FROM demo_payment_callback WHERE callback_no = ?",
                Long.class, callbackId);
    }

    private String callbackProcessStatus(String callbackId) {
        return jdbcTemplate.queryForObject(
                "SELECT process_status FROM demo_payment_callback WHERE callback_no = ?",
                String.class, callbackId);
    }

    private String callbackFingerprint(String callbackId) {
        return jdbcTemplate.queryForObject(
                "SELECT request_fingerprint FROM demo_payment_callback WHERE callback_no = ?",
                String.class, callbackId);
    }

    private record Fixture(Long orderId, Long paymentId) {
    }
}
