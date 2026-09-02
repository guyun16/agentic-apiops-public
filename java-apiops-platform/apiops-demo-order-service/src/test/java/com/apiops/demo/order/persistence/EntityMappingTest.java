package com.apiops.demo.order.persistence;

import com.apiops.demo.order.coupon.entity.CouponEntity;
import com.apiops.demo.order.coupon.entity.UserCouponEntity;
import com.apiops.demo.order.inventory.entity.InventoryEntity;
import com.apiops.demo.order.order.entity.OrderEntity;
import com.apiops.demo.order.order.entity.OrderItemEntity;
import com.apiops.demo.order.payment.entity.PaymentCallbackEntity;
import com.apiops.demo.order.payment.entity.PaymentEntity;
import com.apiops.demo.order.product.entity.ProductEntity;
import com.apiops.demo.order.user.entity.UserEntity;
import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableField;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import org.junit.jupiter.api.Test;

import java.lang.reflect.Field;
import java.math.BigDecimal;
import java.time.LocalDateTime;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;

class EntityMappingTest {

    private static final Map<Class<?>, String> TABLES = Map.of(
            UserEntity.class, "demo_user",
            ProductEntity.class, "demo_product",
            InventoryEntity.class, "demo_inventory",
            CouponEntity.class, "demo_coupon",
            UserCouponEntity.class, "demo_user_coupon",
            OrderEntity.class, "demo_order",
            OrderItemEntity.class, "demo_order_item",
            PaymentEntity.class, "demo_payment",
            PaymentCallbackEntity.class, "demo_payment_callback"
    );

    @Test
    void mapsEveryEntityToItsExactTableAndAutoIncrementPrimaryKey() throws Exception {
        for (Map.Entry<Class<?>, String> mapping : TABLES.entrySet()) {
            assertThat(mapping.getKey().getAnnotation(TableName.class).value())
                    .isEqualTo(mapping.getValue());

            Field id = mapping.getKey().getDeclaredField("id");
            TableId tableId = id.getAnnotation(TableId.class);
            assertThat(id.getType()).isEqualTo(Long.class);
            assertThat(tableId.value()).isEqualTo("id");
            assertThat(tableId.type()).isEqualTo(IdType.AUTO);
        }
    }

    @Test
    void mapsRepresentativeColumnsWithExactNamesAndSchemaTypes() throws Exception {
        assertField(UserEntity.class, "userNo", "user_no", String.class);
        assertField(ProductEntity.class, "salePrice", "sale_price", BigDecimal.class);
        assertField(ProductEntity.class, "version", "version", Long.class);
        assertField(ProductEntity.class, "deleted", "deleted", Boolean.class);
        assertField(InventoryEntity.class, "availableStock", "available_stock", Long.class);
        assertField(CouponEntity.class, "validUntil", "valid_until", LocalDateTime.class);
        assertField(UserCouponEntity.class, "usedAt", "used_at", LocalDateTime.class);
        assertField(OrderEntity.class, "userCouponId", "user_coupon_id", Long.class);
        assertField(OrderEntity.class, "payableAmount", "payable_amount", BigDecimal.class);
        assertField(OrderItemEntity.class, "quantity", "quantity", Integer.class);
        assertField(PaymentEntity.class, "paidAt", "paid_at", LocalDateTime.class);
        assertField(PaymentCallbackEntity.class, "resultMessage", "result_message", String.class);
        assertField(PaymentCallbackEntity.class, "processedAt", "processed_at", LocalDateTime.class);
    }

    @Test
    void givesEveryNonPrimaryKeyFieldAnExplicitColumnMapping() {
        for (Class<?> entity : TABLES.keySet()) {
            assertThat(entity.getDeclaredFields())
                    .filteredOn(field -> !field.getName().equals("id"))
                    .allSatisfy(field -> assertThat(field.getAnnotation(TableField.class)).isNotNull());
        }
    }

    private static void assertField(
            Class<?> entity, String fieldName, String columnName, Class<?> javaType) throws Exception {
        Field field = entity.getDeclaredField(fieldName);
        assertThat(field.getType()).isEqualTo(javaType);
        assertThat(field.getAnnotation(TableField.class).value()).isEqualTo(columnName);
    }
}
