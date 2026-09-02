package com.apiops.demo.order.coupon.vo;

import io.swagger.v3.oas.annotations.media.Schema;

import java.math.BigDecimal;
import java.time.LocalDateTime;

@Schema(description = "Coupon template view. The id identifies a coupon template, not a user-owned coupon instance.")
public class CouponVO {

    @Schema(description = "Coupon template primary key.", example = "1", format = "int64",
            requiredMode = Schema.RequiredMode.REQUIRED)
    private Long id;
    @Schema(description = "Stable coupon-template business number.", example = "cpn_001",
            requiredMode = Schema.RequiredMode.REQUIRED)
    private String couponNo;
    @Schema(description = "Coupon template display name.", example = "100 minus 20",
            requiredMode = Schema.RequiredMode.REQUIRED)
    private String couponName;
    @Schema(description = "Minimum order amount required by the coupon template.", example = "100.00",
            implementation = Double.class, format = "double", requiredMode = Schema.RequiredMode.REQUIRED)
    private BigDecimal thresholdAmount;
    @Schema(description = "Discount amount granted by the coupon template.", example = "20.00",
            implementation = Double.class, format = "double", requiredMode = Schema.RequiredMode.REQUIRED)
    private BigDecimal discountAmount;
    @Schema(description = "Coupon validity start in ISO-8601 date-time format.",
            example = "2020-01-01T00:00:00", format = "date-time",
            requiredMode = Schema.RequiredMode.REQUIRED)
    private LocalDateTime validFrom;
    @Schema(description = "Coupon validity end in ISO-8601 date-time format.",
            example = "2099-12-31T23:59:59.999", format = "date-time",
            requiredMode = Schema.RequiredMode.REQUIRED)
    private LocalDateTime validUntil;
    @Schema(description = "Coupon-template status.", allowableValues = {"ACTIVE", "INACTIVE"},
            example = "ACTIVE", requiredMode = Schema.RequiredMode.REQUIRED)
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
    public String getCouponNo() { return couponNo; }
    public void setCouponNo(String couponNo) { this.couponNo = couponNo; }
    public String getCouponName() { return couponName; }
    public void setCouponName(String couponName) { this.couponName = couponName; }
    public BigDecimal getThresholdAmount() { return thresholdAmount; }
    public void setThresholdAmount(BigDecimal thresholdAmount) { this.thresholdAmount = thresholdAmount; }
    public BigDecimal getDiscountAmount() { return discountAmount; }
    public void setDiscountAmount(BigDecimal discountAmount) { this.discountAmount = discountAmount; }
    public LocalDateTime getValidFrom() { return validFrom; }
    public void setValidFrom(LocalDateTime validFrom) { this.validFrom = validFrom; }
    public LocalDateTime getValidUntil() { return validUntil; }
    public void setValidUntil(LocalDateTime validUntil) { this.validUntil = validUntil; }
    public String getStatus() { return status; }
    public void setStatus(String status) { this.status = status; }
    public LocalDateTime getCreatedAt() { return createdAt; }
    public void setCreatedAt(LocalDateTime createdAt) { this.createdAt = createdAt; }
    public LocalDateTime getUpdatedAt() { return updatedAt; }
    public void setUpdatedAt(LocalDateTime updatedAt) { this.updatedAt = updatedAt; }
}
