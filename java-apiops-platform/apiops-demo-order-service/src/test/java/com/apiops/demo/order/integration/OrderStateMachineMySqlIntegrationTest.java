package com.apiops.demo.order.integration;

import com.apiops.demo.order.common.exception.DemoOrderBusinessException;
import com.apiops.demo.order.order.application.OrderApplicationService;
import com.apiops.demo.order.order.entity.OrderEntity;
import com.apiops.demo.order.order.enums.OrderEvent;
import com.apiops.demo.order.order.enums.OrderStatus;
import com.apiops.demo.order.order.mapper.OrderMapper;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.test.context.ActiveProfiles;

import java.math.BigDecimal;
import java.time.LocalDateTime;
import java.util.List;
import java.util.UUID;
import java.util.concurrent.ExecutionException;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;

import static org.assertj.core.api.Assertions.assertThat;

@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.NONE)
@ActiveProfiles("local")
@EnabledIfEnvironmentVariable(named = "APIOPS_ORDER_DB_URL", matches = ".+")
class OrderStateMachineMySqlIntegrationTest {

    @Autowired
    private OrderApplicationService orderApplicationService;

    @Autowired
    private OrderMapper orderMapper;

    @Autowired
    private JdbcTemplate jdbcTemplate;

    private Long orderId;
    private Long userId;

    @AfterEach
    void cleanup() {
        if (orderId != null) {
            jdbcTemplate.update("DELETE FROM demo_order WHERE id = ?", orderId);
        }
        if (userId != null) {
            jdbcTemplate.update("DELETE FROM demo_user WHERE id = ?", userId);
        }
    }

    @Test
    void paymentAndCancellationRaceHasExactlyOneWinner() throws Exception {
        createPendingPaymentOrder();
        assertThat(orderMapper.selectById(orderId).getStatus())
                .isEqualTo(OrderStatus.PENDING_PAYMENT.name());

        ExecutorService executor = Executors.newFixedThreadPool(2);
        try {
            Future<OrderStatus> payment = executor.submit(
                    () -> orderApplicationService.transition(orderId, OrderEvent.PAY_SUCCESS));
            Future<OrderStatus> cancellation = executor.submit(
                    () -> orderApplicationService.transition(orderId, OrderEvent.CANCEL));

            List<Object> outcomes = List.of(outcome(payment), outcome(cancellation));
            assertThat(outcomes.stream().filter(OrderStatus.class::isInstance)).hasSize(1);
            assertThat(outcomes.stream().filter(DemoOrderBusinessException.class::isInstance))
                    .hasSize(1);
        } finally {
            executor.shutdownNow();
        }

        String finalStatus = jdbcTemplate.queryForObject(
                "SELECT status FROM demo_order WHERE id = ?", String.class, orderId);
        assertThat(finalStatus).isIn(
                OrderStatus.PAID.name(), OrderStatus.CANCELLED.name());
    }

    private Object outcome(Future<OrderStatus> future) throws InterruptedException {
        try {
            return future.get();
        } catch (ExecutionException exception) {
            return exception.getCause();
        }
    }

    private void createPendingPaymentOrder() {
        String suffix = UUID.randomUUID().toString();
        LocalDateTime now = LocalDateTime.now();
        jdbcTemplate.update(
                "INSERT INTO demo_user (user_no, user_name, status, created_at, updated_at) "
                        + "VALUES (?, ?, 'ENABLED', ?, ?)",
                "state_machine_user_" + suffix, "State machine test user", now, now);
        userId = jdbcTemplate.queryForObject(
                "SELECT id FROM demo_user WHERE user_no = ?", Long.class,
                "state_machine_user_" + suffix);

        OrderEntity order = new OrderEntity();
        order.setOrderNo("state_machine_order_" + suffix);
        order.setUserId(userId);
        order.setOriginalAmount(BigDecimal.TEN);
        order.setDiscountAmount(BigDecimal.ZERO);
        order.setPayableAmount(BigDecimal.TEN);
        order.setStatus(OrderStatus.PENDING_PAYMENT.name());
        order.setCreatedAt(now);
        order.setUpdatedAt(now);
        assertThat(orderMapper.insert(order)).isEqualTo(1);
        orderId = order.getId();
    }
}
