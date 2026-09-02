package com.apiops.demo.order.payment.dto;

import io.swagger.v3.oas.annotations.media.Schema;
import jakarta.validation.constraints.DecimalMin;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Positive;

import java.math.BigDecimal;
import java.time.LocalDateTime;

/** Stable business fields received from the payment platform callback. */
@Schema(description = "Stable business fields received from the payment platform callback.")
public class PaymentCallbackRequest {

    @NotBlank
    @Schema(description = "Payment platform callback identifier used for idempotency.",
            example = "callback-1", requiredMode = Schema.RequiredMode.REQUIRED)
    private String callbackId;

    @NotNull
    @Positive
    @Schema(description = "Payment primary key.", example = "20", format = "int64", minimum = "1",
            requiredMode = Schema.RequiredMode.REQUIRED)
    private Long paymentId;

    @NotNull
    @Positive
    @Schema(description = "Order primary key associated with the payment.", example = "10",
            format = "int64", minimum = "1", requiredMode = Schema.RequiredMode.REQUIRED)
    private Long orderId;

    @NotNull
    @DecimalMin("0")
    @Schema(description = "Amount reported by the payment platform; it must equal the payment amount.",
            example = "99.00", implementation = Double.class, format = "double", minimum = "0",
            requiredMode = Schema.RequiredMode.REQUIRED)
    private BigDecimal paymentAmount;

    @NotBlank
    @Schema(description = "Payment result. Only SUCCESS is accepted for this callback endpoint; another non-blank value is a business conflict.",
            allowableValues = {"SUCCESS"}, example = "SUCCESS", requiredMode = Schema.RequiredMode.REQUIRED)
    private String result;

    @Schema(description = "Optional time supplied by the payment platform; omitted values use server receipt time.",
            example = "2025-01-01T00:00:00", format = "date-time", nullable = true)
    private LocalDateTime callbackTime;

    public String getCallbackId() {
        return callbackId;
    }

    public void setCallbackId(String callbackId) {
        this.callbackId = callbackId;
    }

    public Long getPaymentId() {
        return paymentId;
    }

    public void setPaymentId(Long paymentId) {
        this.paymentId = paymentId;
    }

    public Long getOrderId() {
        return orderId;
    }

    public void setOrderId(Long orderId) {
        this.orderId = orderId;
    }

    public BigDecimal getPaymentAmount() {
        return paymentAmount;
    }

    public void setPaymentAmount(BigDecimal paymentAmount) {
        this.paymentAmount = paymentAmount;
    }

    public String getResult() {
        return result;
    }

    public void setResult(String result) {
        this.result = result;
    }

    public LocalDateTime getCallbackTime() {
        return callbackTime;
    }

    public void setCallbackTime(LocalDateTime callbackTime) {
        this.callbackTime = callbackTime;
    }
}
