package com.apiops.demo.order.payment.mapper;

import com.apiops.demo.order.payment.entity.PaymentEntity;
import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Update;

import java.time.LocalDateTime;

public interface PaymentMapper extends BaseMapper<PaymentEntity> {

    @Update("""
            UPDATE demo_payment
            SET status = 'SUCCESS',
                paid_at = #{paidAt},
                updated_at = CURRENT_TIMESTAMP(3)
            WHERE id = #{paymentId}
              AND status = 'PENDING'
            """)
    int markSuccessIfPending(
            @Param("paymentId") Long paymentId,
            @Param("paidAt") LocalDateTime paidAt
    );
}
