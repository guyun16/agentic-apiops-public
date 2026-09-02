package com.apiops.demo.order.coupon;

import com.apiops.demo.order.common.web.GlobalExceptionHandler;
import com.apiops.demo.order.coupon.application.CouponApplicationService;
import com.apiops.demo.order.coupon.vo.CouponVO;
import com.apiops.demo.order.coupon.vo.UserCouponVO;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.WebMvcTest;
import org.springframework.boot.test.context.TestConfiguration;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Import;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;

import java.math.BigDecimal;
import java.util.List;

import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

@WebMvcTest(controllers = com.apiops.demo.order.coupon.controller.CouponController.class)
@Import({GlobalExceptionHandler.class, CouponWebBoundaryTest.StubConfig.class})
class CouponWebBoundaryTest {

    @TestConfiguration
    static class StubConfig {
        @Bean
        CouponApplicationService couponApplicationService() {
            return new CouponApplicationService(null, null, null) {
                @Override
                public CouponVO queryCouponById(Long couponId) {
                    return coupon(couponId);
                }

                @Override
                public UserCouponVO claimCoupon(Long userId, Long couponId) {
                    UserCouponVO vo = new UserCouponVO();
                    vo.setId(10L);
                    vo.setUserId(userId);
                    vo.setCouponId(couponId);
                    vo.setStatus("AVAILABLE");
                    vo.setCoupon(coupon(couponId));
                    return vo;
                }

                @Override
                public List<UserCouponVO> queryUserCoupons(Long userId, String status) {
                    UserCouponVO vo = claimCoupon(userId, 1L);
                    return List.of(vo);
                }

                private CouponVO coupon(Long id) {
                    CouponVO vo = new CouponVO();
                    vo.setId(id);
                    vo.setCouponNo("cpn_test");
                    vo.setCouponName("Test Coupon");
                    vo.setThresholdAmount(BigDecimal.TEN);
                    vo.setDiscountAmount(BigDecimal.ONE);
                    vo.setStatus("ACTIVE");
                    return vo;
                }
            };
        }
    }

    @Autowired
    private MockMvc mockMvc;

    @Test
    void couponEndpointsReturnVoAndNestedTemplateData() throws Exception {
        mockMvc.perform(get("/coupons/1"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.couponNo").value("cpn_test"))
                .andExpect(jsonPath("$.data.deleted").doesNotExist());
        mockMvc.perform(post("/users/1/coupons/1"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.status").value("AVAILABLE"))
                .andExpect(jsonPath("$.data.coupon.couponNo").value("cpn_test"))
                .andExpect(jsonPath("$.data.version").doesNotExist());
        mockMvc.perform(get("/users/1/coupons?status=AVAILABLE"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data[0].userId").value(1));
    }

    @Test
    void invalidCouponParametersAreRejected() throws Exception {
        mockMvc.perform(get("/coupons/0"))
                .andExpect(status().isBadRequest());
        mockMvc.perform(post("/users/0/coupons/1")
                        .contentType(MediaType.APPLICATION_JSON))
                .andExpect(status().isBadRequest());
        mockMvc.perform(get("/users/1/coupons?status=UNKNOWN"))
                .andExpect(status().isBadRequest());
    }
}
