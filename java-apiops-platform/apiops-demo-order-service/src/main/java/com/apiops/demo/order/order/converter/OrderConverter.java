package com.apiops.demo.order.order.converter;

import com.apiops.demo.order.order.entity.OrderEntity;
import com.apiops.demo.order.order.entity.OrderItemEntity;
import com.apiops.demo.order.order.vo.OrderDetailVO;
import com.apiops.demo.order.order.vo.OrderItemVO;
import com.apiops.demo.order.order.vo.OrderSummaryVO;

import java.util.List;

public final class OrderConverter {

    private OrderConverter() {
    }

    public static OrderDetailVO toDetailVO(OrderEntity order, List<OrderItemEntity> items) {
        OrderDetailVO vo = new OrderDetailVO();
        copyOrder(order, vo);
        vo.setItems(items.stream().map(OrderConverter::toItemVO).toList());
        return vo;
    }

    public static OrderSummaryVO toSummaryVO(OrderEntity order) {
        OrderSummaryVO vo = new OrderSummaryVO();
        vo.setId(order.getId());
        vo.setOrderNo(order.getOrderNo());
        vo.setUserId(order.getUserId());
        vo.setOriginalAmount(order.getOriginalAmount());
        vo.setDiscountAmount(order.getDiscountAmount());
        vo.setPayableAmount(order.getPayableAmount());
        vo.setStatus(order.getStatus());
        vo.setCreatedAt(order.getCreatedAt());
        return vo;
    }

    private static void copyOrder(OrderEntity order, OrderDetailVO vo) {
        vo.setId(order.getId());
        vo.setOrderNo(order.getOrderNo());
        vo.setUserId(order.getUserId());
        vo.setOriginalAmount(order.getOriginalAmount());
        vo.setDiscountAmount(order.getDiscountAmount());
        vo.setPayableAmount(order.getPayableAmount());
        vo.setStatus(order.getStatus());
        vo.setCreatedAt(order.getCreatedAt());
        vo.setUpdatedAt(order.getUpdatedAt());
    }

    private static OrderItemVO toItemVO(OrderItemEntity item) {
        OrderItemVO vo = new OrderItemVO();
        vo.setId(item.getId());
        vo.setProductId(item.getProductId());
        vo.setProductNo(item.getProductNoSnapshot());
        vo.setProductName(item.getProductNameSnapshot());
        vo.setUnitPrice(item.getUnitPrice());
        vo.setQuantity(item.getQuantity());
        vo.setLineAmount(item.getLineAmount());
        return vo;
    }
}
