package com.apiops.demo.order.inventory.application;

import com.apiops.demo.order.common.exception.DemoOrderBusinessException;
import com.apiops.demo.order.common.exception.DemoOrderErrorCode;
import com.apiops.demo.order.common.exception.ResourceNotFoundException;
import com.apiops.demo.order.inventory.entity.InventoryEntity;
import com.apiops.demo.order.inventory.mapper.InventoryMapper;
import com.baomidou.mybatisplus.core.toolkit.Wrappers;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.util.ArrayList;
import java.util.Comparator;
import java.util.HashSet;
import java.util.List;
import java.util.Set;

@Service
public class InventoryApplicationService {

    private final InventoryMapper inventoryMapper;

    public InventoryApplicationService(InventoryMapper inventoryMapper) {
        this.inventoryMapper = inventoryMapper;
    }

    public void deduct(Long productId, Long quantity) {
        validatePositive("productId", productId);
        validatePositive("quantity", quantity);

        InventoryEntity inventory = inventoryMapper.selectOne(
                Wrappers.<InventoryEntity>lambdaQuery()
                        .eq(InventoryEntity::getProductId, productId));
        if (inventory == null) {
            throw new ResourceNotFoundException(
                    "inventory for product id " + productId + " not found");
        }

        int affectedRows = inventoryMapper.deductIfEnough(productId, quantity);
        if (affectedRows == 1) {
            return;
        }
        if (affectedRows == 0) {
            throw new DemoOrderBusinessException(
                    DemoOrderErrorCode.BUSINESS_CONFLICT,
                    "insufficient inventory for product id " + productId);
        }
        throw new IllegalStateException(
                "unexpected inventory deduction row count: " + affectedRows);
    }

    @Transactional
    public void deductBatch(List<InventoryDeductCommand> commands) {
        validateBatchCommands(commands);

        List<InventoryDeductCommand> sortedCommands = new ArrayList<>(commands);
        sortedCommands.sort(Comparator.comparing(InventoryDeductCommand::getProductId));
        for (InventoryDeductCommand command : sortedCommands) {
            deduct(command.getProductId(), command.getQuantity());
        }
    }

    private static void validateBatchCommands(List<InventoryDeductCommand> commands) {
        if (commands == null || commands.isEmpty()) {
            throw new IllegalArgumentException("commands must not be null or empty");
        }

        Set<Long> productIds = new HashSet<>();
        for (InventoryDeductCommand command : commands) {
            if (command == null) {
                throw new IllegalArgumentException("command must not be null");
            }
            validatePositive("productId", command.getProductId());
            validatePositive("quantity", command.getQuantity());
            if (!productIds.add(command.getProductId())) {
                throw new IllegalArgumentException(
                        "duplicate productId: " + command.getProductId());
            }
        }
    }

    private static void validatePositive(String name, Long value) {
        if (value == null || value <= 0) {
            throw new IllegalArgumentException(name + " must be greater than 0");
        }
    }
}
