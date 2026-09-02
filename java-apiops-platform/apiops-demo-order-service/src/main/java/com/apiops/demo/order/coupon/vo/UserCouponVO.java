package com.apiops.demo.order.coupon.vo;

import io.swagger.v3.oas.annotations.media.Schema;

import java.time.LocalDateTime;

@Schema(description = "User-owned coupon view. couponId refers to the coupon template primary key.")
public class UserCouponVO {

    @Schema(description = "User-coupon instance primary key.", example = "10", format = "int64",
            requiredMode = Schema.RequiredMode.REQUIRED)
    private Long id;
    @Schema(description = "Stable user-coupon instance business number.", example = "ucp_001",
            requiredMode = Schema.RequiredMode.REQUIRED)
    private String userCouponNo;
    @Schema(description = "User primary key that owns the coupon.", example = "1", format = "int64",
            requiredMode = Schema.RequiredMode.REQUIRED)
    private Long userId;
    @Schema(description = "Coupon template primary key from demo_coupon; this is not the user-coupon instance id.",
            example = "1", format = "int64", requiredMode = Schema.RequiredMode.REQUIRED)
    private Long couponId;
    @Schema(description = "User-coupon lifecycle status.", allowableValues = {"AVAILABLE", "USED", "EXPIRED"},
            example = "AVAILABLE", requiredMode = Schema.RequiredMode.REQUIRED)
    private String status;
    @Schema(description = "Time when the user claimed the coupon.", example = "2025-01-01T00:00:00",
            format = "date-time", requiredMode = Schema.RequiredMode.REQUIRED)
    private LocalDateTime receivedAt;
    @Schema(description = "Time when the user-coupon was consumed; null while unused.",
            example = "2025-01-02T00:00:00", format = "date-time", nullable = true)
    private LocalDateTime usedAt;
    @Schema(description = "Creation time in ISO-8601 date-time format.",
            example = "2025-01-01T00:00:00", format = "date-time",
            requiredMode = Schema.RequiredMode.REQUIRED)
    private LocalDateTime createdAt;
    @Schema(description = "Last update time in ISO-8601 date-time format.",
            example = "2025-01-01T00:00:00", format = "date-time",
            requiredMode = Schema.RequiredMode.REQUIRED)
    private LocalDateTime updatedAt;
    @Schema(description = "Resolved coupon-template details.", requiredMode = Schema.RequiredMode.REQUIRED)
    private CouponVO coupon;

    public Long getId() { return id; }
    public void setId(Long id) { this.id = id; }
    public String getUserCouponNo() { return userCouponNo; }
    public void setUserCouponNo(String userCouponNo) { this.userCouponNo = userCouponNo; }
    public Long getUserId() { return userId; }
    public void setUserId(Long userId) { this.userId = userId; }
    public Long getCouponId() { return couponId; }
    public void setCouponId(Long couponId) { this.couponId = couponId; }
    public String getStatus() { return status; }
    public void setStatus(String status) { this.status = status; }
    public LocalDateTime getReceivedAt() { return receivedAt; }
    public void setReceivedAt(LocalDateTime receivedAt) { this.receivedAt = receivedAt; }
    public LocalDateTime getUsedAt() { return usedAt; }
    public void setUsedAt(LocalDateTime usedAt) { this.usedAt = usedAt; }
    public LocalDateTime getCreatedAt() { return createdAt; }
    public void setCreatedAt(LocalDateTime createdAt) { this.createdAt = createdAt; }
    public LocalDateTime getUpdatedAt() { return updatedAt; }
    public void setUpdatedAt(LocalDateTime updatedAt) { this.updatedAt = updatedAt; }
    public CouponVO getCoupon() { return coupon; }
    public void setCoupon(CouponVO coupon) { this.coupon = coupon; }
}
