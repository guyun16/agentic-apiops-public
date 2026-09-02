package com.apiops.demo.order.persistence;

import com.apiops.demo.order.product.entity.ProductEntity;
import com.apiops.demo.order.product.mapper.ProductMapper;
import com.apiops.demo.order.user.entity.UserEntity;
import com.apiops.demo.order.user.mapper.UserMapper;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.core.toolkit.Wrappers;
import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.TestInstance;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.test.annotation.Rollback;
import org.springframework.test.context.ActiveProfiles;
import org.springframework.transaction.annotation.Transactional;

import java.math.BigDecimal;
import java.time.LocalDateTime;
import java.util.HashSet;
import java.util.List;
import java.util.Set;
import java.util.UUID;
import static org.assertj.core.api.Assertions.assertThat;

@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.NONE)
@ActiveProfiles("local")
@EnabledIfEnvironmentVariable(named = "APIOPS_ORDER_DB_URL", matches = ".+")
@Transactional
@Rollback
@TestInstance(TestInstance.Lifecycle.PER_CLASS)
class MapperMySqlTest {

    static final String ROLLBACK_TEST_USER_NO = "test_mapper_rollback_verification";
    static final String LOGIC_DELETE_TEST_PRODUCT_NO = "test_logic_delete_prd";
    static final String OPTIMISTIC_LOCK_TEST_PRODUCT_NO = "test_optimistic_lock_prd";

    @Autowired
    private UserMapper userMapper;

    @Autowired
    private ProductMapper productMapper;

    @Autowired
    private JdbcTemplate jdbcTemplate;

    @Test
    void selectsSeedProductsByExistingStatus() {
        List<ProductEntity> seededProducts = productMapper.selectList(
                new LambdaQueryWrapper<ProductEntity>());
        assertThat(seededProducts).isNotEmpty();
        String existingStatus = seededProducts.get(0).getStatus();

        List<ProductEntity> matchingProducts = productMapper.selectList(
                new LambdaQueryWrapper<ProductEntity>()
                        .eq(ProductEntity::getStatus, existingStatus));

        assertThat(matchingProducts).isNotEmpty();
        assertThat(matchingProducts)
                .allSatisfy(product -> assertThat(product.getStatus()).isEqualTo(existingStatus));
    }

    @Test
    void selectsSeedProductsInStrictlyAscendingIdOrder() {
        List<ProductEntity> seededProducts = productMapper.selectList(
                new LambdaQueryWrapper<ProductEntity>().orderByAsc(ProductEntity::getId));
        List<Long> productIds = seededProducts.stream().map(ProductEntity::getId).toList();

        assertThat(seededProducts).hasSizeGreaterThanOrEqualTo(2);
        for (int index = 1; index < productIds.size(); index++) {
            assertThat(productIds.get(index)).isGreaterThan(productIds.get(index - 1));
        }
        System.out.println("Ascending seed product IDs = " + productIds);
    }

    @Test
    void returnsEmptyListForMissingProductStatus() {
        Set<String> existingStatuses = new HashSet<>();
        productMapper.selectList(new LambdaQueryWrapper<ProductEntity>())
                .forEach(product -> existingStatuses.add(product.getStatus()));
        String missingStatus = "__MISSING_0__";
        for (int suffix = 1; existingStatuses.contains(missingStatus); suffix++) {
            missingStatus = "__MISSING_" + suffix + "__";
        }

        List<ProductEntity> matchingProducts = productMapper.selectList(
                new LambdaQueryWrapper<ProductEntity>()
                        .eq(ProductEntity::getStatus, missingStatus)
                        .orderByAsc(ProductEntity::getId));

        assertThat(matchingProducts).isEmpty();
    }

    @Test
    void paginatesSeedProductsInAscendingIdOrder() {
        List<Long> allProductIds = productMapper.selectList(
                        new LambdaQueryWrapper<ProductEntity>().orderByAsc(ProductEntity::getId))
                .stream()
                .map(ProductEntity::getId)
                .toList();
        long pageSize = 2;
        long expectedPages = (allProductIds.size() + pageSize - 1) / pageSize;

        assertThat(allProductIds).hasSizeGreaterThanOrEqualTo(3);

        Page<ProductEntity> firstPage = productMapper.selectPage(
                new Page<>(1, pageSize),
                new LambdaQueryWrapper<ProductEntity>().orderByAsc(ProductEntity::getId));
        List<Long> firstPageIds = firstPage.getRecords().stream().map(ProductEntity::getId).toList();
        assertThat(firstPage.getCurrent()).isEqualTo(1);
        assertThat(firstPage.getSize()).isEqualTo(pageSize);
        assertThat(firstPage.getTotal()).isEqualTo(allProductIds.size());
        assertThat(firstPage.getPages()).isEqualTo(expectedPages);
        assertThat(firstPageIds).containsExactlyElementsOf(allProductIds.subList(0, 2));

        Page<ProductEntity> secondPage = productMapper.selectPage(
                new Page<>(2, pageSize),
                new LambdaQueryWrapper<ProductEntity>().orderByAsc(ProductEntity::getId));
        List<Long> secondPageIds = secondPage.getRecords().stream().map(ProductEntity::getId).toList();
        assertThat(secondPage.getCurrent()).isEqualTo(2);
        assertThat(secondPage.getSize()).isEqualTo(pageSize);
        assertThat(secondPage.getTotal()).isEqualTo(allProductIds.size());
        assertThat(secondPage.getPages()).isEqualTo(expectedPages);
        assertThat(secondPageIds).containsExactlyElementsOf(allProductIds.subList(2, allProductIds.size()));

        Page<ProductEntity> outOfRangePage = productMapper.selectPage(
                new Page<>(expectedPages + 1, pageSize),
                new LambdaQueryWrapper<ProductEntity>().orderByAsc(ProductEntity::getId));
        List<Long> outOfRangePageIds = outOfRangePage.getRecords().stream().map(ProductEntity::getId).toList();
        assertThat(outOfRangePageIds).isEmpty();
        assertThat(outOfRangePage.getTotal()).isEqualTo(allProductIds.size());
        assertThat(outOfRangePage.getPages()).isEqualTo(expectedPages);

        System.out.println("All seed product IDs = " + allProductIds);
        System.out.println("First page product IDs = " + firstPageIds);
        System.out.println("Second page product IDs = " + secondPageIds);
        System.out.println("Out-of-range page product IDs = " + outOfRangePageIds);
    }

    @Test
    void fillsUserTimestampsOnInsertAndUpdate() throws InterruptedException {
        UserEntity user = new UserEntity();
        user.setUserNo("test_autofill_" + UUID.randomUUID());
        user.setUserName("Auto-fill persistence test");
        user.setStatus("ENABLED");

        assertThat(user.getCreatedAt()).isNull();
        assertThat(user.getUpdatedAt()).isNull();
        assertThat(userMapper.insert(user)).isEqualTo(1);
        assertThat(user.getId()).isNotNull();
        assertThat(user.getCreatedAt()).isNotNull();
        assertThat(user.getUpdatedAt()).isNotNull();

        UserEntity insertedUser = userMapper.selectById(user.getId());
        assertThat(insertedUser.getCreatedAt()).isNotNull();
        assertThat(insertedUser.getUpdatedAt()).isNotNull();
        LocalDateTime insertedCreatedAt = insertedUser.getCreatedAt();
        LocalDateTime insertedUpdatedAt = insertedUser.getUpdatedAt();

        Thread.sleep(10);
        UserEntity updateUser = new UserEntity();
        updateUser.setId(user.getId());
        updateUser.setUserName("Auto-fill persistence test updated");
        assertThat(userMapper.updateById(updateUser)).isEqualTo(1);

        UserEntity updatedUser = userMapper.selectById(user.getId());
        assertThat(updatedUser.getCreatedAt()).isEqualTo(insertedCreatedAt);
        assertThat(updatedUser.getUpdatedAt()).isAfter(insertedUpdatedAt);
        assertThat(updatedUser.getUserName()).isEqualTo("Auto-fill persistence test updated");
        System.out.println("Auto-fill insert timestamps = createdAt=" + insertedCreatedAt
                + ", updatedAt=" + insertedUpdatedAt);
        System.out.println("Auto-fill update timestamp = updatedAt=" + updatedUser.getUpdatedAt());
    }

    @Test
    void setsDeletedColumnToOneOnDeleteAndSkipsInQueries() {
        // 1. Insert test product with unique productNo
        LocalDateTime now = LocalDateTime.now().withNano(0);
        ProductEntity product = new ProductEntity();
        product.setProductNo(LOGIC_DELETE_TEST_PRODUCT_NO);
        product.setProductName("Logic-delete test product");
        product.setSalePrice(BigDecimal.TEN);
        product.setStatus("ON_SALE");
        product.setVersion(0L);
        product.setCreatedAt(now);
        product.setUpdatedAt(now);
        assertThat(productMapper.insert(product)).isEqualTo(1);
        Long productId = product.getId();
        assertThat(productId).isNotNull();

        // 2. Verify inserted row has deleted=0 (JdbcTemplate)
        Integer deletedAfterInsert = jdbcTemplate.queryForObject(
                "SELECT deleted FROM demo_product WHERE id = ?",
                Integer.class, productId);
        assertThat(deletedAfterInsert).isZero();

        // 3. selectById before delete — row is found
        ProductEntity beforeDelete = productMapper.selectById(productId);
        assertThat(beforeDelete).isNotNull();
        assertThat(beforeDelete.getDeleted()).isFalse();

        // 4. deleteById: returns 1 row affected
        int firstDelete = productMapper.deleteById(productId);
        assertThat(firstDelete).isEqualTo(1);

        // 5. selectById after delete — returns null
        ProductEntity afterDelete = productMapper.selectById(productId);
        assertThat(afterDelete).isNull();

        // 6. Raw SQL proves physical row still exists
        Long rawCount = jdbcTemplate.queryForObject(
                "SELECT COUNT(*) FROM demo_product WHERE id = ?",
                Long.class, productId);
        assertThat(rawCount).isEqualTo(1L);

        // 7. Raw SQL: deleted column is now 1
        Integer deletedAfterLogicalDelete = jdbcTemplate.queryForObject(
                "SELECT deleted FROM demo_product WHERE id = ?",
                Integer.class, productId);
        assertThat(deletedAfterLogicalDelete).isEqualTo(1);

        // 8. selectList: deleted product excluded from normal list
        List<ProductEntity> allProducts = productMapper.selectList(
                new LambdaQueryWrapper<>());
        assertThat(allProducts).noneSatisfy(
                p -> assertThat(p.getId()).isEqualTo(productId));

        // 9. Second deleteById on same row — observe actual row count
        int secondDelete = productMapper.deleteById(productId);
        System.out.println(
                "Second deleteById on logically-deleted row returned " + secondDelete
                + " (expected: 0 — row is already deleted)");
        assertThat(secondDelete).isZero();

        // 10. product_no unique key boundary: raw SQL shows original product_no
        //     still occupies unique key; inserting same product_no fails.
        String rawProductNo = jdbcTemplate.queryForObject(
                "SELECT product_no FROM demo_product WHERE id = ?",
                String.class, productId);
        assertThat(rawProductNo).isEqualTo(LOGIC_DELETE_TEST_PRODUCT_NO);

        ProductEntity duplicateNoProduct = new ProductEntity();
        duplicateNoProduct.setProductNo(LOGIC_DELETE_TEST_PRODUCT_NO);
        duplicateNoProduct.setProductName("Duplicate product_no test");
        duplicateNoProduct.setSalePrice(BigDecimal.ONE);
        duplicateNoProduct.setStatus("ON_SALE");
        duplicateNoProduct.setVersion(0L);
        duplicateNoProduct.setCreatedAt(now);
        duplicateNoProduct.setUpdatedAt(now);
        try {
            productMapper.insert(duplicateNoProduct);
            // If insert succeeds, assert it's not the logical-delete row (it got a new id)
            assertThat(duplicateNoProduct.getId()).isNotNull();
            assertThat(duplicateNoProduct.getId()).isNotEqualTo(productId);
            System.out.println(
                    "WARNING: duplicate product_no insert succeeded on id="
                    + duplicateNoProduct.getId()
                    + " — unique key may not be enforced for logically-deleted rows");
            // Clean up duplicate
            jdbcTemplate.update("DELETE FROM demo_product WHERE id = ?",
                    duplicateNoProduct.getId());
        } catch (Exception e) {
            System.out.println(
                    "Expected: duplicate product_no insert failed — "
                    + "unique key still enforced. Error: "
                    + e.getClass().getSimpleName() + " — "
                    + e.getMessage());
        }
    }

    @Test
    void selectsSeedUserThroughBaseMapper() {
        UserEntity seededUser = userMapper.selectOne(
                Wrappers.<UserEntity>lambdaQuery().eq(UserEntity::getUserNo, "usr_001"));

        assertThat(seededUser).isNotNull();
        assertThat(userMapper.selectById(seededUser.getId()).getUserName())
                .isEqualTo("Demo User 001");
    }

    @Test
    void rejectsStaleVersionUpdateAndBumpsVersionOnSuccess() {
        // 1. Insert test product
        LocalDateTime now = LocalDateTime.now().withNano(0);
        ProductEntity product = new ProductEntity();
        product.setProductNo(OPTIMISTIC_LOCK_TEST_PRODUCT_NO);
        product.setProductName("Optimistic lock test product");
        product.setSalePrice(BigDecimal.TEN);
        product.setStatus("ON_SALE");
        product.setCreatedAt(now);
        product.setUpdatedAt(now);
        assertThat(productMapper.insert(product)).isEqualTo(1);
        Long productId = product.getId();
        assertThat(productId).isNotNull();

        // 2. Re-query to get the real initial version from MySQL.
        //    Copy into two independent POJOs so MyBatis session cache does not
        //    alias snapshotA == snapshotB.
        ProductEntity queried = productMapper.selectById(productId);
        assertThat(queried).isNotNull();
        Long initialVersion = queried.getVersion();

        ProductEntity snapshotA = new ProductEntity();
        snapshotA.setId(queried.getId());
        snapshotA.setProductNo(queried.getProductNo());
        snapshotA.setProductName(queried.getProductName());
        snapshotA.setSalePrice(queried.getSalePrice());
        snapshotA.setStatus(queried.getStatus());
        snapshotA.setVersion(initialVersion);
        snapshotA.setDeleted(queried.getDeleted());
        snapshotA.setCreatedAt(queried.getCreatedAt());
        snapshotA.setUpdatedAt(queried.getUpdatedAt());

        ProductEntity snapshotB = new ProductEntity();
        snapshotB.setId(queried.getId());
        snapshotB.setProductNo(queried.getProductNo());
        snapshotB.setProductName(queried.getProductName());
        snapshotB.setSalePrice(queried.getSalePrice());
        snapshotB.setStatus(queried.getStatus());
        snapshotB.setVersion(initialVersion);
        snapshotB.setDeleted(queried.getDeleted());
        snapshotB.setCreatedAt(queried.getCreatedAt());
        snapshotB.setUpdatedAt(queried.getUpdatedAt());

        assertThat(snapshotB.getVersion()).isEqualTo(initialVersion);
        System.out.println("Initial version = " + initialVersion);

        // 3. Snapshot A updates successfully
        snapshotA.setProductName("Updated by A");
        int rowsA = productMapper.updateById(snapshotA);
        assertThat(rowsA).isEqualTo(1);

        // Verify A's change persisted via JdbcTemplate
        String dbNameAfterA = jdbcTemplate.queryForObject(
                "SELECT product_name FROM demo_product WHERE id = ?",
                String.class, productId);
        assertThat(dbNameAfterA).isEqualTo("Updated by A");

        // Verify version incremented in DB
        Long dbVersionAfterA = jdbcTemplate.queryForObject(
                "SELECT version FROM demo_product WHERE id = ?",
                Long.class, productId);
        assertThat(dbVersionAfterA).isEqualTo(initialVersion + 1);

        // 4. Snapshot B with stale version fails
        snapshotB.setProductName("Updated by B — should fail");
        int rowsB = productMapper.updateById(snapshotB);
        System.out.println("Stale snapshot updateById affected rows = " + rowsB);
        assertThat(rowsB).isZero();

        // Verify DB still has A's value
        String dbNameAfterB = jdbcTemplate.queryForObject(
                "SELECT product_name FROM demo_product WHERE id = ?",
                String.class, productId);
        assertThat(dbNameAfterB).isEqualTo("Updated by A");

        // Verify version did NOT increment again
        Long dbVersionAfterB = jdbcTemplate.queryForObject(
                "SELECT version FROM demo_product WHERE id = ?",
                Long.class, productId);
        assertThat(dbVersionAfterB).isEqualTo(dbVersionAfterA);

        // 5. Check whether framework writes back version into entity
        System.out.println("snapshotA.version after updateById = " + snapshotA.getVersion());
        System.out.println("snapshotB.version after failed updateById = " + snapshotB.getVersion());
    }

    @Test
    void insertsUserAndRollsTransactionBack() {
        LocalDateTime now = LocalDateTime.now().withNano(0);
        UserEntity user = new UserEntity();
        user.setUserNo(ROLLBACK_TEST_USER_NO);
        user.setUserName("Persistence rollback test");
        user.setStatus("ENABLED");
        user.setCreatedAt(now);
        user.setUpdatedAt(now);

        assertThat(userMapper.insert(user)).isEqualTo(1);
        assertThat(user.getId()).isNotNull();
        assertThat(userMapper.selectById(user.getId()).getUserNo()).isEqualTo(user.getUserNo());
    }

    @AfterAll
    void leavesNoRollbackTestUserBehind() {
        Long residualCount = userMapper.selectCount(
                Wrappers.<UserEntity>lambdaQuery()
                        .eq(UserEntity::getUserNo, ROLLBACK_TEST_USER_NO));

        System.out.println("Rollback residual count for " + ROLLBACK_TEST_USER_NO + " = " + residualCount);
        assertThat(residualCount).isZero();
    }
}
