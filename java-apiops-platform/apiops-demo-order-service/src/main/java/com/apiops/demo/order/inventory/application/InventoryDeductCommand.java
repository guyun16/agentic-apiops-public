package com.apiops.demo.order.inventory.application;

public class InventoryDeductCommand {

    private final Long productId;
    private final Long quantity;

    public InventoryDeductCommand(Long productId, Long quantity) {
        this.productId = productId;
        this.quantity = quantity;
    }

    public Long getProductId() {
        return productId;
    }

    public Long getQuantity() {
        return quantity;
    }
}
