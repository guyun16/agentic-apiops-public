package com.apiops.demo.order.product.application;

import com.apiops.demo.order.common.exception.DemoOrderBusinessException;
import com.apiops.demo.order.common.exception.DemoOrderErrorCode;
import com.apiops.demo.order.common.exception.ResourceNotFoundException;
import com.apiops.demo.order.product.converter.ProductConverter;
import com.apiops.demo.order.product.dto.ProductPageQuery;
import com.apiops.demo.order.product.entity.ProductEntity;
import com.apiops.demo.order.product.enums.ProductStatus;
import com.apiops.demo.order.product.mapper.ProductMapper;
import com.apiops.demo.order.product.vo.ProductPageVO;
import com.apiops.demo.order.product.vo.ProductVO;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.core.conditions.update.LambdaUpdateWrapper;
import com.baomidou.mybatisplus.core.toolkit.Wrappers;
import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import org.springframework.dao.DuplicateKeyException;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.util.List;

@Service
public class ProductApplicationService {

    private static final String ON_SALE = ProductStatus.ON_SALE.name();
    private static final String OFF_SALE = ProductStatus.OFF_SALE.name();

    private final ProductMapper productMapper;

    public ProductApplicationService(ProductMapper productMapper) {
        this.productMapper = productMapper;
    }

    @Transactional
    public ProductVO createProduct(String productNo, String productName,
                                   java.math.BigDecimal price, String status) {
        String normalizedStatus = status == null ? ON_SALE : status;
        if (!ProductStatus.isValid(normalizedStatus)) {
            throw new IllegalArgumentException("unsupported product status: " + status);
        }

        Long existingCount = productMapper.selectCount(
                Wrappers.<ProductEntity>lambdaQuery()
                        .eq(ProductEntity::getProductNo, productNo));
        if (existingCount != null && existingCount > 0) {
            throw duplicateProductNo(productNo);
        }

        ProductEntity entity = new ProductEntity();
        entity.setProductNo(productNo);
        entity.setProductName(productName);
        entity.setSalePrice(price);
        entity.setStatus(normalizedStatus);
        try {
            productMapper.insert(entity);
        } catch (DuplicateKeyException exception) {
            // demo_product has exactly one unique constraint: uk_demo_product_product_no.
            throw duplicateProductNo(productNo);
        }
        return ProductConverter.toVO(entity);
    }

    public ProductVO queryById(Long id) {
        ProductEntity entity = productMapper.selectById(id);
        if (entity == null) {
            throw new ResourceNotFoundException("product id " + id + " not found");
        }
        return ProductConverter.toVO(entity);
    }

    public ProductPageVO page(ProductPageQuery query) {
        LambdaQueryWrapper<ProductEntity> wrapper = Wrappers.lambdaQuery();
        wrapper.eq(query.getProductNo() != null && !query.getProductNo().isBlank(),
                        ProductEntity::getProductNo, query.getProductNo())
                .like(query.getProductName() != null && !query.getProductName().isBlank(),
                        ProductEntity::getProductName, query.getProductName())
                .eq(query.getStatus() != null && !query.getStatus().isBlank(),
                        ProductEntity::getStatus, query.getStatus())
                .orderByDesc(ProductEntity::getId);

        Page<ProductEntity> page = productMapper.selectPage(
                new Page<>(query.getPageNo(), query.getPageSize()), wrapper);
        List<ProductVO> records = page.getRecords().stream()
                .map(ProductConverter::toVO)
                .toList();
        ProductPageVO result = new ProductPageVO();
        result.setTotal(page.getTotal());
        result.setPageNo(page.getCurrent());
        result.setPageSize(page.getSize());
        result.setRecords(records);
        return result;
    }

    @Transactional
    public ProductVO offShelf(Long id) {
        LambdaUpdateWrapper<ProductEntity> wrapper =
                Wrappers.<ProductEntity>lambdaUpdate()
                        .eq(ProductEntity::getId, id)
                        .eq(ProductEntity::getStatus, ON_SALE)
                        .set(ProductEntity::getStatus, OFF_SALE);
        int rows = productMapper.update(wrapper);
        if (rows == 1) {
            return queryById(id);
        }

        ProductEntity current = productMapper.selectById(id);
        if (current == null) {
            throw new ResourceNotFoundException("product id " + id + " not found");
        }
        if (OFF_SALE.equals(current.getStatus())) {
            return ProductConverter.toVO(current);
        }
        throw new DemoOrderBusinessException(
                DemoOrderErrorCode.BUSINESS_CONFLICT,
                "product id " + id + " is in unexpected status, off-shelf failed");
    }

    private static DemoOrderBusinessException duplicateProductNo(String productNo) {
        return new DemoOrderBusinessException(
                DemoOrderErrorCode.BUSINESS_CONFLICT,
                "product with productNo " + productNo + " already exists");
    }
}
