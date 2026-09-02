package com.apiops.demo.order.payment.vo;

import io.swagger.v3.oas.annotations.media.Schema;

import java.math.BigDecimal;

@Schema(description = "Result of a payment callback, including whether it was a first delivery or an idempotent replay.")
public class PaymentCallbackResultVO {

    @Schema(description = "Payment platform callback identifier.", example = "callback-1",
            requiredMode = Schema.RequiredMode.REQUIRED)
    private String callbackId;
    @Schema(description = "Payment primary key.", example = "20", format = "int64",
            requiredMode = Schema.RequiredMode.REQUIRED)
    private Long paymentId;
    @Schema(description = "Order primary key associated with the payment.", example = "10",
            format = "int64", requiredMode = Schema.RequiredMode.REQUIRED)
    private Long orderId;
    @Schema(description = "Payment amount accepted by the callback processor.", example = "99.00",
            implementation = Double.class, format = "double", requiredMode = Schema.RequiredMode.REQUIRED)
    private BigDecimal paymentAmount;
    @Schema(description = "Normalized payment result.", allowableValues = {"SUCCESS"}, example = "SUCCESS",
            requiredMode = Schema.RequiredMode.REQUIRED)
    private String result;
    @Schema(description = "Processing outcome.", allowableValues = {"FIRST_SUCCESS", "IDEMPOTENT_REPLAY"},
            example = "FIRST_SUCCESS", requiredMode = Schema.RequiredMode.REQUIRED)
    private String outcome;
    @Schema(description = "Whether this request replayed an already processed callback.", example = "false",
            requiredMode = Schema.RequiredMode.REQUIRED)
    private boolean replay;

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

    public String getOutcome() {
        return outcome;
    }

    public void setOutcome(String outcome) {
        this.outcome = outcome;
    }

    public boolean isReplay() {
        return replay;
    }

    public void setReplay(boolean replay) {
        this.replay = replay;
    }
}
