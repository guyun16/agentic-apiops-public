package com.apiops.demo.order.payment.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.FieldFill;
import com.baomidou.mybatisplus.annotation.TableField;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;

import java.math.BigDecimal;
import java.time.LocalDateTime;

@TableName("demo_payment_callback")
public class PaymentCallbackEntity {
    @TableId(value = "id", type = IdType.AUTO) private Long id;
    @TableField("callback_no") private String callbackNo;
    @TableField("payment_id") private Long paymentId;
    @TableField("callback_amount") private BigDecimal callbackAmount;
    @TableField("request_fingerprint") private String requestFingerprint;
    @TableField("process_status") private String processStatus;
    @TableField("result_code") private String resultCode;
    @TableField("result_message") private String resultMessage;
    @TableField("received_at") private LocalDateTime receivedAt;
    @TableField("processed_at") private LocalDateTime processedAt;
    @TableField(value = "created_at", fill = FieldFill.INSERT) private LocalDateTime createdAt;
    @TableField(value = "updated_at", fill = FieldFill.INSERT_UPDATE) private LocalDateTime updatedAt;

    public Long getId() { return id; }
    public void setId(Long id) { this.id = id; }
    public String getCallbackNo() { return callbackNo; }
    public void setCallbackNo(String callbackNo) { this.callbackNo = callbackNo; }
    public Long getPaymentId() { return paymentId; }
    public void setPaymentId(Long paymentId) { this.paymentId = paymentId; }
    public BigDecimal getCallbackAmount() { return callbackAmount; }
    public void setCallbackAmount(BigDecimal callbackAmount) { this.callbackAmount = callbackAmount; }
    public String getRequestFingerprint() { return requestFingerprint; }
    public void setRequestFingerprint(String requestFingerprint) { this.requestFingerprint = requestFingerprint; }
    public String getProcessStatus() { return processStatus; }
    public void setProcessStatus(String processStatus) { this.processStatus = processStatus; }
    public String getResultCode() { return resultCode; }
    public void setResultCode(String resultCode) { this.resultCode = resultCode; }
    public String getResultMessage() { return resultMessage; }
    public void setResultMessage(String resultMessage) { this.resultMessage = resultMessage; }
    public LocalDateTime getReceivedAt() { return receivedAt; }
    public void setReceivedAt(LocalDateTime receivedAt) { this.receivedAt = receivedAt; }
    public LocalDateTime getProcessedAt() { return processedAt; }
    public void setProcessedAt(LocalDateTime processedAt) { this.processedAt = processedAt; }
    public LocalDateTime getCreatedAt() { return createdAt; }
    public void setCreatedAt(LocalDateTime createdAt) { this.createdAt = createdAt; }
    public LocalDateTime getUpdatedAt() { return updatedAt; }
    public void setUpdatedAt(LocalDateTime updatedAt) { this.updatedAt = updatedAt; }
}
