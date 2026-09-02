package com.apiops.demo.order.order.dto;

import io.swagger.v3.oas.annotations.media.ArraySchema;
import io.swagger.v3.oas.annotations.media.Schema;
import jakarta.validation.Valid;
import jakarta.validation.constraints.NotEmpty;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Positive;

import java.util.List;

@Schema(description = "Request to create an order for one user.")
public class CreateOrderRequest {

    @NotNull
    @Positive
    @Schema(description = "User primary key that owns the order.", example = "1", format = "int64",
            minimum = "1", requiredMode = Schema.RequiredMode.REQUIRED)
    private Long userId;

    @NotEmpty
    @Valid
    @ArraySchema(minItems = 1, schema = @Schema(implementation = CreateOrderItemRequest.class),
            arraySchema = @Schema(description = "At least one distinct product line."))
    private List<CreateOrderItemRequest> items;

    /**
     * Coupon template ID from demo_coupon. The service resolves the user's
     * AVAILABLE demo_user_coupon record before consuming it.
     */
    @Positive
    @Schema(description = "Coupon template primary key from demo_coupon; the service resolves the user's AVAILABLE user-coupon record before consuming it.",
            example = "1", format = "int64", minimum = "1", nullable = true)
    private Long couponId;

    public Long getUserId() {
        return userId;
    }

    public void setUserId(Long userId) {
        this.userId = userId;
    }

    public List<CreateOrderItemRequest> getItems() {
        return items;
    }

    public void setItems(List<CreateOrderItemRequest> items) {
        this.items = items;
    }

    public Long getCouponId() {
        return couponId;
    }

    public void setCouponId(Long couponId) {
        this.couponId = couponId;
    }
}
