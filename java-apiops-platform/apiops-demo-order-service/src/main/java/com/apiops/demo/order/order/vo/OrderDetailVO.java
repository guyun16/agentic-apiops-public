package com.apiops.demo.order.order.vo;

import io.swagger.v3.oas.annotations.media.ArraySchema;
import io.swagger.v3.oas.annotations.media.Schema;

import java.math.BigDecimal;
import java.time.LocalDateTime;
import java.util.List;

@Schema(description = "Full order details returned by order lifecycle operations.")
public class OrderDetailVO {

    @Schema(description = "Order primary key.", example = "10", format = "int64",
            requiredMode = Schema.RequiredMode.REQUIRED)
    private Long id;
    @Schema(description = "Generated order business number.",
            example = "ord_00000000-0000-4000-8000-000000000001",
            requiredMode = Schema.RequiredMode.REQUIRED)
    private String orderNo;
    @Schema(description = "User primary key that owns the order.", example = "1", format = "int64",
            requiredMode = Schema.RequiredMode.REQUIRED)
    private Long userId;
    @Schema(description = "Sum of order-item line amounts before coupon discount.", example = "100.00",
            implementation = Double.class, format = "double", requiredMode = Schema.RequiredMode.REQUIRED)
    private BigDecimal originalAmount;
    @Schema(description = "Coupon discount applied to the order.", example = "20.00",
            implementation = Double.class, format = "double", requiredMode = Schema.RequiredMode.REQUIRED)
    private BigDecimal discountAmount;
    @Schema(description = "Amount payable after discount.", example = "80.00",
            implementation = Double.class, format = "double", requiredMode = Schema.RequiredMode.REQUIRED)
    private BigDecimal payableAmount;
    @Schema(description = "Order lifecycle status.", allowableValues = {"PENDING_PAYMENT", "PAID", "CANCELLED"},
            example = "PENDING_PAYMENT", requiredMode = Schema.RequiredMode.REQUIRED)
    private String status;
    @Schema(description = "Creation time in ISO-8601 date-time format.",
            example = "2025-01-01T00:00:00", format = "date-time",
            requiredMode = Schema.RequiredMode.REQUIRED)
    private LocalDateTime createdAt;
    @Schema(description = "Last update time in ISO-8601 date-time format.",
            example = "2025-01-01T00:00:00", format = "date-time",
            requiredMode = Schema.RequiredMode.REQUIRED)
    private LocalDateTime updatedAt;
    @ArraySchema(minItems = 1, schema = @Schema(implementation = OrderItemVO.class),
            arraySchema = @Schema(description = "Order lines in ascending item-id order."))
    private List<OrderItemVO> items;

    public Long getId() { return id; }
    public void setId(Long id) { this.id = id; }
    public String getOrderNo() { return orderNo; }
    public void setOrderNo(String orderNo) { this.orderNo = orderNo; }
    public Long getUserId() { return userId; }
    public void setUserId(Long userId) { this.userId = userId; }
    public BigDecimal getOriginalAmount() { return originalAmount; }
    public void setOriginalAmount(BigDecimal originalAmount) { this.originalAmount = originalAmount; }
    public BigDecimal getDiscountAmount() { return discountAmount; }
    public void setDiscountAmount(BigDecimal discountAmount) { this.discountAmount = discountAmount; }
    public BigDecimal getPayableAmount() { return payableAmount; }
    public void setPayableAmount(BigDecimal payableAmount) { this.payableAmount = payableAmount; }
    public String getStatus() { return status; }
    public void setStatus(String status) { this.status = status; }
    public LocalDateTime getCreatedAt() { return createdAt; }
    public void setCreatedAt(LocalDateTime createdAt) { this.createdAt = createdAt; }
    public LocalDateTime getUpdatedAt() { return updatedAt; }
    public void setUpdatedAt(LocalDateTime updatedAt) { this.updatedAt = updatedAt; }
    public List<OrderItemVO> getItems() { return items; }
    public void setItems(List<OrderItemVO> items) { this.items = items; }
}
