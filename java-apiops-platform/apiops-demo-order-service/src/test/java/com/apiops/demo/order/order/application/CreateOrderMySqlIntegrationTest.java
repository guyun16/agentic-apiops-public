package com.apiops.demo.order.order.application;

import com.apiops.demo.order.common.exception.DemoOrderBusinessException;
import com.apiops.demo.order.common.exception.ResourceNotFoundException;
import com.apiops.demo.order.coupon.mapper.CouponMapper;
import com.apiops.demo.order.coupon.mapper.UserCouponMapper;
import com.apiops.demo.order.inventory.application.InventoryApplicationService;
import com.apiops.demo.order.inventory.application.InventoryDeductCommand;
import com.apiops.demo.order.inventory.mapper.InventoryMapper;
import com.apiops.demo.order.order.dto.CreateOrderItemRequest;
import com.apiops.demo.order.order.dto.CreateOrderRequest;
import com.apiops.demo.order.order.entity.OrderItemEntity;
import com.apiops.demo.order.order.enums.OrderStatus;
import com.apiops.demo.order.order.mapper.OrderItemMapper;
import com.apiops.demo.order.order.mapper.OrderMapper;
import com.apiops.demo.order.order.vo.OrderDetailVO;
import com.apiops.demo.order.payment.entity.PaymentEntity;
import com.apiops.demo.order.payment.mapper.PaymentMapper;
import com.apiops.demo.order.product.mapper.ProductMapper;
import com.apiops.demo.order.user.mapper.UserMapper;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.context.TestConfiguration;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Import;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.test.context.ActiveProfiles;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.support.TransactionTemplate;

import java.math.BigDecimal;
import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.List;
import java.util.UUID;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.NONE)
@ActiveProfiles("local")
@Import(CreateOrderMySqlIntegrationTest.CreateOrderFailureTestConfiguration.class)
@EnabledIfEnvironmentVariable(named = "APIOPS_ORDER_DB_URL", matches = ".+")
class CreateOrderMySqlIntegrationTest {

    @Autowired
    private CreateOrderApplicationService createOrderApplicationService;

    @Autowired
    private JdbcTemplate jdbcTemplate;

    @Autowired
    private PlatformTransactionManager transactionManager;

    @Autowired
    @Qualifier("failingOrderItemService")
    private FailingCreateOrderApplicationService failingOrderItemService;

    @Autowired
    @Qualifier("failingPaymentService")
    private FailingCreateOrderApplicationService failingPaymentService;

    @Autowired
    @Qualifier("failingCouponService")
    private FailingCreateOrderApplicationService failingCouponService;

    @Autowired private UserMapper userMapper;
    @Autowired private ProductMapper productMapper;
    @Autowired private InventoryMapper inventoryMapper;
    @Autowired private InventoryApplicationService inventoryApplicationService;
    @Autowired private CouponMapper couponMapper;
    @Autowired private UserCouponMapper userCouponMapper;
    @Autowired private OrderMapper orderMapper;
    @Autowired private OrderItemMapper orderItemMapper;
    @Autowired private PaymentMapper paymentMapper;

    private final List<Long> userIds = new ArrayList<>();
    private final List<Long> productIds = new ArrayList<>();
    private final List<Long> couponIds = new ArrayList<>();
    private final List<Long> userCouponIds = new ArrayList<>();
    private final List<Long> orderIds = new ArrayList<>();

    @AfterEach
    void cleanup() {
        for (Long orderId : orderIds) {
            jdbcTemplate.update("DELETE FROM demo_payment WHERE order_id = ?", orderId);
            jdbcTemplate.update("DELETE FROM demo_order_item WHERE order_id = ?", orderId);
            jdbcTemplate.update("DELETE FROM demo_order WHERE id = ?", orderId);
        }
        for (Long userCouponId : userCouponIds) {
            jdbcTemplate.update("DELETE FROM demo_user_coupon WHERE id = ?", userCouponId);
        }
        for (Long productId : productIds) {
            jdbcTemplate.update("DELETE FROM demo_inventory WHERE product_id = ?", productId);
            jdbcTemplate.update("DELETE FROM demo_product WHERE id = ?", productId);
        }
        for (Long couponId : couponIds) {
            jdbcTemplate.update("DELETE FROM demo_coupon WHERE id = ?", couponId);
        }
        for (Long userId : userIds) {
            jdbcTemplate.update("DELETE FROM demo_user WHERE id = ?", userId);
        }
        orderIds.clear();
        userCouponIds.clear();
        couponIds.clear();
        productIds.clear();
        userIds.clear();
    }

    @Test
    void createsOrderItemsSnapshotsInventoryCouponAndPendingPayment() {
        Long userId = insertUser();
        Long firstProductId = insertProduct("First product", "10.00", 5L);
        Long secondProductId = insertProduct("Second product", "20.00", 3L);
        Long couponId = insertCoupon("30.00", "5.00");
        Long userCouponId = insertUserCoupon(userId, couponId);

        CreateOrderRequest request = request(userId, couponId,
                item(secondProductId, 1), item(firstProductId, 2));
        OrderDetailVO created = createOrderApplicationService.createOrder(request);
        orderIds.add(created.getId());

        assertThat(created.getStatus()).isEqualTo(OrderStatus.PENDING_PAYMENT.name());
        assertThat(created.getOriginalAmount()).isEqualByComparingTo("40.00");
        assertThat(created.getDiscountAmount()).isEqualByComparingTo("5.00");
        assertThat(created.getPayableAmount()).isEqualByComparingTo("35.00");
        assertThat(created.getItems()).extracting("productName")
                .containsExactly("First product", "Second product");
        assertThat(created.getItems()).extracting("unitPrice")
                .containsExactly(new BigDecimal("10.00"), new BigDecimal("20.00"));

        assertThat(stock(firstProductId)).isEqualTo(3L);
        assertThat(stock(secondProductId)).isEqualTo(2L);
        assertThat(jdbcTemplate.queryForObject(
                "SELECT status FROM demo_user_coupon WHERE id = ?", String.class, userCouponId))
                .isEqualTo("USED");
        assertThat(jdbcTemplate.queryForObject(
                "SELECT COUNT(*) FROM demo_order_item WHERE order_id = ?", Long.class, created.getId()))
                .isEqualTo(2L);
        assertThat(jdbcTemplate.queryForObject(
                "SELECT status FROM demo_payment WHERE order_id = ?", String.class, created.getId()))
                .isEqualTo("PENDING");
        assertThat(jdbcTemplate.queryForObject(
                "SELECT payment_amount FROM demo_payment WHERE order_id = ?", BigDecimal.class, created.getId()))
                .isEqualByComparingTo("35.00");
        assertThat(jdbcTemplate.queryForObject(
                "SELECT user_coupon_id FROM demo_order WHERE id = ?", Long.class, created.getId()))
                .isEqualTo(userCouponId);
    }

    @Test
    void createsOrderWithoutCoupon() {
        Long userId = insertUser();
        Long productId = insertProduct("No coupon product", "12.00", 5L);

        OrderDetailVO created = createOrderApplicationService.createOrder(
                request(userId, null, item(productId, 2)));
        orderIds.add(created.getId());

        assertThat(created.getOriginalAmount()).isEqualByComparingTo("24.00");
        assertThat(created.getDiscountAmount()).isEqualByComparingTo("0.00");
        assertThat(created.getPayableAmount()).isEqualByComparingTo("24.00");
        assertThat(stock(productId)).isEqualTo(3L);
    }

    @Test
    void rejectsMissingProduct() {
        Long userId = insertUser();
        long missingProductId = 9_999_999_999L;

        assertThatThrownBy(() -> createOrderApplicationService.createOrder(
                request(userId, null, item(missingProductId, 1))))
                .isInstanceOf(ResourceNotFoundException.class)
                .hasMessage("product id " + missingProductId + " not found");

        assertNoOrderDataForUser(userId);
    }

    @Test
    void rejectsOffSaleProduct() {
        Long userId = insertUser();
        Long productId = insertProduct("Off sale product", "12.00", 5L);
        jdbcTemplate.update("UPDATE demo_product SET status = 'OFF_SALE' WHERE id = ?", productId);

        assertThatThrownBy(() -> createOrderApplicationService.createOrder(
                request(userId, null, item(productId, 1))))
                .isInstanceOf(DemoOrderBusinessException.class)
                .hasMessage("product id " + productId + " is not on sale");

        assertThat(stock(productId)).isEqualTo(5L);
        assertNoOrderDataForUser(userId);
    }

    @Test
    void rejectsDuplicateProductId() {
        Long userId = insertUser();
        Long productId = insertProduct("Duplicate product", "12.00", 5L);

        assertThatThrownBy(() -> createOrderApplicationService.createOrder(
                request(userId, null, item(productId, 1), item(productId, 2))))
                .isInstanceOf(DemoOrderBusinessException.class)
                .hasMessage("duplicate productId: " + productId);

        assertThat(stock(productId)).isEqualTo(5L);
        assertNoOrderDataForUser(userId);
    }

    @Test
    void deductsMultipleProductsInStableProductIdOrder() {
        Long userId = insertUser();
        Long firstProductId = insertProduct("First sorted product", "10.00", 5L);
        Long secondProductId = insertProduct("Second sorted product", "20.00", 5L);
        RecordingInventoryApplicationService recordingInventory =
                new RecordingInventoryApplicationService(inventoryMapper);
        CreateOrderApplicationService recordingService = new CreateOrderApplicationService(
                userMapper, productMapper, recordingInventory, couponMapper,
                userCouponMapper, orderMapper, orderItemMapper, paymentMapper);

        OrderDetailVO created = inTransactionResult(() -> recordingService.createOrder(
                request(userId, null, item(secondProductId, 1), item(firstProductId, 1))));
        orderIds.add(created.getId());

        assertThat(recordingInventory.productIds).containsExactly(firstProductId, secondProductId);
        assertThat(created.getItems()).extracting("productId")
                .containsExactly(firstProductId, secondProductId);
    }

    @Test
    void laterInventoryFailureRollsBackEarlierDeductionAndAllOrderWrites() {
        Long userId = insertUser();
        Long firstProductId = insertProduct("First product", "10.00", 5L);
        Long secondProductId = insertProduct("Second product", "20.00", 1L);

        assertThatThrownBy(() -> createOrderApplicationService.createOrder(request(userId, null,
                item(secondProductId, 2), item(firstProductId, 2))))
                .isInstanceOf(DemoOrderBusinessException.class)
                .hasMessage("insufficient inventory for product id " + secondProductId);

        assertThat(stock(firstProductId)).isEqualTo(5L);
        assertThat(stock(secondProductId)).isEqualTo(1L);
        assertNoOrderDataForUser(userId);
    }

    @Test
    void couponConditionalConsumeFailureRollsBackInventoryAndOrderWrites() {
        Long userId = insertUser();
        Long productId = insertProduct("Coupon product", "50.00", 5L);
        Long couponId = insertCoupon("10.00", "5.00");
        Long userCouponId = insertUserCoupon(userId, couponId);
        assertThatThrownBy(() -> failingCouponService.createOrder(
                request(userId, couponId, item(productId, 1))))
                .isInstanceOf(DemoOrderBusinessException.class)
                .hasMessage("user coupon is no longer available");

        assertThat(stock(productId)).isEqualTo(5L);
        assertThat(userCouponStatus(userCouponId)).isEqualTo("AVAILABLE");
        assertNoOrderDataForUser(userId);
    }

    @Test
    void orderItemInsertFailureRollsBackInventoryAndOrder() {
        Long userId = insertUser();
        Long productId = insertProduct("Item failure product", "10.00", 5L);
        Long couponId = insertCoupon("5.00", "1.00");
        Long userCouponId = insertUserCoupon(userId, couponId);
        assertThatThrownBy(() -> failingOrderItemService.createOrder(
                request(userId, couponId, item(productId, 1))))
                .isInstanceOf(IllegalStateException.class)
                .hasMessage("forced order item failure");

        assertThat(failingOrderItemService.wasOrderItemInserted()).isTrue();
        assertThat(stock(productId)).isEqualTo(5L);
        assertThat(userCouponStatus(userCouponId)).isEqualTo("AVAILABLE");
        assertNoOrderDataForUser(userId);
    }

    @Test
    void paymentInsertFailureRollsBackInventoryOrderAndItems() {
        Long userId = insertUser();
        Long productId = insertProduct("Payment failure product", "10.00", 5L);
        Long couponId = insertCoupon("5.00", "1.00");
        Long userCouponId = insertUserCoupon(userId, couponId);
        assertThatThrownBy(() -> failingPaymentService.createOrder(
                request(userId, couponId, item(productId, 1))))
                .isInstanceOf(IllegalStateException.class)
                .hasMessage("forced payment failure");

        assertThat(failingPaymentService.wasPaymentInserted()).isTrue();
        assertThat(stock(productId)).isEqualTo(5L);
        assertThat(userCouponStatus(userCouponId)).isEqualTo("AVAILABLE");
        assertNoOrderDataForUser(userId);
    }

    private CreateOrderRequest request(Long userId, Long couponId,
                                       CreateOrderItemRequest... items) {
        CreateOrderRequest request = new CreateOrderRequest();
        request.setUserId(userId);
        request.setCouponId(couponId);
        request.setItems(List.of(items));
        return request;
    }

    private CreateOrderItemRequest item(Long productId, int quantity) {
        CreateOrderItemRequest item = new CreateOrderItemRequest();
        item.setProductId(productId);
        item.setQuantity(quantity);
        return item;
    }

    private Long insertUser() {
        String userNo = "create_order_user_" + UUID.randomUUID();
        LocalDateTime now = LocalDateTime.now();
        jdbcTemplate.update(
                "INSERT INTO demo_user (user_no, user_name, status, created_at, updated_at) "
                        + "VALUES (?, 'Create order test user', 'ENABLED', ?, ?)",
                userNo, now, now);
        Long id = jdbcTemplate.queryForObject(
                "SELECT id FROM demo_user WHERE user_no = ?", Long.class, userNo);
        userIds.add(id);
        return id;
    }

    private Long insertProduct(String name, String price, long stock) {
        String productNo = "create_order_product_" + UUID.randomUUID();
        LocalDateTime now = LocalDateTime.now();
        jdbcTemplate.update(
                "INSERT INTO demo_product (product_no, product_name, sale_price, status, version, "
                        + "deleted, created_at, updated_at) VALUES (?, ?, ?, 'ON_SALE', 0, 0, ?, ?)",
                productNo, name, new BigDecimal(price), now, now);
        Long productId = jdbcTemplate.queryForObject(
                "SELECT id FROM demo_product WHERE product_no = ?", Long.class, productNo);
        jdbcTemplate.update(
                "INSERT INTO demo_inventory (product_id, available_stock, created_at, updated_at) "
                        + "VALUES (?, ?, ?, ?)", productId, stock, now, now);
        productIds.add(productId);
        return productId;
    }

    private Long insertCoupon(String threshold, String discount) {
        String couponNo = "create_order_coupon_" + UUID.randomUUID();
        LocalDateTime now = LocalDateTime.now();
        jdbcTemplate.update(
                "INSERT INTO demo_coupon (coupon_no, coupon_name, threshold_amount, discount_amount, "
                        + "valid_from, valid_until, status, deleted, created_at, updated_at) "
                        + "VALUES (?, 'Create order coupon', ?, ?, ?, ?, 'ACTIVE', 0, ?, ?)",
                couponNo, new BigDecimal(threshold), new BigDecimal(discount),
                now.minusDays(1), now.plusDays(1), now, now);
        Long couponId = jdbcTemplate.queryForObject(
                "SELECT id FROM demo_coupon WHERE coupon_no = ?", Long.class, couponNo);
        couponIds.add(couponId);
        return couponId;
    }

    private Long insertUserCoupon(Long userId, Long couponId) {
        String userCouponNo = "create_order_user_coupon_" + UUID.randomUUID();
        LocalDateTime now = LocalDateTime.now();
        jdbcTemplate.update(
                "INSERT INTO demo_user_coupon (user_coupon_no, user_id, coupon_id, status, "
                        + "received_at, created_at, updated_at) VALUES (?, ?, ?, 'AVAILABLE', ?, ?, ?)",
                userCouponNo, userId, couponId, now, now, now);
        Long userCouponId = jdbcTemplate.queryForObject(
                "SELECT id FROM demo_user_coupon WHERE user_coupon_no = ?", Long.class,
                userCouponNo);
        userCouponIds.add(userCouponId);
        return userCouponId;
    }

    private long stock(Long productId) {
        return jdbcTemplate.queryForObject(
                "SELECT available_stock FROM demo_inventory WHERE product_id = ?", Long.class, productId);
    }

    private String userCouponStatus(Long userCouponId) {
        return jdbcTemplate.queryForObject(
                "SELECT status FROM demo_user_coupon WHERE id = ?", String.class, userCouponId);
    }

    private void inTransaction(Runnable operation) {
        new TransactionTemplate(transactionManager).executeWithoutResult(status -> operation.run());
    }

    private <T> T inTransactionResult(java.util.function.Supplier<T> operation) {
        return new TransactionTemplate(transactionManager).execute(status -> operation.get());
    }

    private void assertNoOrderDataForUser(Long userId) {
        assertThat(jdbcTemplate.queryForObject(
                "SELECT COUNT(*) FROM demo_order WHERE user_id = ?", Long.class, userId)).isZero();
        assertThat(jdbcTemplate.queryForObject(
                "SELECT COUNT(*) FROM demo_order_item oi JOIN demo_order o ON o.id = oi.order_id "
                        + "WHERE o.user_id = ?", Long.class, userId)).isZero();
        assertThat(jdbcTemplate.queryForObject(
                "SELECT COUNT(*) FROM demo_payment p JOIN demo_order o ON o.id = p.order_id "
                        + "WHERE o.user_id = ?", Long.class, userId)).isZero();
    }

    private enum FailureMode { COUPON, ORDER_ITEM, PAYMENT }

    static class FailingCreateOrderApplicationService
            extends CreateOrderApplicationService {

        private final FailureMode failureMode;
        private boolean orderItemInserted;
        private boolean paymentInserted;

        FailingCreateOrderApplicationService(
                UserMapper userMapper,
                ProductMapper productMapper,
                InventoryApplicationService inventoryApplicationService,
                CouponMapper couponMapper,
                UserCouponMapper userCouponMapper,
                OrderMapper orderMapper,
                OrderItemMapper orderItemMapper,
                PaymentMapper paymentMapper,
                FailureMode failureMode
        ) {
            super(userMapper, productMapper, inventoryApplicationService, couponMapper,
                    userCouponMapper, orderMapper, orderItemMapper, paymentMapper);
            this.failureMode = failureMode;
        }

        @Override
        protected int consumeUserCoupon(Long userCouponId, Long userId) {
            if (failureMode == FailureMode.COUPON) {
                return 0;
            }
            return super.consumeUserCoupon(userCouponId, userId);
        }

        @Override
        protected int insertOrderItem(OrderItemEntity orderItem) {
            if (failureMode == FailureMode.ORDER_ITEM) {
                orderItemInserted = super.insertOrderItem(orderItem) == 1;
                throw new IllegalStateException("forced order item failure");
            }
            return super.insertOrderItem(orderItem);
        }

        @Override
        protected int insertPayment(PaymentEntity payment) {
            if (failureMode == FailureMode.PAYMENT) {
                paymentInserted = super.insertPayment(payment) == 1;
                throw new IllegalStateException("forced payment failure");
            }
            return super.insertPayment(payment);
        }

        boolean wasOrderItemInserted() {
            return orderItemInserted;
        }

        boolean wasPaymentInserted() {
            return paymentInserted;
        }
    }

    private static final class RecordingInventoryApplicationService
            extends InventoryApplicationService {

        private final List<Long> productIds = new ArrayList<>();

        private RecordingInventoryApplicationService(InventoryMapper inventoryMapper) {
            super(inventoryMapper);
        }

        @Override
        public void deductBatch(List<InventoryDeductCommand> commands) {
            productIds.addAll(commands.stream().map(InventoryDeductCommand::getProductId).toList());
            super.deductBatch(commands);
        }
    }

    @TestConfiguration(proxyBeanMethods = false)
    static class CreateOrderFailureTestConfiguration {

        @Bean("failingCouponService")
        FailingCreateOrderApplicationService failingCouponService(
                UserMapper userMapper,
                ProductMapper productMapper,
                InventoryApplicationService inventoryApplicationService,
                CouponMapper couponMapper,
                UserCouponMapper userCouponMapper,
                OrderMapper orderMapper,
                OrderItemMapper orderItemMapper,
                PaymentMapper paymentMapper
        ) {
            return service(userMapper, productMapper, inventoryApplicationService,
                    couponMapper, userCouponMapper, orderMapper, orderItemMapper,
                    paymentMapper, FailureMode.COUPON);
        }

        @Bean("failingOrderItemService")
        FailingCreateOrderApplicationService failingOrderItemService(
                UserMapper userMapper,
                ProductMapper productMapper,
                InventoryApplicationService inventoryApplicationService,
                CouponMapper couponMapper,
                UserCouponMapper userCouponMapper,
                OrderMapper orderMapper,
                OrderItemMapper orderItemMapper,
                PaymentMapper paymentMapper
        ) {
            return service(userMapper, productMapper, inventoryApplicationService,
                    couponMapper, userCouponMapper, orderMapper, orderItemMapper,
                    paymentMapper, FailureMode.ORDER_ITEM);
        }

        @Bean("failingPaymentService")
        FailingCreateOrderApplicationService failingPaymentService(
                UserMapper userMapper,
                ProductMapper productMapper,
                InventoryApplicationService inventoryApplicationService,
                CouponMapper couponMapper,
                UserCouponMapper userCouponMapper,
                OrderMapper orderMapper,
                OrderItemMapper orderItemMapper,
                PaymentMapper paymentMapper
        ) {
            return service(userMapper, productMapper, inventoryApplicationService,
                    couponMapper, userCouponMapper, orderMapper, orderItemMapper,
                    paymentMapper, FailureMode.PAYMENT);
        }

        private static FailingCreateOrderApplicationService service(
                UserMapper userMapper,
                ProductMapper productMapper,
                InventoryApplicationService inventoryApplicationService,
                CouponMapper couponMapper,
                UserCouponMapper userCouponMapper,
                OrderMapper orderMapper,
                OrderItemMapper orderItemMapper,
                PaymentMapper paymentMapper,
                FailureMode failureMode
        ) {
            return new FailingCreateOrderApplicationService(
                    userMapper, productMapper, inventoryApplicationService, couponMapper,
                    userCouponMapper, orderMapper, orderItemMapper, paymentMapper,
                    failureMode);
        }
    }
}
