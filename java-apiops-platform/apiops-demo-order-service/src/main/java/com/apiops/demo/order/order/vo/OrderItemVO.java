package com.apiops.demo.order.order.vo;

import io.swagger.v3.oas.annotations.media.Schema;

import java.math.BigDecimal;

@Schema(description = "Order line snapshot returned with order details.")
public class OrderItemVO {

    @Schema(description = "Order-item primary key.", example = "100", format = "int64",
            requiredMode = Schema.RequiredMode.REQUIRED)
    private Long id;
    @Schema(description = "Product primary key.", example = "1", format = "int64",
            requiredMode = Schema.RequiredMode.REQUIRED)
    private Long productId;
    @Schema(description = "Product business number captured at order creation.", example = "prd_001",
            requiredMode = Schema.RequiredMode.REQUIRED)
    private String productNo;
    @Schema(description = "Product name captured at order creation.", example = "Demo Product 001",
            requiredMode = Schema.RequiredMode.REQUIRED)
    private String productName;
    @Schema(description = "Unit sale price captured at order creation.", example = "100.00",
            implementation = Double.class, format = "double", requiredMode = Schema.RequiredMode.REQUIRED)
    private BigDecimal unitPrice;
    @Schema(description = "Number of units in this line.", example = "1", minimum = "1",
            requiredMode = Schema.RequiredMode.REQUIRED)
    private Integer quantity;
    @Schema(description = "unitPrice multiplied by quantity.", example = "100.00",
            implementation = Double.class, format = "double", requiredMode = Schema.RequiredMode.REQUIRED)
    private BigDecimal lineAmount;

    public Long getId() { return id; }
    public void setId(Long id) { this.id = id; }
    public Long getProductId() { return productId; }
    public void setProductId(Long productId) { this.productId = productId; }
    public String getProductNo() { return productNo; }
    public void setProductNo(String productNo) { this.productNo = productNo; }
    public String getProductName() { return productName; }
    public void setProductName(String productName) { this.productName = productName; }
    public BigDecimal getUnitPrice() { return unitPrice; }
    public void setUnitPrice(BigDecimal unitPrice) { this.unitPrice = unitPrice; }
    public Integer getQuantity() { return quantity; }
    public void setQuantity(Integer quantity) { this.quantity = quantity; }
    public BigDecimal getLineAmount() { return lineAmount; }
    public void setLineAmount(BigDecimal lineAmount) { this.lineAmount = lineAmount; }
}
