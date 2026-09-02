package com.apiops.demo.order.persistence;

import com.apiops.demo.order.inventory.entity.InventoryEntity;
import com.apiops.demo.order.inventory.mapper.InventoryMapper;
import com.apiops.demo.order.product.entity.ProductEntity;
import com.apiops.demo.order.product.mapper.ProductMapper;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.test.annotation.Rollback;
import org.springframework.test.context.ActiveProfiles;
import org.springframework.transaction.annotation.Transactional;

import java.math.BigDecimal;
import java.time.LocalDateTime;
import java.util.UUID;

import static org.assertj.core.api.Assertions.assertThat;

@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.NONE)
@ActiveProfiles("local")
@EnabledIfEnvironmentVariable(named = "APIOPS_ORDER_DB_URL", matches = ".+")
@Transactional
@Rollback
class InventoryMapperMySqlTest {

    @Autowired
    private InventoryMapper inventoryMapper;

    @Autowired
    private ProductMapper productMapper;

    @Test
    void deductsRequestedQuantityWhenStockIsEnough() {
        InventoryEntity inventory = insertInventory(10L);

        int affectedRows = inventoryMapper.deductIfEnough(inventory.getProductId(), 4L);

        assertThat(affectedRows).isEqualTo(1);
        assertThat(inventoryMapper.selectById(inventory.getId()).getAvailableStock()).isEqualTo(6L);
    }

    @Test
    void deductsToZeroWhenQuantityExactlyMatchesStock() {
        InventoryEntity inventory = insertInventory(5L);

        int affectedRows = inventoryMapper.deductIfEnough(inventory.getProductId(), 5L);

        assertThat(affectedRows).isEqualTo(1);
        assertThat(inventoryMapper.selectById(inventory.getId()).getAvailableStock()).isZero();
    }

    @Test
    void updatesUpdatedAtWhenDeductionSucceeds() {
        InventoryEntity inventory = insertInventory(10L);
        LocalDateTime beforeUpdate = inventoryMapper.selectById(inventory.getId()).getUpdatedAt();

        int affectedRows = inventoryMapper.deductIfEnough(inventory.getProductId(), 1L);

        assertThat(affectedRows).isEqualTo(1);
        assertThat(inventoryMapper.selectById(inventory.getId()).getUpdatedAt())
                .isAfter(beforeUpdate);
    }

    @Test
    void leavesStockUnchangedWhenStockIsInsufficient() {
        InventoryEntity inventory = insertInventory(3L);

        int affectedRows = inventoryMapper.deductIfEnough(inventory.getProductId(), 4L);

        assertThat(affectedRows).isZero();
        assertThat(inventoryMapper.selectById(inventory.getId()).getAvailableStock()).isEqualTo(3L);
    }

    @Test
    void returnsZeroWhenInventoryRecordDoesNotExist() {
        ProductEntity product = insertProduct();

        int affectedRows = inventoryMapper.deductIfEnough(product.getId(), 1L);

        assertThat(affectedRows).isZero();
    }

    private InventoryEntity insertInventory(long availableStock) {
        ProductEntity product = insertProduct();
        LocalDateTime now = LocalDateTime.of(2000, 1, 1, 0, 0);
        InventoryEntity inventory = new InventoryEntity();
        inventory.setProductId(product.getId());
        inventory.setAvailableStock(availableStock);
        inventory.setCreatedAt(now);
        inventory.setUpdatedAt(now);
        assertThat(inventoryMapper.insert(inventory)).isEqualTo(1);
        assertThat(inventory.getId()).isNotNull();
        return inventory;
    }

    private ProductEntity insertProduct() {
        LocalDateTime now = LocalDateTime.now().withNano(0);
        ProductEntity product = new ProductEntity();
        product.setProductNo("test_inventory_" + UUID.randomUUID());
        product.setProductName("Inventory mapper test product");
        product.setSalePrice(BigDecimal.ONE);
        product.setStatus("ON_SALE");
        product.setCreatedAt(now);
        product.setUpdatedAt(now);
        assertThat(productMapper.insert(product)).isEqualTo(1);
        assertThat(product.getId()).isNotNull();
        return product;
    }
}
