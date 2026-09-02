package com.apiops.demo.order.product.enums;

public enum ProductStatus {

    ON_SALE,
    OFF_SALE;

    public static boolean isValid(String value) {
        for (ProductStatus status : values()) {
            if (status.name().equals(value)) {
                return true;
            }
        }
        return false;
    }
}
