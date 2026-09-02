package com.apiops.demo.order.coupon.converter;

import com.apiops.demo.order.coupon.entity.CouponEntity;
import com.apiops.demo.order.coupon.entity.UserCouponEntity;
import com.apiops.demo.order.coupon.vo.CouponVO;
import com.apiops.demo.order.coupon.vo.UserCouponVO;

public final class CouponConverter {

    private CouponConverter() {
    }

    public static CouponVO toCouponVO(CouponEntity entity) {
        if (entity == null) {
            return null;
        }
        CouponVO vo = new CouponVO();
        vo.setId(entity.getId());
        vo.setCouponNo(entity.getCouponNo());
        vo.setCouponName(entity.getCouponName());
        vo.setThresholdAmount(entity.getThresholdAmount());
        vo.setDiscountAmount(entity.getDiscountAmount());
        vo.setValidFrom(entity.getValidFrom());
        vo.setValidUntil(entity.getValidUntil());
        vo.setStatus(entity.getStatus());
        vo.setCreatedAt(entity.getCreatedAt());
        vo.setUpdatedAt(entity.getUpdatedAt());
        return vo;
    }

    public static UserCouponVO toUserCouponVO(UserCouponEntity entity, CouponEntity coupon) {
        UserCouponVO vo = new UserCouponVO();
        vo.setId(entity.getId());
        vo.setUserCouponNo(entity.getUserCouponNo());
        vo.setUserId(entity.getUserId());
        vo.setCouponId(entity.getCouponId());
        vo.setStatus(entity.getStatus());
        vo.setReceivedAt(entity.getReceivedAt());
        vo.setUsedAt(entity.getUsedAt());
        vo.setCreatedAt(entity.getCreatedAt());
        vo.setUpdatedAt(entity.getUpdatedAt());
        vo.setCoupon(toCouponVO(coupon));
        return vo;
    }
}
