package com.apiops.demo.order.product.converter;

import com.apiops.demo.order.product.entity.ProductEntity;
import com.apiops.demo.order.product.vo.ProductVO;

public final class ProductConverter {

    private ProductConverter() {
    }

    public static ProductVO toVO(ProductEntity entity) {
        if (entity == null) {
            return null;
        }
        ProductVO vo = new ProductVO();
        vo.setId(entity.getId());
        vo.setProductNo(entity.getProductNo());
        vo.setProductName(entity.getProductName());
        vo.setPrice(entity.getSalePrice());
        vo.setStatus(entity.getStatus());
        vo.setCreatedAt(entity.getCreatedAt());
        vo.setUpdatedAt(entity.getUpdatedAt());
        return vo;
    }
}
