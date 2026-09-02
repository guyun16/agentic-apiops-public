package com.apiops.demo.order.coupon.mapper;

import com.apiops.demo.order.coupon.entity.UserCouponEntity;
import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Update;

public interface UserCouponMapper extends BaseMapper<UserCouponEntity> {

    @Update("""
            UPDATE demo_user_coupon
            SET status = 'USED', used_at = CURRENT_TIMESTAMP(3), updated_at = CURRENT_TIMESTAMP(3)
            WHERE id = #{userCouponId}
              AND user_id = #{userId}
              AND status = 'AVAILABLE'
            """)
    int consumeIfAvailable(
            @Param("userCouponId") Long userCouponId,
            @Param("userId") Long userId
    );
}
