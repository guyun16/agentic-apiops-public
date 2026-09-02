package com.apiops.demo.order;

import com.apiops.demo.order.coupon.mapper.CouponMapper;
import com.apiops.demo.order.coupon.mapper.UserCouponMapper;
import com.apiops.demo.order.inventory.mapper.InventoryMapper;
import com.apiops.demo.order.product.mapper.ProductMapper;
import com.apiops.demo.order.order.mapper.OrderMapper;
import com.apiops.demo.order.order.mapper.OrderItemMapper;
import com.apiops.demo.order.payment.mapper.PaymentMapper;
import com.apiops.demo.order.user.mapper.UserMapper;
import org.junit.jupiter.api.Test;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.test.context.ActiveProfiles;
import org.springframework.test.context.bean.override.mockito.MockitoBean;

@SpringBootTest
@ActiveProfiles("test")
class DemoOrderApplicationTest {

    @MockitoBean
    private UserMapper userMapper;

    @MockitoBean
    private ProductMapper productMapper;

    @MockitoBean
    private CouponMapper couponMapper;

    @MockitoBean
    private UserCouponMapper userCouponMapper;

    @MockitoBean
    private InventoryMapper inventoryMapper;

    @MockitoBean
    private OrderMapper orderMapper;

    @MockitoBean
    private OrderItemMapper orderItemMapper;

    @MockitoBean
    private PaymentMapper paymentMapper;

    @Test
    void contextLoads() {
    }
}
