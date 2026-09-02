package com.apiops.demo.order.product;

import com.apiops.demo.order.common.exception.DemoOrderBusinessException;
import com.apiops.demo.order.common.exception.DemoOrderErrorCode;
import com.apiops.demo.order.common.exception.ResourceNotFoundException;
import com.apiops.demo.order.product.application.ProductApplicationService;
import com.apiops.demo.order.product.dto.ProductPageQuery;
import com.apiops.demo.order.product.entity.ProductEntity;
import com.apiops.demo.order.product.mapper.ProductMapper;
import com.apiops.demo.order.product.vo.ProductPageVO;
import com.apiops.demo.order.product.vo.ProductVO;
import com.baomidou.mybatisplus.core.toolkit.Wrappers;
import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.TestInstance;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.test.annotation.Rollback;
import org.springframework.test.context.ActiveProfiles;
import org.springframework.transaction.annotation.Transactional;

import java.math.BigDecimal;
import java.util.UUID;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.NONE)
@ActiveProfiles("local")
@EnabledIfEnvironmentVariable(named = "APIOPS_ORDER_DB_URL", matches = ".+")
@Transactional
@Rollback
@TestInstance(TestInstance.Lifecycle.PER_CLASS)
class ProductIntegrationTest {

    private static final String TEST_PRODUCT_NO_PREFIX = "test_product_";

    @Autowired
    private ProductApplicationService productApplicationService;

    @Autowired
    private ProductMapper productMapper;

    @Test
    void createsProductAndQueriesFromDatabase() {
        String productNo = uniqueProductNo();
        ProductVO created = productApplicationService.createProduct(
                productNo, "Integration Product", new BigDecimal("12.34"), "ON_SALE");

        assertThat(created.getId()).isNotNull();
        assertThat(created.getProductNo()).isEqualTo(productNo);
        assertThat(created.getPrice()).isEqualByComparingTo("12.34");
        assertThat(created.getStatus()).isEqualTo("ON_SALE");

        ProductEntity databaseProduct = productMapper.selectById(created.getId());
        assertThat(databaseProduct).isNotNull();
        assertThat(databaseProduct.getProductNo()).isEqualTo(productNo);
        assertThat(databaseProduct.getSalePrice()).isEqualByComparingTo("12.34");
    }

    @Test
    void rejectsDuplicateProductNoAndKeepsOneRecord() {
        String productNo = uniqueProductNo();
        productApplicationService.createProduct(productNo, "First", BigDecimal.TEN, "ON_SALE");

        assertThatThrownBy(() -> productApplicationService.createProduct(
                productNo, "Second", BigDecimal.ONE, "ON_SALE"))
                .isInstanceOf(DemoOrderBusinessException.class)
                .extracting(e -> ((DemoOrderBusinessException) e).getErrorCode())
                .isEqualTo(DemoOrderErrorCode.BUSINESS_CONFLICT);
        assertThat(productMapper.selectCount(Wrappers.<ProductEntity>lambdaQuery()
                .eq(ProductEntity::getProductNo, productNo))).isEqualTo(1L);
    }

    @Test
    void rejectsInvalidStatusBeforeDatabaseInsert() {
        String productNo = uniqueProductNo();

        assertThatThrownBy(() -> productApplicationService.createProduct(
                productNo, "Invalid Status", BigDecimal.ONE, "INVALID"))
                .isInstanceOf(IllegalArgumentException.class);
        assertThat(productMapper.selectCount(Wrappers.<ProductEntity>lambdaQuery()
                .eq(ProductEntity::getProductNo, productNo))).isZero();
    }

    @Test
    void queriesProductByIdAndRejectsMissingProduct() {
        String productNo = uniqueProductNo();
        ProductVO created = productApplicationService.createProduct(
                productNo, "Query Product", BigDecimal.ONE, "ON_SALE");

        ProductVO queried = productApplicationService.queryById(created.getId());
        assertThat(queried.getProductNo()).isEqualTo(productNo);
        assertThat(queried.getProductName()).isEqualTo("Query Product");

        assertThatThrownBy(() -> productApplicationService.queryById(Long.MAX_VALUE))
                .isInstanceOf(ResourceNotFoundException.class);
    }

    @Test
    void pagesProductsWithEmptyAndFilteredConditions() {
        String prefix = uniqueProductNo();
        productApplicationService.createProduct(prefix + "_a", "Blue Widget", BigDecimal.ONE, "ON_SALE");
        productApplicationService.createProduct(prefix + "_b", "Blue Cable", BigDecimal.ONE, "OFF_SALE");

        ProductPageQuery empty = new ProductPageQuery();
        empty.setPageNo(1);
        empty.setPageSize(2);
        ProductPageVO emptyPage = productApplicationService.page(empty);
        assertThat(emptyPage.getTotal()).isGreaterThanOrEqualTo(3);
        assertThat(emptyPage.getPageNo()).isEqualTo(1);
        assertThat(emptyPage.getPageSize()).isEqualTo(2);
        assertThat(emptyPage.getRecords()).isNotEmpty();
        assertThat(emptyPage.getRecords().get(0).getId())
                .isGreaterThan(emptyPage.getRecords().get(1).getId());

        ProductPageQuery byNo = new ProductPageQuery();
        byNo.setProductNo(prefix + "_a");
        assertThat(productApplicationService.page(byNo).getRecords())
                .extracting(ProductVO::getProductNo).containsExactly(prefix + "_a");

        ProductPageQuery byName = new ProductPageQuery();
        byName.setProductName("Blue");
        assertThat(productApplicationService.page(byName).getRecords())
                .extracting(ProductVO::getProductName)
                .allMatch(name -> name.contains("Blue"));

        ProductPageQuery byStatus = new ProductPageQuery();
        byStatus.setStatus("OFF_SALE");
        assertThat(productApplicationService.page(byStatus).getRecords())
                .extracting(ProductVO::getStatus)
                .containsOnly("OFF_SALE");

        ProductPageQuery combined = new ProductPageQuery();
        combined.setProductName("Blue");
        combined.setStatus("ON_SALE");
        assertThat(productApplicationService.page(combined).getRecords())
                .extracting(ProductVO::getProductNo).containsExactly(prefix + "_a");
    }

    @Test
    void offShelfIsSuccessfulAndIdempotent() {
        ProductVO created = productApplicationService.createProduct(
                uniqueProductNo(), "Off Shelf Product", BigDecimal.ONE, "ON_SALE");

        ProductVO first = productApplicationService.offShelf(created.getId());
        assertThat(first.getStatus()).isEqualTo("OFF_SALE");
        assertThat(productMapper.selectById(created.getId()).getStatus()).isEqualTo("OFF_SALE");

        ProductVO second = productApplicationService.offShelf(created.getId());
        assertThat(second.getStatus()).isEqualTo("OFF_SALE");
    }

    @Test
    void offShelfHandlesMissingAndUnexpectedStatuses() {
        assertThatThrownBy(() -> productApplicationService.offShelf(Long.MAX_VALUE))
                .isInstanceOf(ResourceNotFoundException.class);
        ProductVO unexpectedStatus = productApplicationService.createProduct(
                uniqueProductNo(), "Unexpected Status", BigDecimal.ONE, "ON_SALE");
        assertThat(productMapper.update(Wrappers.<ProductEntity>lambdaUpdate()
                .eq(ProductEntity::getId, unexpectedStatus.getId())
                .set(ProductEntity::getStatus, "PAUSED"))).isEqualTo(1);
        assertThatThrownBy(() -> productApplicationService.offShelf(unexpectedStatus.getId()))
                .isInstanceOf(DemoOrderBusinessException.class)
                .extracting(e -> ((DemoOrderBusinessException) e).getErrorCode())
                .isEqualTo(DemoOrderErrorCode.BUSINESS_CONFLICT);
    }

    @Test
    void logicalDeleteIsHiddenFromQueryAndPageAndVOHasNoInternalFields() {
        ProductVO created = productApplicationService.createProduct(
                uniqueProductNo(), "Logical Delete Product", BigDecimal.ONE, "ON_SALE");
        assertThat(productMapper.deleteById(created.getId())).isEqualTo(1);

        assertThatThrownBy(() -> productApplicationService.queryById(created.getId()))
                .isInstanceOf(ResourceNotFoundException.class);
        ProductPageQuery query = new ProductPageQuery();
        query.setProductNo(created.getProductNo());
        assertThat(productApplicationService.page(query).getRecords()).isEmpty();
        assertThat(ProductVO.class.getDeclaredFields())
                .noneMatch(field -> field.getName().equals("deleted") || field.getName().equals("version"));
    }

    @AfterAll
    void leavesNoProductTestDataBehind() {
        assertThat(productMapper.selectCount(Wrappers.<ProductEntity>lambdaQuery()
                .likeRight(ProductEntity::getProductNo, TEST_PRODUCT_NO_PREFIX))).isZero();
    }

    private static String uniqueProductNo() {
        return TEST_PRODUCT_NO_PREFIX + UUID.randomUUID();
    }
}
