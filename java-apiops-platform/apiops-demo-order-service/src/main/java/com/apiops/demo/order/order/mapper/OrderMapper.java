package com.apiops.demo.order.order.mapper;

import com.apiops.demo.order.order.entity.OrderEntity;
import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Update;

public interface OrderMapper extends BaseMapper<OrderEntity> {

    @Update("""
            UPDATE demo_order
            SET status = #{targetStatus}, updated_at = CURRENT_TIMESTAMP(3)
            WHERE id = #{orderId} AND status = #{expectedStatus}
            """)
    int updateStatusIfExpected(
            @Param("orderId") Long orderId,
            @Param("expectedStatus") String expectedStatus,
            @Param("targetStatus") String targetStatus
    );
}
