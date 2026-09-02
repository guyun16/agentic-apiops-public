package com.apiops.demo.order.coupon;

import com.apiops.demo.order.common.exception.DemoOrderBusinessException;
import com.apiops.demo.order.common.exception.DemoOrderErrorCode;
import com.apiops.demo.order.common.exception.ResourceNotFoundException;
import com.apiops.demo.order.coupon.application.CouponApplicationService;
import com.apiops.demo.order.coupon.entity.CouponEntity;
import com.apiops.demo.order.coupon.entity.UserCouponEntity;
import com.apiops.demo.order.coupon.mapper.CouponMapper;
import com.apiops.demo.order.coupon.mapper.UserCouponMapper;
import com.apiops.demo.order.coupon.vo.CouponVO;
import com.apiops.demo.order.coupon.vo.UserCouponVO;
import com.apiops.demo.order.user.entity.UserEntity;
import com.apiops.demo.order.user.mapper.UserMapper;
import com.baomidou.mybatisplus.core.toolkit.Wrappers;
import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.TestInstance;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.test.annotation.Rollback;
import org.springframework.test.context.ActiveProfiles;
import org.springframework.transaction.annotation.Transactional;

import java.math.BigDecimal;
import java.time.LocalDateTime;
import java.util.UUID;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.NONE)
@ActiveProfiles("local")
@EnabledIfEnvironmentVariable(named = "APIOPS_ORDER_DB_URL", matches = ".+")
@Transactional
@Rollback
@TestInstance(TestInstance.Lifecycle.PER_CLASS)
class CouponIntegrationTest {

    private static final String TEST_COUPON_NO_PREFIX = "test_coupon_";

    @Autowired
    private CouponApplicationService couponApplicationService;

    @Autowired
    private CouponMapper couponMapper;

    @Autowired
    private UserCouponMapper userCouponMapper;

    @Autowired
    private UserMapper userMapper;

    @Test
    void queriesCouponTemplateWithRuleFields() {
        CouponVO coupon = couponApplicationService.queryCouponById(couponId("cpn_001"));

        assertThat(coupon.getCouponNo()).isEqualTo("cpn_001");
        assertThat(coupon.getThresholdAmount()).isEqualByComparingTo("100.00");
        assertThat(coupon.getDiscountAmount()).isEqualByComparingTo("20.00");
        assertThat(coupon.getStatus()).isEqualTo("ACTIVE");
        assertThat(coupon.getValidFrom()).isBefore(coupon.getValidUntil());
    }

    @Test
    void missingOrDeletedCouponTemplateReturnsNotFound() {
        assertThatThrownBy(() -> couponApplicationService.queryCouponById(Long.MAX_VALUE))
                .isInstanceOf(ResourceNotFoundException.class);

        CouponEntity deleted = createCoupon("Deleted Coupon", LocalDateTime.now().minusDays(1),
                LocalDateTime.now().plusDays(1));
        assertThat(couponMapper.update(Wrappers.<CouponEntity>lambdaUpdate()
                .eq(CouponEntity::getId, deleted.getId())
                .set(CouponEntity::getDeleted, true))).isEqualTo(1);
        assertThatThrownBy(() -> couponApplicationService.queryCouponById(deleted.getId()))
                .isInstanceOf(ResourceNotFoundException.class);
    }

    @Test
    void enabledUserClaimsValidCouponAndDatabaseRecordCanBeReloaded() {
        Long userId = userId("usr_002");
        Long couponId = couponId("cpn_used_001");

        UserCouponVO claimed = couponApplicationService.claimCoupon(userId, couponId);

        assertThat(claimed.getId()).isNotNull();
        assertThat(claimed.getUserId()).isEqualTo(userId);
        assertThat(claimed.getCouponId()).isEqualTo(couponId);
        assertThat(claimed.getStatus()).isEqualTo("AVAILABLE");
        assertThat(claimed.getReceivedAt()).isNotNull();
        assertThat(claimed.getCoupon().getCouponNo()).isEqualTo("cpn_used_001");

        UserCouponEntity databaseRecord = userCouponMapper.selectById(claimed.getId());
        assertThat(databaseRecord).isNotNull();
        assertThat(databaseRecord.getUserId()).isEqualTo(userId);
        assertThat(databaseRecord.getCouponId()).isEqualTo(couponId);
        assertThat(databaseRecord.getStatus()).isEqualTo("AVAILABLE");
    }

    @Test
    void duplicateClaimReturnsConflictAndKeepsOneRecord() {
        Long userId = userId("usr_001");
        Long couponId = couponId("cpn_001");

        assertThatThrownBy(() -> couponApplicationService.claimCoupon(userId, couponId))
                .isInstanceOf(DemoOrderBusinessException.class)
                .extracting(e -> ((DemoOrderBusinessException) e).getErrorCode())
                .isEqualTo(DemoOrderErrorCode.BUSINESS_CONFLICT);
        assertThat(userCouponCount(userId, couponId)).isEqualTo(1L);
    }

    @Test
    void differentUsersCanClaimTheSameCoupon() {
        CouponEntity coupon = createCoupon("Shared Coupon", LocalDateTime.now().minusDays(1),
                LocalDateTime.now().plusDays(1));

        UserCouponVO first = couponApplicationService.claimCoupon(userId("usr_001"), coupon.getId());
        UserCouponVO second = couponApplicationService.claimCoupon(userId("usr_002"), coupon.getId());

        assertThat(first.getId()).isNotEqualTo(second.getId());
        assertThat(userCouponCount(userId("usr_001"), coupon.getId())).isEqualTo(1L);
        assertThat(userCouponCount(userId("usr_002"), coupon.getId())).isEqualTo(1L);
    }

    @Test
    void rejectsMissingDisabledAndInvalidCouponClaims() {
        assertThatThrownBy(() -> couponApplicationService.claimCoupon(
                Long.MAX_VALUE, couponId("cpn_001")))
                .isInstanceOf(ResourceNotFoundException.class);
        assertThatThrownBy(() -> couponApplicationService.claimCoupon(
                userId("usr_disabled_001"), couponId("cpn_001")))
                .isInstanceOf(DemoOrderBusinessException.class);
        assertThatThrownBy(() -> couponApplicationService.claimCoupon(
                userId("usr_002"), Long.MAX_VALUE))
                .isInstanceOf(ResourceNotFoundException.class);
    }

    @Test
    void rejectsInactiveExpiredAndNotYetValidTemplates() {
        assertConflict(userId("usr_002"), couponId("cpn_inactive_001"));
        assertConflict(userId("usr_002"), couponId("cpn_expired_001"));
        CouponEntity future = createCoupon("Future Coupon", LocalDateTime.now().plusDays(1),
                LocalDateTime.now().plusDays(2));
        assertConflict(userId("usr_002"), future.getId());
    }

    @Test
    void queriesUserCouponsWithOptionalStatusAndStableDescendingIds() {
        Long userId = userId("usr_001");
        var all = couponApplicationService.queryUserCoupons(userId, null);
        assertThat(all).isNotEmpty();
        assertThat(all).allMatch(item -> item.getUserId().equals(userId));
        assertThat(all).allMatch(item -> item.getCoupon() != null);
        assertThat(all).extracting(UserCouponVO::getId)
                .isSortedAccordingTo((left, right) -> right.compareTo(left));

        var available = couponApplicationService.queryUserCoupons(userId, "AVAILABLE");
        assertThat(available).isNotEmpty();
        assertThat(available).allMatch(item -> "AVAILABLE".equals(item.getStatus()));
        assertThat(CouponVO.class.getDeclaredFields())
                .noneMatch(field -> field.getName().equals("deleted") || field.getName().equals("version"));
        assertThat(UserCouponVO.class.getDeclaredFields())
                .noneMatch(field -> field.getName().equals("deleted") || field.getName().equals("version"));
    }

    @AfterAll
    void leavesNoCouponTestDataBehind() {
        assertThat(couponMapper.selectCount(Wrappers.<CouponEntity>lambdaQuery()
                .likeRight(CouponEntity::getCouponNo, TEST_COUPON_NO_PREFIX))).isZero();
    }

    private void assertConflict(Long userId, Long couponId) {
        assertThatThrownBy(() -> couponApplicationService.claimCoupon(userId, couponId))
                .isInstanceOf(DemoOrderBusinessException.class)
                .extracting(e -> ((DemoOrderBusinessException) e).getErrorCode())
                .isEqualTo(DemoOrderErrorCode.BUSINESS_CONFLICT);
    }

    private Long userId(String userNo) {
        UserEntity user = userMapper.selectOne(Wrappers.<UserEntity>lambdaQuery()
                .eq(UserEntity::getUserNo, userNo));
        assertThat(user).as("seed user " + userNo).isNotNull();
        return user.getId();
    }

    private Long couponId(String couponNo) {
        CouponEntity coupon = couponMapper.selectOne(Wrappers.<CouponEntity>lambdaQuery()
                .eq(CouponEntity::getCouponNo, couponNo)
                .eq(CouponEntity::getDeleted, false));
        assertThat(coupon).as("seed coupon " + couponNo).isNotNull();
        return coupon.getId();
    }

    private CouponEntity createCoupon(String name, LocalDateTime validFrom, LocalDateTime validUntil) {
        CouponEntity coupon = new CouponEntity();
        coupon.setCouponNo(TEST_COUPON_NO_PREFIX + UUID.randomUUID());
        coupon.setCouponName(name);
        coupon.setThresholdAmount(new BigDecimal("50.00"));
        coupon.setDiscountAmount(new BigDecimal("5.00"));
        coupon.setValidFrom(validFrom);
        coupon.setValidUntil(validUntil);
        coupon.setStatus("ACTIVE");
        coupon.setDeleted(false);
        assertThat(couponMapper.insert(coupon)).isEqualTo(1);
        return coupon;
    }

    private Long userCouponCount(Long userId, Long couponId) {
        return userCouponMapper.selectCount(Wrappers.<UserCouponEntity>lambdaQuery()
                .eq(UserCouponEntity::getUserId, userId)
                .eq(UserCouponEntity::getCouponId, couponId));
    }
}
