package com.apiops.demo.order.coupon.application;

import com.apiops.demo.order.common.exception.DemoOrderBusinessException;
import com.apiops.demo.order.common.exception.DemoOrderErrorCode;
import com.apiops.demo.order.common.exception.ResourceNotFoundException;
import com.apiops.demo.order.coupon.converter.CouponConverter;
import com.apiops.demo.order.coupon.entity.CouponEntity;
import com.apiops.demo.order.coupon.entity.UserCouponEntity;
import com.apiops.demo.order.coupon.mapper.CouponMapper;
import com.apiops.demo.order.coupon.mapper.UserCouponMapper;
import com.apiops.demo.order.coupon.vo.CouponVO;
import com.apiops.demo.order.coupon.vo.UserCouponVO;
import com.apiops.demo.order.user.entity.UserEntity;
import com.apiops.demo.order.user.mapper.UserMapper;
import com.baomidou.mybatisplus.core.toolkit.Wrappers;
import org.springframework.dao.DuplicateKeyException;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.time.LocalDateTime;
import java.util.Collections;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import java.util.function.Function;
import java.util.stream.Collectors;

@Service
public class CouponApplicationService {

    private static final String USER_ENABLED = "ENABLED";
    private static final String COUPON_ACTIVE = "ACTIVE";
    private static final String USER_COUPON_AVAILABLE = "AVAILABLE";

    private final CouponMapper couponMapper;
    private final UserCouponMapper userCouponMapper;
    private final UserMapper userMapper;

    public CouponApplicationService(CouponMapper couponMapper,
                                    UserCouponMapper userCouponMapper,
                                    UserMapper userMapper) {
        this.couponMapper = couponMapper;
        this.userCouponMapper = userCouponMapper;
        this.userMapper = userMapper;
    }

    public CouponVO queryCouponById(Long couponId) {
        CouponEntity coupon = findCoupon(couponId);
        if (coupon == null) {
            throw new ResourceNotFoundException("coupon id " + couponId + " not found");
        }
        return CouponConverter.toCouponVO(coupon);
    }

    @Transactional
    public UserCouponVO claimCoupon(Long userId, Long couponId) {
        UserEntity user = userMapper.selectById(userId);
        if (user == null) {
            throw new ResourceNotFoundException("user id " + userId + " not found");
        }
        if (!USER_ENABLED.equals(user.getStatus())) {
            throw new DemoOrderBusinessException(
                    DemoOrderErrorCode.BUSINESS_CONFLICT,
                    "user id " + userId + " is not eligible to claim coupons");
        }

        CouponEntity coupon = findCoupon(couponId);
        if (coupon == null) {
            throw new ResourceNotFoundException("coupon id " + couponId + " not found");
        }
        if (!COUPON_ACTIVE.equals(coupon.getStatus())) {
            throw new DemoOrderBusinessException(
                    DemoOrderErrorCode.BUSINESS_CONFLICT,
                    "coupon id " + couponId + " is not active");
        }
        LocalDateTime now = LocalDateTime.now();
        if (now.isBefore(coupon.getValidFrom()) || now.isAfter(coupon.getValidUntil())) {
            throw new DemoOrderBusinessException(
                    DemoOrderErrorCode.BUSINESS_CONFLICT,
                    "coupon id " + couponId + " is outside its validity period");
        }

        if (hasUserCoupon(userId, couponId)) {
            throw duplicateClaim(userId, couponId);
        }

        UserCouponEntity entity = new UserCouponEntity();
        entity.setUserCouponNo("ucp_" + UUID.randomUUID());
        entity.setUserId(userId);
        entity.setCouponId(couponId);
        entity.setStatus(USER_COUPON_AVAILABLE);
        entity.setReceivedAt(now);
        entity.setUsedAt(null);
        try {
            userCouponMapper.insert(entity);
        } catch (DuplicateKeyException exception) {
            // The pair constraint is the claim conflict. A generated user_coupon_no
            // collision is not silently converted into a duplicate claim.
            if (hasUserCoupon(userId, couponId)) {
                throw duplicateClaim(userId, couponId);
            }
            throw exception;
        }

        UserCouponEntity saved = userCouponMapper.selectById(entity.getId());
        return CouponConverter.toUserCouponVO(saved, coupon);
    }

    public List<UserCouponVO> queryUserCoupons(Long userId, String status) {
        UserEntity user = userMapper.selectById(userId);
        if (user == null) {
            throw new ResourceNotFoundException("user id " + userId + " not found");
        }

        List<UserCouponEntity> userCoupons = userCouponMapper.selectList(
                Wrappers.<UserCouponEntity>lambdaQuery()
                        .eq(UserCouponEntity::getUserId, userId)
                        .eq(status != null && !status.isBlank(), UserCouponEntity::getStatus, status)
                        .orderByDesc(UserCouponEntity::getId));
        if (userCoupons.isEmpty()) {
            return Collections.emptyList();
        }

        List<Long> couponIds = userCoupons.stream()
                .map(UserCouponEntity::getCouponId)
                .distinct()
                .toList();
        Map<Long, CouponEntity> coupons = couponMapper.selectList(
                        Wrappers.<CouponEntity>lambdaQuery()
                                .in(CouponEntity::getId, couponIds)
                                .eq(CouponEntity::getDeleted, false)).stream()
                .collect(Collectors.toMap(CouponEntity::getId, Function.identity()));
        return userCoupons.stream()
                .map(userCoupon -> CouponConverter.toUserCouponVO(
                        userCoupon, coupons.get(userCoupon.getCouponId())))
                .toList();
    }

    private CouponEntity findCoupon(Long couponId) {
        return couponMapper.selectOne(
                Wrappers.<CouponEntity>lambdaQuery()
                        .eq(CouponEntity::getId, couponId)
                        .eq(CouponEntity::getDeleted, false));
    }

    private boolean hasUserCoupon(Long userId, Long couponId) {
        Long count = userCouponMapper.selectCount(
                Wrappers.<UserCouponEntity>lambdaQuery()
                        .eq(UserCouponEntity::getUserId, userId)
                        .eq(UserCouponEntity::getCouponId, couponId));
        return count != null && count > 0;
    }

    private static DemoOrderBusinessException duplicateClaim(Long userId, Long couponId) {
        return new DemoOrderBusinessException(
                DemoOrderErrorCode.BUSINESS_CONFLICT,
                "user " + userId + " already claimed coupon " + couponId);
    }
}
