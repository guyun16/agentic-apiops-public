package com.apiops.demo.order.order.domain;

import com.apiops.demo.order.common.exception.DemoOrderBusinessException;
import org.junit.jupiter.api.Test;

import java.math.BigDecimal;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

class OrderPricingCalculatorTest {

    @Test
    void sumsLineAmountsForOriginalAmount() {
        assertThat(OrderPricingCalculator.originalAmount(List.of(
                new BigDecimal("10.00"), new BigDecimal("2.50"))))
                .isEqualByComparingTo("12.50");
    }

    @Test
    void noCouponUsesZeroDiscount() {
        assertThat(OrderPricingCalculator.payableAmount(
                new BigDecimal("12.50"), BigDecimal.ZERO))
                .isEqualByComparingTo("12.50");
    }

    @Test
    void couponDiscountAppliesWhenThresholdIsMet() {
        BigDecimal discount = OrderPricingCalculator.discountAmount(
                new BigDecimal("100.00"), new BigDecimal("80.00"), new BigDecimal("20.00"));
        assertThat(OrderPricingCalculator.payableAmount(
                new BigDecimal("100.00"), discount)).isEqualByComparingTo("80.00");
    }

    @Test
    void couponIsRejectedWhenThresholdIsNotMet() {
        assertThatThrownBy(() -> OrderPricingCalculator.discountAmount(
                new BigDecimal("79.99"), new BigDecimal("80.00"), new BigDecimal("20.00")))
                .isInstanceOf(DemoOrderBusinessException.class)
                .hasMessage("order amount does not meet coupon threshold");
    }

    @Test
    void negativePayableAmountIsRejected() {
        assertThatThrownBy(() -> OrderPricingCalculator.payableAmount(
                new BigDecimal("10.00"), new BigDecimal("10.01")))
                .isInstanceOf(DemoOrderBusinessException.class)
                .hasMessage("payable amount must not be negative");
    }
}
