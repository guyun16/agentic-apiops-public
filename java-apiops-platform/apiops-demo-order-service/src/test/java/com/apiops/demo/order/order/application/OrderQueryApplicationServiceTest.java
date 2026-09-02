package com.apiops.demo.order.order.application;

import com.apiops.demo.order.common.exception.ResourceNotFoundException;
import com.apiops.demo.order.order.domain.OrderStateTransitionPolicy;
import com.apiops.demo.order.order.entity.OrderEntity;
import com.apiops.demo.order.order.entity.OrderItemEntity;
import com.apiops.demo.order.order.enums.OrderStatus;
import com.apiops.demo.order.order.mapper.OrderItemMapper;
import com.apiops.demo.order.order.mapper.OrderMapper;
import com.apiops.demo.order.order.query.OrderPageQuery;
import com.apiops.demo.order.order.vo.OrderDetailVO;
import com.apiops.demo.order.order.vo.OrderPageVO;
import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

import java.math.BigDecimal;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
class OrderQueryApplicationServiceTest {

    @Mock
    private OrderMapper orderMapper;

    @Mock
    private OrderItemMapper orderItemMapper;

    @Test
    void detailUsesOrderItemSnapshotFields() {
        OrderEntity order = order(10L, 7L, OrderStatus.PAID.name());
        OrderItemEntity item = new OrderItemEntity();
        item.setId(100L);
        item.setOrderId(10L);
        item.setProductId(3L);
        item.setProductNoSnapshot("prd_snapshot");
        item.setProductNameSnapshot("Name at order time");
        item.setUnitPrice(new BigDecimal("12.34"));
        item.setQuantity(2);
        item.setLineAmount(new BigDecimal("24.68"));
        when(orderMapper.selectById(10L)).thenReturn(order);
        when(orderItemMapper.selectList(any())).thenReturn(List.of(item));

        OrderDetailVO detail = service().queryDetail(10L);

        assertThat(detail.getStatus()).isEqualTo(OrderStatus.PAID.name());
        assertThat(detail.getItems()).hasSize(1);
        assertThat(detail.getItems().get(0).getProductName()).isEqualTo("Name at order time");
        assertThat(detail.getItems().get(0).getUnitPrice()).isEqualByComparingTo("12.34");
        assertThat(detail.getItems().get(0).getQuantity()).isEqualTo(2);
        assertThat(detail.getItems().get(0).getLineAmount()).isEqualByComparingTo("24.68");
    }

    @Test
    void missingDetailRaisesResourceNotFound() {
        when(orderMapper.selectById(999L)).thenReturn(null);

        assertThatThrownBy(() -> service().queryDetail(999L))
                .isInstanceOf(ResourceNotFoundException.class);
    }

    @Test
    void pageMapsOrderSummariesWithoutLoadingItems() {
        OrderEntity order = order(10L, 7L, OrderStatus.PENDING_PAYMENT.name());
        Page<OrderEntity> page = new Page<>(2, 5);
        page.setTotal(6);
        page.setRecords(List.of(order));
        when(orderMapper.selectPage(any(), any())).thenReturn(page);

        OrderPageQuery query = new OrderPageQuery();
        query.setPageNo(2);
        query.setPageSize(5);
        query.setUserId(7L);
        query.setStatus(OrderStatus.PENDING_PAYMENT.name());

        OrderPageVO result = service().page(query);

        assertThat(result.getTotal()).isEqualTo(6);
        assertThat(result.getPageNo()).isEqualTo(2);
        assertThat(result.getPageSize()).isEqualTo(5);
        assertThat(result.getRecords()).hasSize(1);
        assertThat(result.getRecords().get(0).getId()).isEqualTo(10L);
        verify(orderItemMapper, never()).selectList(any());
    }

    private OrderApplicationService service() {
        return new OrderApplicationService(
                orderMapper, orderItemMapper, new OrderStateTransitionPolicy());
    }

    private OrderEntity order(Long id, Long userId, String status) {
        OrderEntity order = new OrderEntity();
        order.setId(id);
        order.setOrderNo("order_" + id);
        order.setUserId(userId);
        order.setOriginalAmount(BigDecimal.TEN);
        order.setDiscountAmount(BigDecimal.ZERO);
        order.setPayableAmount(BigDecimal.TEN);
        order.setStatus(status);
        return order;
    }
}
