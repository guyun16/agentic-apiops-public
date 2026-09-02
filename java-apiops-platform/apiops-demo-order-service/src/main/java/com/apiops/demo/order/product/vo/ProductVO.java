package com.apiops.demo.order.product.vo;

import io.swagger.v3.oas.annotations.media.Schema;

import java.math.BigDecimal;
import java.time.LocalDateTime;

@Schema(description = "Product catalog view. Persistence-only fields such as version and deleted are not exposed.")
public class ProductVO {

    @Schema(description = "Product primary key.", example = "1", format = "int64",
            requiredMode = Schema.RequiredMode.REQUIRED)
    private Long id;
    @Schema(description = "Stable product business number.", example = "prd_001",
            requiredMode = Schema.RequiredMode.REQUIRED)
    private String productNo;
    @Schema(description = "Product display name.", example = "Demo Product 001",
            requiredMode = Schema.RequiredMode.REQUIRED)
    private String productName;
    @Schema(description = "Sale price in the service's monetary unit.", example = "100.00",
            implementation = Double.class, format = "double", requiredMode = Schema.RequiredMode.REQUIRED)
    private BigDecimal price;
    @Schema(description = "Current catalog status.", allowableValues = {"ON_SALE", "OFF_SALE"},
            example = "ON_SALE", requiredMode = Schema.RequiredMode.REQUIRED)
    private String status;
    @Schema(description = "Creation time in ISO-8601 date-time format.",
            example = "2025-01-01T00:00:00", format = "date-time",
            requiredMode = Schema.RequiredMode.REQUIRED)
    private LocalDateTime createdAt;
    @Schema(description = "Last update time in ISO-8601 date-time format.",
            example = "2025-01-01T00:00:00", format = "date-time",
            requiredMode = Schema.RequiredMode.REQUIRED)
    private LocalDateTime updatedAt;

    public Long getId() { return id; }
    public void setId(Long id) { this.id = id; }
    public String getProductNo() { return productNo; }
    public void setProductNo(String productNo) { this.productNo = productNo; }
    public String getProductName() { return productName; }
    public void setProductName(String productName) { this.productName = productName; }
    public BigDecimal getPrice() { return price; }
    public void setPrice(BigDecimal price) { this.price = price; }
    public String getStatus() { return status; }
    public void setStatus(String status) { this.status = status; }
    public LocalDateTime getCreatedAt() { return createdAt; }
    public void setCreatedAt(LocalDateTime createdAt) { this.createdAt = createdAt; }
    public LocalDateTime getUpdatedAt() { return updatedAt; }
    public void setUpdatedAt(LocalDateTime updatedAt) { this.updatedAt = updatedAt; }
}
