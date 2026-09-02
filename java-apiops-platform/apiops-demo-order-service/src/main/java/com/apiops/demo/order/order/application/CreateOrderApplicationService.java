package com.apiops.demo.order.order.application;

import com.apiops.demo.order.common.exception.DemoOrderBusinessException;
import com.apiops.demo.order.common.exception.DemoOrderErrorCode;
import com.apiops.demo.order.common.exception.ResourceNotFoundException;
import com.apiops.demo.order.coupon.entity.CouponEntity;
import com.apiops.demo.order.coupon.entity.UserCouponEntity;
import com.apiops.demo.order.coupon.mapper.CouponMapper;
import com.apiops.demo.order.coupon.mapper.UserCouponMapper;
import com.apiops.demo.order.inventory.application.InventoryApplicationService;
import com.apiops.demo.order.inventory.application.InventoryDeductCommand;
import com.apiops.demo.order.order.converter.OrderConverter;
import com.apiops.demo.order.order.domain.OrderPricingCalculator;
import com.apiops.demo.order.order.dto.CreateOrderItemRequest;
import com.apiops.demo.order.order.dto.CreateOrderRequest;
import com.apiops.demo.order.order.entity.OrderEntity;
import com.apiops.demo.order.order.entity.OrderItemEntity;
import com.apiops.demo.order.order.enums.OrderStatus;
import com.apiops.demo.order.order.mapper.OrderItemMapper;
import com.apiops.demo.order.order.mapper.OrderMapper;
import com.apiops.demo.order.order.vo.OrderDetailVO;
import com.apiops.demo.order.payment.entity.PaymentEntity;
import com.apiops.demo.order.payment.mapper.PaymentMapper;
import com.apiops.demo.order.product.entity.ProductEntity;
import com.apiops.demo.order.product.mapper.ProductMapper;
import com.apiops.demo.order.user.mapper.UserMapper;
import com.baomidou.mybatisplus.core.toolkit.Wrappers;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.math.BigDecimal;
import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.HashMap;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.UUID;

@Service
public class CreateOrderApplicationService {

    private static final String PRODUCT_ON_SALE = "ON_SALE";
    private static final String USER_COUPON_AVAILABLE = "AVAILABLE";
    private static final String COUPON_ACTIVE = "ACTIVE";
    private static final String PAYMENT_PENDING = "PENDING";

    private final UserMapper userMapper;
    private final ProductMapper productMapper;
    private final InventoryApplicationService inventoryApplicationService;
    private final CouponMapper couponMapper;
    private final UserCouponMapper userCouponMapper;
    private final OrderMapper orderMapper;
    private final OrderItemMapper orderItemMapper;
    private final PaymentMapper paymentMapper;

    @Autowired
    public CreateOrderApplicationService(
            UserMapper userMapper,
            ProductMapper productMapper,
            InventoryApplicationService inventoryApplicationService,
            CouponMapper couponMapper,
            UserCouponMapper userCouponMapper,
            OrderMapper orderMapper,
            OrderItemMapper orderItemMapper,
            PaymentMapper paymentMapper
    ) {
        this.userMapper = userMapper;
        this.productMapper = productMapper;
        this.inventoryApplicationService = inventoryApplicationService;
        this.couponMapper = couponMapper;
        this.userCouponMapper = userCouponMapper;
        this.orderMapper = orderMapper;
        this.orderItemMapper = orderItemMapper;
        this.paymentMapper = paymentMapper;
    }

    @Transactional
    public OrderDetailVO createOrder(CreateOrderRequest request) {
        validateRequest(request);
        validateUser(request.getUserId());

        List<CreateOrderItemRequest> sortedItems = sortAndValidateItems(request.getItems());
        Map<Long, ProductEntity> products = loadSaleProducts(sortedItems);
        List<PreparedItem> preparedItems = prepareItems(sortedItems, products);

        BigDecimal originalAmount = OrderPricingCalculator.originalAmount(
                preparedItems.stream().map(PreparedItem::lineAmount).toList());
        CouponApplication couponApplication = resolveCoupon(request.getCouponId(),
                request.getUserId(), originalAmount);
        BigDecimal discountAmount = couponApplication.discountAmount();
        BigDecimal payableAmount = OrderPricingCalculator.payableAmount(
                originalAmount, discountAmount);

        inventoryApplicationService.deductBatch(preparedItems.stream()
                .map(item -> new InventoryDeductCommand(
                        item.product().getId(), item.request().getQuantity().longValue()))
                .toList());

        if (couponApplication.userCoupon() != null
                && consumeUserCoupon(
                        couponApplication.userCoupon().getId(), request.getUserId()) != 1) {
            throw businessConflict("user coupon is no longer available");
        }

        LocalDateTime now = LocalDateTime.now();
        OrderEntity order = new OrderEntity();
        order.setOrderNo("ord_" + UUID.randomUUID());
        order.setUserId(request.getUserId());
        order.setUserCouponId(couponApplication.userCoupon() == null
                ? null : couponApplication.userCoupon().getId());
        order.setOriginalAmount(originalAmount);
        order.setDiscountAmount(discountAmount);
        order.setPayableAmount(payableAmount);
        order.setStatus(OrderStatus.PENDING_PAYMENT.name());
        order.setCreatedAt(now);
        order.setUpdatedAt(now);
        requireInserted(orderMapper.insert(order), "order");

        List<OrderItemEntity> orderItems = new ArrayList<>();
        for (PreparedItem preparedItem : preparedItems) {
            OrderItemEntity orderItem = new OrderItemEntity();
            orderItem.setOrderId(order.getId());
            orderItem.setProductId(preparedItem.product().getId());
            orderItem.setProductNoSnapshot(preparedItem.product().getProductNo());
            orderItem.setProductNameSnapshot(preparedItem.product().getProductName());
            orderItem.setUnitPrice(preparedItem.product().getSalePrice());
            orderItem.setQuantity(preparedItem.request().getQuantity());
            orderItem.setLineAmount(preparedItem.lineAmount());
            orderItem.setCreatedAt(now);
            orderItem.setUpdatedAt(now);
            requireInserted(insertOrderItem(orderItem), "order item");
            orderItems.add(orderItem);
        }

        PaymentEntity payment = new PaymentEntity();
        payment.setPaymentNo("pay_" + UUID.randomUUID());
        payment.setOrderId(order.getId());
        payment.setPaymentAmount(payableAmount);
        payment.setStatus(PAYMENT_PENDING);
        payment.setPaidAt(null);
        payment.setCreatedAt(now);
        payment.setUpdatedAt(now);
        requireInserted(insertPayment(payment), "payment");

        return OrderConverter.toDetailVO(order, orderItems);
    }

    private void validateRequest(CreateOrderRequest request) {
        if (request == null || request.getUserId() == null || request.getUserId() <= 0
                || request.getItems() == null || request.getItems().isEmpty()) {
            throw new IllegalArgumentException("userId and items are required");
        }
    }

    private void validateUser(Long userId) {
        if (userMapper.selectById(userId) == null) {
            throw new ResourceNotFoundException("user id " + userId + " not found");
        }
    }

    private List<CreateOrderItemRequest> sortAndValidateItems(
            List<CreateOrderItemRequest> requestItems) {
        Set<Long> productIds = new HashSet<>();
        List<CreateOrderItemRequest> sortedItems = new ArrayList<>(requestItems);
        for (CreateOrderItemRequest item : sortedItems) {
            if (item == null || item.getProductId() == null || item.getProductId() <= 0
                    || item.getQuantity() == null || item.getQuantity() <= 0) {
                throw new IllegalArgumentException("productId and quantity must be positive");
            }
            if (!productIds.add(item.getProductId())) {
                throw businessConflict("duplicate productId: " + item.getProductId());
            }
        }
        sortedItems.sort(Comparator.comparing(CreateOrderItemRequest::getProductId));
        return sortedItems;
    }

    private Map<Long, ProductEntity> loadSaleProducts(
            List<CreateOrderItemRequest> requestItems) {
        List<Long> productIds = requestItems.stream()
                .map(CreateOrderItemRequest::getProductId)
                .toList();
        List<ProductEntity> existingProducts = productMapper.selectList(
                Wrappers.<ProductEntity>lambdaQuery().in(ProductEntity::getId, productIds));
        Map<Long, ProductEntity> products = new HashMap<>();
        for (ProductEntity product : existingProducts) {
            products.put(product.getId(), product);
        }
        for (Long productId : productIds) {
            ProductEntity product = products.get(productId);
            if (product == null) {
                throw new ResourceNotFoundException("product id " + productId + " not found");
            }
            if (!PRODUCT_ON_SALE.equals(product.getStatus())) {
                throw businessConflict("product id " + productId + " is not on sale");
            }
        }
        return products;
    }

    private List<PreparedItem> prepareItems(
            List<CreateOrderItemRequest> requestItems,
            Map<Long, ProductEntity> products
    ) {
        return requestItems.stream()
                .map(item -> {
                    ProductEntity product = products.get(item.getProductId());
                    BigDecimal lineAmount = product.getSalePrice()
                            .multiply(BigDecimal.valueOf(item.getQuantity()));
                    return new PreparedItem(item, product, lineAmount);
                })
                .toList();
    }

    private CouponApplication resolveCoupon(Long couponTemplateId, Long userId,
                                            BigDecimal originalAmount) {
        if (couponTemplateId == null) {
            return new CouponApplication(null, BigDecimal.ZERO);
        }

        CouponEntity coupon = couponMapper.selectOne(
                Wrappers.<CouponEntity>lambdaQuery()
                        .eq(CouponEntity::getId, couponTemplateId)
                        .eq(CouponEntity::getDeleted, false));
        if (coupon == null) {
            throw new ResourceNotFoundException(
                    "coupon id " + couponTemplateId + " not found");
        }
        if (!COUPON_ACTIVE.equals(coupon.getStatus())) {
            throw businessConflict("coupon id " + couponTemplateId + " is not active");
        }
        LocalDateTime now = LocalDateTime.now();
        if (now.isBefore(coupon.getValidFrom()) || now.isAfter(coupon.getValidUntil())) {
            throw businessConflict(
                    "coupon id " + couponTemplateId + " is outside its validity period");
        }

        UserCouponEntity userCoupon = userCouponMapper.selectOne(
                Wrappers.<UserCouponEntity>lambdaQuery()
                        .eq(UserCouponEntity::getUserId, userId)
                        .eq(UserCouponEntity::getCouponId, couponTemplateId)
                        .eq(UserCouponEntity::getStatus, USER_COUPON_AVAILABLE));
        if (userCoupon == null) {
            throw businessConflict("user coupon is not available");
        }

        BigDecimal discountAmount = OrderPricingCalculator.discountAmount(
                originalAmount, coupon.getThresholdAmount(), coupon.getDiscountAmount());
        return new CouponApplication(userCoupon, discountAmount);
    }

    private static void requireInserted(int rows, String resource) {
        if (rows != 1) {
            throw new IllegalStateException("expected one " + resource + " row, got " + rows);
        }
    }

    protected int consumeUserCoupon(Long userCouponId, Long userId) {
        return userCouponMapper.consumeIfAvailable(userCouponId, userId);
    }

    protected int insertOrderItem(OrderItemEntity orderItem) {
        return orderItemMapper.insert(orderItem);
    }

    protected int insertPayment(PaymentEntity payment) {
        return paymentMapper.insert(payment);
    }

    private static DemoOrderBusinessException businessConflict(String message) {
        return new DemoOrderBusinessException(DemoOrderErrorCode.BUSINESS_CONFLICT, message);
    }

    private record PreparedItem(
            CreateOrderItemRequest request,
            ProductEntity product,
            BigDecimal lineAmount
    ) {
    }

    private record CouponApplication(UserCouponEntity userCoupon, BigDecimal discountAmount) {
    }
}
