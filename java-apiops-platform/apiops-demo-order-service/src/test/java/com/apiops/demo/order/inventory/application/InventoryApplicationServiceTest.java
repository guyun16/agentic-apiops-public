package com.apiops.demo.order.inventory.application;

import com.apiops.demo.order.common.exception.DemoOrderBusinessException;
import com.apiops.demo.order.common.exception.ResourceNotFoundException;
import com.apiops.demo.order.inventory.entity.InventoryEntity;
import com.apiops.demo.order.inventory.mapper.InventoryMapper;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.NullSource;
import org.junit.jupiter.params.provider.ValueSource;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

import java.util.ArrayList;
import java.util.Collections;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.inOrder;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.verifyNoMoreInteractions;
import static org.mockito.Mockito.when;
import org.mockito.InOrder;

@ExtendWith(MockitoExtension.class)
class InventoryApplicationServiceTest {

    @Mock
    private InventoryMapper inventoryMapper;

    @ParameterizedTest
    @NullSource
    @ValueSource(longs = {0L, -1L})
    void rejectsInvalidProductIdWithoutWriting(Long productId) {
        assertThatThrownBy(() -> service().deduct(productId, 1L))
                .isInstanceOf(IllegalArgumentException.class)
                .hasMessage("productId must be greater than 0");

        verifyNoInteractions(inventoryMapper);
    }

    @ParameterizedTest
    @NullSource
    @ValueSource(longs = {0L, -1L})
    void rejectsInvalidQuantityWithoutWriting(Long quantity) {
        assertThatThrownBy(() -> service().deduct(10L, quantity))
                .isInstanceOf(IllegalArgumentException.class)
                .hasMessage("quantity must be greater than 0");

        verifyNoInteractions(inventoryMapper);
    }

    @Test
    void missingInventoryThrowsNotFoundWithoutDeducting() {
        when(inventoryMapper.selectOne(any())).thenReturn(null);

        assertThatThrownBy(() -> service().deduct(10L, 2L))
                .isInstanceOf(ResourceNotFoundException.class)
                .hasMessage("inventory for product id 10 not found");

        verify(inventoryMapper).selectOne(any());
        verifyNoMoreInteractions(inventoryMapper);
    }

    @Test
    void successfulDeductionPassesExactArguments() {
        when(inventoryMapper.selectOne(any())).thenReturn(inventory(10L));
        when(inventoryMapper.deductIfEnough(10L, 2L)).thenReturn(1);

        service().deduct(10L, 2L);

        verify(inventoryMapper).selectOne(any());
        verify(inventoryMapper).deductIfEnough(10L, 2L);
        verifyNoMoreInteractions(inventoryMapper);
    }

    @Test
    void insufficientInventoryThrowsBusinessConflict() {
        when(inventoryMapper.selectOne(any())).thenReturn(inventory(1L));
        when(inventoryMapper.deductIfEnough(10L, 2L)).thenReturn(0);

        assertThatThrownBy(() -> service().deduct(10L, 2L))
                .isInstanceOf(DemoOrderBusinessException.class)
                .hasMessage("insufficient inventory for product id 10");

        verify(inventoryMapper).selectOne(any());
        verify(inventoryMapper).deductIfEnough(10L, 2L);
        verifyNoMoreInteractions(inventoryMapper);
    }

    @Test
    void batchDeductsInAscendingProductIdOrder() {
        when(inventoryMapper.selectOne(any()))
                .thenReturn(inventory(1L), inventory(2L));
        when(inventoryMapper.deductIfEnough(1L, 3L)).thenReturn(1);
        when(inventoryMapper.deductIfEnough(2L, 4L)).thenReturn(1);
        List<InventoryDeductCommand> commands = List.of(
                new InventoryDeductCommand(2L, 4L),
                new InventoryDeductCommand(1L, 3L));

        service().deductBatch(commands);

        InOrder order = inOrder(inventoryMapper);
        order.verify(inventoryMapper).selectOne(any());
        order.verify(inventoryMapper).deductIfEnough(1L, 3L);
        order.verify(inventoryMapper).selectOne(any());
        order.verify(inventoryMapper).deductIfEnough(2L, 4L);
        verifyNoMoreInteractions(inventoryMapper);
    }

    @Test
    void batchDoesNotModifyInputOrder() {
        when(inventoryMapper.selectOne(any()))
                .thenReturn(inventory(1L), inventory(2L));
        when(inventoryMapper.deductIfEnough(1L, 1L)).thenReturn(1);
        when(inventoryMapper.deductIfEnough(2L, 1L)).thenReturn(1);
        List<InventoryDeductCommand> commands = new ArrayList<>(List.of(
                new InventoryDeductCommand(2L, 1L),
                new InventoryDeductCommand(1L, 1L)));

        service().deductBatch(commands);

        assertThat(commands).extracting(InventoryDeductCommand::getProductId)
                .containsExactly(2L, 1L);
    }

    @Test
    void batchRejectsNullOrEmptyCommands() {
        assertThatThrownBy(() -> service().deductBatch(null))
                .isInstanceOf(IllegalArgumentException.class)
                .hasMessage("commands must not be null or empty");
        assertThatThrownBy(() -> service().deductBatch(List.of()))
                .isInstanceOf(IllegalArgumentException.class)
                .hasMessage("commands must not be null or empty");

        verifyNoInteractions(inventoryMapper);
    }

    @Test
    void batchRejectsNullCommand() {
        List<InventoryDeductCommand> commands = Collections.singletonList(null);
        assertThatThrownBy(() -> service().deductBatch(commands))
                .isInstanceOf(IllegalArgumentException.class)
                .hasMessage("command must not be null");

        verifyNoInteractions(inventoryMapper);
    }

    @ParameterizedTest
    @NullSource
    @ValueSource(longs = {0L, -1L})
    void batchValidatesInvalidQuantityBeforeAnyDeduction(Long quantity) {
        List<InventoryDeductCommand> commands = List.of(
                new InventoryDeductCommand(1L, 1L),
                new InventoryDeductCommand(2L, quantity));

        assertThatThrownBy(() -> service().deductBatch(commands))
                .isInstanceOf(IllegalArgumentException.class)
                .hasMessage("quantity must be greater than 0");

        verify(inventoryMapper, never()).deductIfEnough(any(), any());
        verifyNoInteractions(inventoryMapper);
    }

    @ParameterizedTest
    @NullSource
    @ValueSource(longs = {0L, -1L})
    void batchValidatesInvalidProductIdBeforeAnyDeduction(Long productId) {
        List<InventoryDeductCommand> commands = List.of(
                new InventoryDeductCommand(1L, 1L),
                new InventoryDeductCommand(productId, 1L));

        assertThatThrownBy(() -> service().deductBatch(commands))
                .isInstanceOf(IllegalArgumentException.class)
                .hasMessage("productId must be greater than 0");

        verify(inventoryMapper, never()).deductIfEnough(any(), any());
        verifyNoInteractions(inventoryMapper);
    }

    @Test
    void batchRejectsDuplicateProductIdWithoutWriting() {
        List<InventoryDeductCommand> commands = List.of(
                new InventoryDeductCommand(1L, 1L),
                new InventoryDeductCommand(1L, 2L));

        assertThatThrownBy(() -> service().deductBatch(commands))
                .isInstanceOf(IllegalArgumentException.class)
                .hasMessage("duplicate productId: 1");

        verifyNoInteractions(inventoryMapper);
    }

    @Test
    void batchPropagatesMidBatchInsufficientInventory() {
        when(inventoryMapper.selectOne(any()))
                .thenReturn(inventory(1L), inventory(2L));
        when(inventoryMapper.deductIfEnough(1L, 1L)).thenReturn(1);
        when(inventoryMapper.deductIfEnough(2L, 2L)).thenReturn(0);

        assertThatThrownBy(() -> service().deductBatch(List.of(
                new InventoryDeductCommand(1L, 1L),
                new InventoryDeductCommand(2L, 2L))))
                .isInstanceOf(DemoOrderBusinessException.class)
                .hasMessage("insufficient inventory for product id 2");

        verify(inventoryMapper).deductIfEnough(1L, 1L);
        verify(inventoryMapper).deductIfEnough(2L, 2L);
    }

    private InventoryApplicationService service() {
        return new InventoryApplicationService(inventoryMapper);
    }

    private InventoryEntity inventory(Long productId) {
        InventoryEntity inventory = new InventoryEntity();
        inventory.setProductId(productId);
        return inventory;
    }
}
