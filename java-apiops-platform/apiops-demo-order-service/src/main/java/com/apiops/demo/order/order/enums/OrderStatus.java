package com.apiops.demo.order.order.enums;

/**
 * Status values persisted in {@code demo_order.status}.
 *
 * <p>The enum names intentionally match the database protocol.</p>
 */
public enum OrderStatus {
    PENDING_PAYMENT,
    PAID,
    CANCELLED;

    public static OrderStatus fromDatabaseValue(String value) {
        if (value == null) {
            throw new IllegalArgumentException("order status must not be null");
        }
        try {
            return valueOf(value);
        } catch (IllegalArgumentException exception) {
            throw new IllegalArgumentException("unknown order status: " + value, exception);
        }
    }
}
