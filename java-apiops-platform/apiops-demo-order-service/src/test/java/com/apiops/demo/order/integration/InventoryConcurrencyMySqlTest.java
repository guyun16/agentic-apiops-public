package com.apiops.demo.order.integration;

import com.apiops.demo.order.common.exception.DemoOrderBusinessException;
import com.apiops.demo.order.common.exception.DemoOrderErrorCode;
import com.apiops.demo.order.inventory.application.InventoryApplicationService;
import com.apiops.demo.order.inventory.entity.InventoryEntity;
import com.apiops.demo.order.inventory.mapper.InventoryMapper;
import com.apiops.demo.order.product.entity.ProductEntity;
import com.apiops.demo.order.product.mapper.ProductMapper;
import com.zaxxer.hikari.HikariDataSource;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.test.context.ActiveProfiles;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.TransactionDefinition;
import org.springframework.transaction.support.TransactionTemplate;

import javax.sql.DataSource;
import java.math.BigDecimal;
import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.List;
import java.util.UUID;
import java.util.concurrent.Callable;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.ExecutionException;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.TimeoutException;
import java.util.concurrent.atomic.AtomicInteger;

import static org.assertj.core.api.Assertions.assertThat;

@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.NONE)
@ActiveProfiles("local")
@EnabledIfEnvironmentVariable(named = "APIOPS_ORDER_DB_URL", matches = ".+")
class InventoryConcurrencyMySqlTest {

    private static final int INITIAL_STOCK = 5;
    private static final int REQUEST_COUNT = 10;
    private static final long DEDUCT_QUANTITY = 1L;
    private static final long FUTURE_TIMEOUT_SECONDS = 60L;

    @Autowired
    private InventoryApplicationService inventoryApplicationService;

    @Autowired
    private InventoryMapper inventoryMapper;

    @Autowired
    private ProductMapper productMapper;

    @Autowired
    private JdbcTemplate jdbcTemplate;

    @Autowired
    private DataSource dataSource;

    @Autowired
    private PlatformTransactionManager transactionManager;

    private Long productId;

    @AfterEach
    void cleanup() {
        if (productId != null) {
            jdbcTemplate.update("DELETE FROM demo_inventory WHERE product_id = ?", productId);
            jdbcTemplate.update("DELETE FROM demo_product WHERE id = ?", productId);
            productId = null;
        }
    }

    @Test
    void competingDeductionsConsumeExactlyAvailableStock() throws Exception {
        createInventory(INITIAL_STOCK);
        assertThat(dataSource).isInstanceOf(HikariDataSource.class);
        int maximumPoolSize = ((HikariDataSource) dataSource).getMaximumPoolSize();
        System.out.println("Hikari maximumPoolSize = " + maximumPoolSize);
        assertThat(maximumPoolSize).isGreaterThanOrEqualTo(2);

        TransactionTemplate transactionTemplate = new TransactionTemplate(transactionManager);
        transactionTemplate.setPropagationBehavior(
                TransactionDefinition.PROPAGATION_REQUIRES_NEW);

        AtomicInteger successCount = new AtomicInteger();
        AtomicInteger insufficientCount = new AtomicInteger();
        CountDownLatch readyLatch = new CountDownLatch(REQUEST_COUNT);
        CountDownLatch startLatch = new CountDownLatch(1);
        ExecutorService executor = Executors.newFixedThreadPool(REQUEST_COUNT);
        List<Future<Void>> futures = new ArrayList<>(REQUEST_COUNT);

        try {
            for (int taskIndex = 0; taskIndex < REQUEST_COUNT; taskIndex++) {
                futures.add(executor.submit(task(
                        transactionTemplate,
                        readyLatch,
                        startLatch,
                        successCount,
                        insufficientCount)));
            }

            assertThat(readyLatch.await(FUTURE_TIMEOUT_SECONDS, TimeUnit.SECONDS))
                    .as("all deduction tasks should report ready")
                    .isTrue();
            startLatch.countDown();
            assertFutureResults(futures);
        } finally {
            executor.shutdownNow();
            assertThat(executor.awaitTermination(FUTURE_TIMEOUT_SECONDS, TimeUnit.SECONDS))
                    .as("deduction executor should terminate")
                    .isTrue();
        }

        long finalStock = stock();
        System.out.println("successCount = " + successCount.get());
        System.out.println("insufficientCount = " + insufficientCount.get());
        System.out.println("final available_stock = " + finalStock);

        assertThat(successCount.get()).isEqualTo(5);
        assertThat(insufficientCount.get()).isEqualTo(5);
        assertThat(finalStock).isZero();
        assertThat((long) successCount.get() * DEDUCT_QUANTITY + finalStock)
                .isEqualTo(INITIAL_STOCK);
    }

    private Callable<Void> task(
            TransactionTemplate transactionTemplate,
            CountDownLatch readyLatch,
            CountDownLatch startLatch,
            AtomicInteger successCount,
            AtomicInteger insufficientCount) {
        return () -> {
            readyLatch.countDown();
            startLatch.await();
            try {
                transactionTemplate.executeWithoutResult(status ->
                        inventoryApplicationService.deduct(productId, DEDUCT_QUANTITY));
                successCount.incrementAndGet();
            } catch (DemoOrderBusinessException exception) {
                if (!isExpectedInsufficient(exception)) {
                    throw exception;
                }
                insufficientCount.incrementAndGet();
            }
            return null;
        };
    }

    private boolean isExpectedInsufficient(DemoOrderBusinessException exception) {
        return exception.getErrorCode() == DemoOrderErrorCode.BUSINESS_CONFLICT
                && ("insufficient inventory for product id " + productId)
                .equals(exception.getMessage());
    }

    private void assertFutureResults(List<Future<Void>> futures) {
        List<Throwable> failures = new ArrayList<>();
        for (Future<Void> future : futures) {
            try {
                future.get(FUTURE_TIMEOUT_SECONDS, TimeUnit.SECONDS);
            } catch (InterruptedException exception) {
                Thread.currentThread().interrupt();
                failures.add(exception);
            } catch (ExecutionException exception) {
                failures.add(exception.getCause());
            } catch (TimeoutException exception) {
                failures.add(exception);
            }
        }
        if (!failures.isEmpty()) {
            throw new AssertionError("one or more deduction tasks failed", failures.get(0));
        }
    }

    private void createInventory(long availableStock) {
        LocalDateTime now = LocalDateTime.now().withNano(0);
        ProductEntity product = new ProductEntity();
        product.setProductNo("test_inventory_concurrency_" + UUID.randomUUID());
        product.setProductName("Inventory concurrency test product");
        product.setSalePrice(BigDecimal.ONE);
        product.setStatus("ON_SALE");
        product.setCreatedAt(now);
        product.setUpdatedAt(now);
        assertThat(productMapper.insert(product)).isEqualTo(1);
        productId = product.getId();

        InventoryEntity inventory = new InventoryEntity();
        inventory.setProductId(productId);
        inventory.setAvailableStock(availableStock);
        inventory.setCreatedAt(now);
        inventory.setUpdatedAt(now);
        assertThat(inventoryMapper.insert(inventory)).isEqualTo(1);
    }

    private long stock() {
        return jdbcTemplate.queryForObject(
                "SELECT available_stock FROM demo_inventory WHERE product_id = ?",
                Long.class, productId);
    }
}
