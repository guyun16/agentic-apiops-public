package com.apiops.demo.order.integration;

import com.apiops.demo.order.common.exception.DemoOrderBusinessException;
import com.apiops.demo.order.inventory.application.InventoryApplicationService;
import com.apiops.demo.order.inventory.application.InventoryDeductCommand;
import com.apiops.demo.order.inventory.entity.InventoryEntity;
import com.apiops.demo.order.inventory.mapper.InventoryMapper;
import com.apiops.demo.order.product.entity.ProductEntity;
import com.apiops.demo.order.product.mapper.ProductMapper;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;
import org.mockito.InOrder;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.mock.mockito.SpyBean;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.test.context.ActiveProfiles;

import java.math.BigDecimal;
import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.List;
import java.util.UUID;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.Mockito.inOrder;

@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.NONE)
@ActiveProfiles("local")
@EnabledIfEnvironmentVariable(named = "APIOPS_ORDER_DB_URL", matches = ".+")
class InventoryBatchTransactionMySqlTest {

    @Autowired
    private InventoryApplicationService inventoryApplicationService;

    @Autowired
    private InventoryMapper inventoryMapper;

    @Autowired
    private ProductMapper productMapper;

    @SpyBean
    private InventoryMapper inventoryMapperSpy;

    @Autowired
    private JdbcTemplate jdbcTemplate;

    private final List<Long> productIds = new ArrayList<>();

    @AfterEach
    void cleanup() {
        for (Long productId : productIds) {
            jdbcTemplate.update("DELETE FROM demo_inventory WHERE product_id = ?", productId);
            jdbcTemplate.update("DELETE FROM demo_product WHERE id = ?", productId);
        }
        productIds.clear();
    }

    @Test
    void rollsBackEarlierDeductionWhenLaterProductIsInsufficient() {
        InventoryEntity first = insertInventory(10L);
        InventoryEntity second = insertInventory(1L);
        long firstBefore = stock(first.getProductId());
        long secondBefore = stock(second.getProductId());

        List<InventoryDeductCommand> commands = List.of(
                new InventoryDeductCommand(second.getProductId(), 2L),
                new InventoryDeductCommand(first.getProductId(), 3L));

        assertThatThrownBy(() -> inventoryApplicationService.deductBatch(commands))
                .isInstanceOf(DemoOrderBusinessException.class)
                .hasMessage("insufficient inventory for product id " + second.getProductId());

        InOrder order = inOrder(inventoryMapperSpy);
        order.verify(inventoryMapperSpy)
                .deductIfEnough(first.getProductId(), 3L);
        order.verify(inventoryMapperSpy)
                .deductIfEnough(second.getProductId(), 2L);

        assertThat(stock(first.getProductId())).isEqualTo(firstBefore);
        assertThat(stock(second.getProductId())).isEqualTo(secondBefore);
    }

    private InventoryEntity insertInventory(long availableStock) {
        ProductEntity product = new ProductEntity();
        LocalDateTime now = LocalDateTime.now().withNano(0);
        product.setProductNo("test_inventory_batch_" + UUID.randomUUID());
        product.setProductName("Inventory batch transaction test product");
        product.setSalePrice(BigDecimal.ONE);
        product.setStatus("ON_SALE");
        product.setCreatedAt(now);
        product.setUpdatedAt(now);
        assertThat(productMapper.insert(product)).isEqualTo(1);
        productIds.add(product.getId());

        InventoryEntity inventory = new InventoryEntity();
        inventory.setProductId(product.getId());
        inventory.setAvailableStock(availableStock);
        inventory.setCreatedAt(now);
        inventory.setUpdatedAt(now);
        assertThat(inventoryMapper.insert(inventory)).isEqualTo(1);
        return inventory;
    }

    private long stock(Long productId) {
        return jdbcTemplate.queryForObject(
                "SELECT available_stock FROM demo_inventory WHERE product_id = ?",
                Long.class, productId);
    }
}
