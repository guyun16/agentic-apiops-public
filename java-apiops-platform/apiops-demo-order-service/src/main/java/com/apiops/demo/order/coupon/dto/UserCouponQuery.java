package com.apiops.demo.order.coupon.dto;

import io.swagger.v3.oas.annotations.media.Schema;
import jakarta.validation.constraints.Pattern;
import org.springdoc.core.annotations.ParameterObject;

@Schema(description = "Optional filter for a user's claimed coupons.")
@ParameterObject
public class UserCouponQuery {

    @Pattern(regexp = "AVAILABLE|USED|EXPIRED")
    @Schema(description = "Optional user-coupon status filter.",
            allowableValues = {"AVAILABLE", "USED", "EXPIRED"}, example = "AVAILABLE",
            nullable = true)
    private String status;

    public String getStatus() { return status; }
    public void setStatus(String status) { this.status = status; }
}
