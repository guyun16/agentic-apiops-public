package com.apiops.demo.order.order.application;

import com.apiops.demo.order.common.exception.ResourceNotFoundException;
import com.apiops.demo.order.order.enums.OrderStatus;
import com.apiops.demo.order.order.query.OrderPageQuery;
import com.apiops.demo.order.order.vo.OrderDetailVO;
import com.apiops.demo.order.order.vo.OrderPageVO;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.test.annotation.Rollback;
import org.springframework.test.context.ActiveProfiles;
import org.springframework.transaction.annotation.Transactional;

import java.math.BigDecimal;
import java.time.LocalDateTime;
import java.util.UUID;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.NONE)
@ActiveProfiles("local")
@EnabledIfEnvironmentVariable(named = "APIOPS_ORDER_DB_URL", matches = ".+")
@Transactional
@Rollback
class OrderQueryMySqlIntegrationTest {

    @Autowired
    private OrderApplicationService orderApplicationService;

    @Autowired
    private JdbcTemplate jdbcTemplate;

    @Test
    void detailContainsAllItemsAndUsesSnapshotsAfterProductChanges() {
        String suffix = UUID.randomUUID().toString();
        Long userId = insertUser(suffix);
        Long firstProductId = insertProduct(suffix + "_one", "Current One", "10.00");
        Long secondProductId = insertProduct(suffix + "_two", "Current Two", "20.00");
        Long orderId = insertOrder(suffix, userId, OrderStatus.PAID.name(), LocalDateTime.now());
        insertItem(orderId, firstProductId, "Snapshot One", "8.50", 2, "17.00");
        insertItem(orderId, secondProductId, "Snapshot Two", "19.00", 1, "19.00");

        jdbcTemplate.update("UPDATE demo_product SET product_name = ?, sale_price = ? WHERE id = ?",
                "Changed One", new BigDecimal("99.99"), firstProductId);
        jdbcTemplate.update("UPDATE demo_product SET product_name = ?, sale_price = ? WHERE id = ?",
                "Changed Two", new BigDecimal("88.88"), secondProductId);

        OrderDetailVO detail = orderApplicationService.queryDetail(orderId);

        assertThat(detail.getId()).isEqualTo(orderId);
        assertThat(detail.getStatus()).isEqualTo(OrderStatus.PAID.name());
        assertThat(detail.getItems()).hasSize(2);
        assertThat(detail.getItems()).extracting("productName")
                .containsExactly("Snapshot One", "Snapshot Two");
        assertThat(detail.getItems()).extracting("unitPrice")
                .containsExactly(new BigDecimal("8.50"), new BigDecimal("19.00"));
        assertThat(detail.getItems()).extracting("quantity").containsExactly(2, 1);
        assertThat(detail.getItems()).extracting("lineAmount")
                .containsExactly(new BigDecimal("17.00"), new BigDecimal("19.00"));
    }

    @Test
    void pageFiltersByUserStatusAndCombination() {
        String suffix = UUID.randomUUID().toString();
        Long firstUserId = insertUser(suffix + "_first");
        Long secondUserId = insertUser(suffix + "_second");
        Long firstPending = insertOrder(suffix + "_pending", firstUserId,
                OrderStatus.PENDING_PAYMENT.name(), LocalDateTime.now().minusMinutes(3));
        Long firstPaid = insertOrder(suffix + "_paid", firstUserId,
                OrderStatus.PAID.name(), LocalDateTime.now().minusMinutes(2));
        insertOrder(suffix + "_other", secondUserId,
                OrderStatus.PAID.name(), LocalDateTime.now().minusMinutes(1));

        OrderPageQuery byUser = new OrderPageQuery();
        byUser.setUserId(firstUserId);
        OrderPageVO userPage = orderApplicationService.page(byUser);
        assertThat(userPage.getRecords()).extracting("id")
                .containsExactly(firstPaid, firstPending);

        OrderPageQuery byStatus = new OrderPageQuery();
        byStatus.setStatus(OrderStatus.PAID.name());
        OrderPageVO statusPage = orderApplicationService.page(byStatus);
        assertThat(statusPage.getRecords()).extracting("id")
                .contains(firstPaid);

        OrderPageQuery combined = new OrderPageQuery();
        combined.setUserId(firstUserId);
        combined.setStatus(OrderStatus.PAID.name());
        assertThat(orderApplicationService.page(combined).getRecords()).extracting("id")
                .containsExactly(firstPaid);
    }

    @Test
    void missingOrderDetailReturnsResourceNotFound() {
        assertThatThrownBy(() -> orderApplicationService.queryDetail(Long.MAX_VALUE))
                .isInstanceOf(ResourceNotFoundException.class);
    }

    private Long insertUser(String suffix) {
        LocalDateTime now = LocalDateTime.now();
        String userNo = "query_user_" + suffix;
        jdbcTemplate.update(
                "INSERT INTO demo_user (user_no, user_name, status, created_at, updated_at) "
                        + "VALUES (?, ?, 'ENABLED', ?, ?)",
                userNo, "Query test user", now, now);
        return jdbcTemplate.queryForObject(
                "SELECT id FROM demo_user WHERE user_no = ?", Long.class, userNo);
    }

    private Long insertProduct(String productNo, String productName, String price) {
        LocalDateTime now = LocalDateTime.now();
        jdbcTemplate.update(
                "INSERT INTO demo_product "
                        + "(product_no, product_name, sale_price, status, version, deleted, created_at, updated_at) "
                        + "VALUES (?, ?, ?, 'ON_SALE', 0, 0, ?, ?)",
                "query_product_" + productNo, productName, new BigDecimal(price), now, now);
        return jdbcTemplate.queryForObject(
                "SELECT id FROM demo_product WHERE product_no = ?", Long.class,
                "query_product_" + productNo);
    }

    private Long insertOrder(String suffix, Long userId, String status, LocalDateTime createdAt) {
        jdbcTemplate.update(
                "INSERT INTO demo_order "
                        + "(order_no, user_id, original_amount, discount_amount, payable_amount, "
                        + "status, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                "query_order_" + suffix, userId, new BigDecimal("100.00"), BigDecimal.ZERO,
                new BigDecimal("100.00"), status, createdAt, createdAt);
        return jdbcTemplate.queryForObject(
                "SELECT id FROM demo_order WHERE order_no = ?", Long.class,
                "query_order_" + suffix);
    }

    private void insertItem(Long orderId, Long productId, String name, String unitPrice,
                            int quantity, String lineAmount) {
        LocalDateTime now = LocalDateTime.now();
        jdbcTemplate.update(
                "INSERT INTO demo_order_item "
                        + "(order_id, product_id, product_no_snapshot, product_name_snapshot, "
                        + "unit_price, quantity, line_amount, created_at, updated_at) "
                        + "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                orderId, productId, "snapshot_product_" + productId, name,
                new BigDecimal(unitPrice), quantity, new BigDecimal(lineAmount), now, now);
    }
}
