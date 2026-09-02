package com.apiops.demo.order.product.dto;

import io.swagger.v3.oas.annotations.media.Schema;
import jakarta.validation.constraints.DecimalMin;
import jakarta.validation.constraints.Digits;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Pattern;
import jakarta.validation.constraints.Size;

import java.math.BigDecimal;

@Schema(description = "Request to create a product in the catalog.")
public class CreateProductRequest {

    @NotBlank
    @Size(max = 64)
    @Schema(description = "Stable product business number.", example = "prd_demo_001",
            maxLength = 64, requiredMode = Schema.RequiredMode.REQUIRED)
    private String productNo;

    @NotBlank
    @Size(max = 128)
    @Schema(description = "Product display name.", example = "Demo Product 001",
            maxLength = 128, requiredMode = Schema.RequiredMode.REQUIRED)
    private String productName;

    @NotNull
    @DecimalMin("0.01")
    @Digits(integer = 16, fraction = 2)
    @Schema(description = "Sale price in the service's monetary unit.", example = "100.00",
            implementation = Double.class, format = "double", minimum = "0.01",
            requiredMode = Schema.RequiredMode.REQUIRED)
    private BigDecimal price;

    @Pattern(regexp = "ON_SALE|OFF_SALE")
    @Schema(description = "Initial product status. Omit it to use ON_SALE.",
            allowableValues = {"ON_SALE", "OFF_SALE"}, example = "ON_SALE",
            nullable = true)
    private String status;

    public String getProductNo() {
        return productNo;
    }

    public void setProductNo(String productNo) {
        this.productNo = productNo;
    }

    public String getProductName() {
        return productName;
    }

    public void setProductName(String productName) {
        this.productName = productName;
    }

    public BigDecimal getPrice() {
        return price;
    }

    public void setPrice(BigDecimal price) {
        this.price = price;
    }

    public String getStatus() {
        return status;
    }

    public void setStatus(String status) {
        this.status = status;
    }
}
