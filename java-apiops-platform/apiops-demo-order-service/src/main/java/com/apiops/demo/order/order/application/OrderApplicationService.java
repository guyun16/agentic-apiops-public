package com.apiops.demo.order.order.application;

import com.apiops.demo.order.common.exception.DemoOrderBusinessException;
import com.apiops.demo.order.common.exception.DemoOrderErrorCode;
import com.apiops.demo.order.common.exception.ResourceNotFoundException;
import com.apiops.demo.order.order.domain.OrderStateTransitionPolicy;
import com.apiops.demo.order.order.entity.OrderEntity;
import com.apiops.demo.order.order.entity.OrderItemEntity;
import com.apiops.demo.order.order.enums.OrderEvent;
import com.apiops.demo.order.order.enums.OrderStatus;
import com.apiops.demo.order.order.converter.OrderConverter;
import com.apiops.demo.order.order.mapper.OrderMapper;
import com.apiops.demo.order.order.mapper.OrderItemMapper;
import com.apiops.demo.order.order.query.OrderPageQuery;
import com.apiops.demo.order.order.vo.OrderDetailVO;
import com.apiops.demo.order.order.vo.OrderPageVO;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.core.toolkit.Wrappers;
import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.util.List;

/** Applies an order event using an optimistic, expected-status update. */
@Service
public class OrderApplicationService {

    private final OrderMapper orderMapper;
    private final OrderItemMapper orderItemMapper;
    private final OrderStateTransitionPolicy transitionPolicy;

    @Autowired
    public OrderApplicationService(
            OrderMapper orderMapper,
            OrderItemMapper orderItemMapper,
            OrderStateTransitionPolicy transitionPolicy
    ) {
        this.orderMapper = orderMapper;
        this.orderItemMapper = orderItemMapper;
        this.transitionPolicy = transitionPolicy;
    }

    /** Compatibility constructor for state-machine unit callers. */
    public OrderApplicationService(
            OrderMapper orderMapper,
            OrderStateTransitionPolicy transitionPolicy
    ) {
        this(orderMapper, null, transitionPolicy);
    }

    public OrderDetailVO queryDetail(Long orderId) {
        OrderEntity order = findOrder(orderId);
        List<OrderItemEntity> items = requireOrderItemMapper().selectList(
                Wrappers.<OrderItemEntity>lambdaQuery()
                        .eq(OrderItemEntity::getOrderId, orderId)
                        .orderByAsc(OrderItemEntity::getId));
        return OrderConverter.toDetailVO(order, items);
    }

    /** Alias matching the existing single-resource query convention. */
    public OrderDetailVO queryById(Long orderId) {
        return queryDetail(orderId);
    }

    public OrderPageVO page(OrderPageQuery query) {
        LambdaQueryWrapper<OrderEntity> wrapper = Wrappers.lambdaQuery();
        wrapper.eq(query.getUserId() != null, OrderEntity::getUserId, query.getUserId())
                .eq(query.getStatus() != null && !query.getStatus().isBlank(),
                        OrderEntity::getStatus, query.getStatus())
                .orderByDesc(OrderEntity::getCreatedAt)
                .orderByDesc(OrderEntity::getId);

        Page<OrderEntity> page = orderMapper.selectPage(
                new Page<>(query.getPageNo(), query.getPageSize()), wrapper);
        OrderPageVO result = new OrderPageVO();
        result.setTotal(page.getTotal());
        result.setPageNo(page.getCurrent());
        result.setPageSize(page.getSize());
        result.setRecords(page.getRecords().stream()
                .map(OrderConverter::toSummaryVO)
                .toList());
        return result;
    }

    @Transactional
    public OrderStatus transition(Long orderId, OrderEvent event) {
        OrderEntity currentOrder = findOrder(orderId);
        OrderStatus currentStatus = parseStatus(currentOrder.getStatus());
        OrderStatus targetStatus = transitionPolicy.targetStatus(currentStatus, event);

        int rows = orderMapper.updateStatusIfExpected(
                orderId,
                currentStatus.name(),
                targetStatus.name()
        );
        if (rows == 1) {
            return targetStatus;
        }

        // A failed conditional update is either a missing row or a concurrent state change.
        OrderEntity latestOrder = orderMapper.selectById(orderId);
        if (latestOrder == null) {
            throw new ResourceNotFoundException("order not found");
        }
        throw statusConflict();
    }

    private OrderEntity findOrder(Long orderId) {
        OrderEntity order = orderMapper.selectById(orderId);
        if (order == null) {
            throw new ResourceNotFoundException("order not found");
        }
        return order;
    }

    private OrderItemMapper requireOrderItemMapper() {
        if (orderItemMapper == null) {
            throw new IllegalStateException("OrderItemMapper is required for order detail queries");
        }
        return orderItemMapper;
    }

    private OrderStatus parseStatus(String status) {
        try {
            return OrderStatus.fromDatabaseValue(status);
        } catch (IllegalArgumentException exception) {
            throw statusConflict();
        }
    }

    private DemoOrderBusinessException statusConflict() {
        return new DemoOrderBusinessException(
                DemoOrderErrorCode.BUSINESS_CONFLICT,
                "order status conflict"
        );
    }
}
