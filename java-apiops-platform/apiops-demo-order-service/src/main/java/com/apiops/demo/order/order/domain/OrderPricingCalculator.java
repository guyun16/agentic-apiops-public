package com.apiops.demo.order.order.domain;

import com.apiops.demo.order.common.exception.DemoOrderBusinessException;
import com.apiops.demo.order.common.exception.DemoOrderErrorCode;

import java.math.BigDecimal;
import java.util.List;

public final class OrderPricingCalculator {

    private OrderPricingCalculator() {
    }

    public static BigDecimal originalAmount(List<BigDecimal> lineAmounts) {
        if (lineAmounts == null || lineAmounts.isEmpty()) {
            throw businessConflict("order must contain at least one item");
        }
        return lineAmounts.stream()
                .reduce(BigDecimal.ZERO, BigDecimal::add);
    }

    public static BigDecimal discountAmount(
            BigDecimal originalAmount,
            BigDecimal thresholdAmount,
            BigDecimal couponDiscountAmount
    ) {
        requireNonNegative(originalAmount, "original amount");
        requireNonNegative(thresholdAmount, "coupon threshold amount");
        requirePositive(couponDiscountAmount, "coupon discount amount");
        if (originalAmount.compareTo(thresholdAmount) < 0) {
            throw businessConflict("order amount does not meet coupon threshold");
        }
        if (couponDiscountAmount.compareTo(originalAmount) > 0) {
            throw businessConflict("coupon discount exceeds order amount");
        }
        return couponDiscountAmount;
    }

    public static BigDecimal payableAmount(BigDecimal originalAmount, BigDecimal discountAmount) {
        requireNonNegative(originalAmount, "original amount");
        requireNonNegative(discountAmount, "discount amount");
        BigDecimal payableAmount = originalAmount.subtract(discountAmount);
        if (payableAmount.signum() < 0) {
            throw businessConflict("payable amount must not be negative");
        }
        return payableAmount;
    }

    private static void requireNonNegative(BigDecimal value, String name) {
        if (value == null || value.signum() < 0) {
            throw businessConflict(name + " must not be negative");
        }
    }

    private static void requirePositive(BigDecimal value, String name) {
        if (value == null || value.signum() <= 0) {
            throw businessConflict(name + " must be positive");
        }
    }

    private static DemoOrderBusinessException businessConflict(String message) {
        return new DemoOrderBusinessException(DemoOrderErrorCode.BUSINESS_CONFLICT, message);
    }
}
