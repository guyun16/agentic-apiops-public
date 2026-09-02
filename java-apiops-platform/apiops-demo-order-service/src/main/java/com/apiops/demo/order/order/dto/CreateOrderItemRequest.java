package com.apiops.demo.order.order.dto;

import io.swagger.v3.oas.annotations.media.Schema;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Positive;

@Schema(description = "One product line in an order creation request.")
public class CreateOrderItemRequest {

    @NotNull
    @Positive
    @Schema(description = "Product primary key.", example = "1", format = "int64",
            minimum = "1", requiredMode = Schema.RequiredMode.REQUIRED)
    private Long productId;

    @NotNull
    @Positive
    @Schema(description = "Number of units to purchase.", example = "2", minimum = "1",
            requiredMode = Schema.RequiredMode.REQUIRED)
    private Integer quantity;

    public Long getProductId() {
        return productId;
    }

    public void setProductId(Long productId) {
        this.productId = productId;
    }

    public Integer getQuantity() {
        return quantity;
    }

    public void setQuantity(Integer quantity) {
        this.quantity = quantity;
    }
}
