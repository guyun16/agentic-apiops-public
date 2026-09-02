package com.apiops.demo.order.payment.mapper;

import com.apiops.demo.order.payment.entity.PaymentCallbackEntity;
import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Update;

import java.time.LocalDateTime;

public interface PaymentCallbackMapper extends BaseMapper<PaymentCallbackEntity> {

    @Update("""
            UPDATE demo_payment_callback
            SET process_status = #{processStatus},
                result_message = #{resultMessage},
                processed_at = #{processedAt},
                updated_at = CURRENT_TIMESTAMP(3)
            WHERE callback_no = #{callbackId}
              AND request_fingerprint = #{requestFingerprint}
            """)
    int markProcessed(
            @Param("callbackId") String callbackId,
            @Param("requestFingerprint") String requestFingerprint,
            @Param("processStatus") String processStatus,
            @Param("resultMessage") String resultMessage,
            @Param("processedAt") LocalDateTime processedAt
    );
}
