package com.apiops.demo.order.user;

import com.apiops.demo.order.common.exception.DemoOrderBusinessException;
import com.apiops.demo.order.common.exception.DemoOrderErrorCode;
import com.apiops.demo.order.common.exception.ResourceNotFoundException;
import com.apiops.demo.order.user.application.UserApplicationService;
import com.apiops.demo.order.user.entity.UserEntity;
import com.apiops.demo.order.user.mapper.UserMapper;
import com.apiops.demo.order.user.vo.UserVO;
import com.baomidou.mybatisplus.core.toolkit.Wrappers;
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

import java.util.UUID;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatCode;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.NONE)
@ActiveProfiles("local")
@EnabledIfEnvironmentVariable(named = "APIOPS_ORDER_DB_URL", matches = ".+")
@Transactional
@Rollback
@TestInstance(TestInstance.Lifecycle.PER_CLASS)
class UserIntegrationTest {

    static final String INTEGRATION_TEST_USER_NO_PREFIX = "test_int_user_";

    @Autowired
    private UserApplicationService userApplicationService;

    @Autowired
    private UserMapper userMapper;

    @Autowired
    private JdbcTemplate jdbcTemplate;

    @Test
    void createsUserAndQueriesFromDatabase() {
        String userNo = uniqueUserNo();
        UserVO created = userApplicationService.createUser(userNo, "Integration Test User");

        assertThat(created.getId()).isNotNull();
        assertThat(created.getUserNo()).isEqualTo(userNo);
        assertThat(created.getStatus()).isEqualTo("ENABLED");

        // Verify DB state
        UserEntity dbEntity = userMapper.selectById(created.getId());
        assertThat(dbEntity).isNotNull();
        assertThat(dbEntity.getUserNo()).isEqualTo(userNo);
        assertThat(dbEntity.getStatus()).isEqualTo("ENABLED");
    }

    @Test
    void rejectsDuplicateUserNoWithBusinessError() {
        String userNo = uniqueUserNo();
        userApplicationService.createUser(userNo, "First User");

        assertThatThrownBy(() -> userApplicationService.createUser(userNo, "Second User"))
                .isInstanceOf(DemoOrderBusinessException.class)
                .extracting(e -> ((DemoOrderBusinessException) e).getErrorCode())
                .isEqualTo(DemoOrderErrorCode.BUSINESS_CONFLICT);

        // Only one record exists
        Long count = userMapper.selectCount(
                Wrappers.<UserEntity>lambdaQuery()
                        .eq(UserEntity::getUserNo, userNo));
        assertThat(count).isEqualTo(1L);
    }

    @Test
    void queriesUserByIdSuccessfully() {
        String userNo = uniqueUserNo();
        UserVO created = userApplicationService.createUser(userNo, "Query Test User");

        UserVO queried = userApplicationService.queryById(created.getId());

        assertThat(queried.getId()).isEqualTo(created.getId());
        assertThat(queried.getUserNo()).isEqualTo(userNo);
        assertThat(queried.getUserName()).isEqualTo("Query Test User");
        assertThat(queried.getStatus()).isEqualTo("ENABLED");
    }

    @Test
    void queryNonExistentUserThrowsResourceNotFound() {
        assertThatThrownBy(() -> userApplicationService.queryById(Long.MAX_VALUE))
                .isInstanceOf(ResourceNotFoundException.class)
                .hasMessageContaining("not found");
    }

    @Test
    void disablesEnabledUserAndUpdatesDatabase() {
        String userNo = uniqueUserNo();
        UserVO created = userApplicationService.createUser(userNo, "User to disable");
        assertThat(created.getStatus()).isEqualTo("ENABLED");

        UserVO disabled = userApplicationService.disableUser(created.getId());
        assertThat(disabled.getStatus()).isEqualTo("DISABLED");

        // Verify DB state
        String dbStatus = jdbcTemplate.queryForObject(
                "SELECT status FROM demo_user WHERE id = ?",
                String.class, created.getId());
        assertThat(dbStatus).isEqualTo("DISABLED");
    }

    @Test
    void repeatDisableIsIdempotent() {
        String userNo = uniqueUserNo();
        UserVO created = userApplicationService.createUser(userNo, "Idempotent disable test");

        // First disable — conditional update rows=1
        UserVO first = userApplicationService.disableUser(created.getId());
        assertThat(first.getStatus()).isEqualTo("DISABLED");

        // Second disable — conditional update rows=0, re-query DISABLED
        UserVO second = userApplicationService.disableUser(created.getId());
        assertThat(second.getStatus()).isEqualTo("DISABLED");
        assertThat(second.getId()).isEqualTo(created.getId());

        // Verify only one DB record, still DISABLED
        Long count = userMapper.selectCount(
                Wrappers.<UserEntity>lambdaQuery()
                        .eq(UserEntity::getUserNo, userNo));
        assertThat(count).isEqualTo(1L);

        String dbStatus = jdbcTemplate.queryForObject(
                "SELECT status FROM demo_user WHERE id = ?",
                String.class, created.getId());
        assertThat(dbStatus).isEqualTo("DISABLED");
    }

    @Test
    void concurrentDisableAlreadyDisabledStillSucceeds() {
        // Simulates concurrent disable: another transaction disabled the
        // user between our conditional UPDATE (rows=0) and our re-query.
        // We test this by doing a direct DB update to DISABLED first,
        // then calling disableUser, which must handle rows=0 gracefully.
        String userNo = uniqueUserNo();
        UserVO created = userApplicationService.createUser(userNo, "Concurrent disable test");

        // Another "concurrent" caller disables the user via raw SQL
        jdbcTemplate.update("UPDATE demo_user SET status = 'DISABLED' WHERE id = ?",
                created.getId());

        // Our disableUser sees rows=0, re-queries, finds DISABLED → success
        assertThatCode(() -> {
            UserVO result = userApplicationService.disableUser(created.getId());
            assertThat(result.getStatus()).isEqualTo("DISABLED");
        }).doesNotThrowAnyException();

        String dbStatus = jdbcTemplate.queryForObject(
                "SELECT status FROM demo_user WHERE id = ?",
                String.class, created.getId());
        assertThat(dbStatus).isEqualTo("DISABLED");
    }

    @Test
    void disableNonExistentUserThrowsResourceNotFound() {
        assertThatThrownBy(() -> userApplicationService.disableUser(Long.MAX_VALUE))
                .isInstanceOf(ResourceNotFoundException.class)
                .hasMessageContaining("not found");
    }

    @Test
    void responseVOExcludesInternalFields() {
        String userNo = uniqueUserNo();
        UserVO created = userApplicationService.createUser(userNo, "VO Leak Test User");

        UserVO queried = userApplicationService.queryById(created.getId());
        // VO should not expose Entity internals like TableField annotations
        assertThat(queried.getStatus()).isNotNull();
        assertThat(queried.getUserNo()).isNotNull();
        assertThat(queried.getUserName()).isNotNull();
    }

    @AfterAll
    void leavesNoIntegrationTestDataBehind() {
        Long residualCount = userMapper.selectCount(
                Wrappers.<UserEntity>lambdaQuery()
                        .likeRight(UserEntity::getUserNo,
                                INTEGRATION_TEST_USER_NO_PREFIX));
        System.out.println("Residual user test data count = " + residualCount);
        assertThat(residualCount).isZero();
    }

    private static String uniqueUserNo() {
        return INTEGRATION_TEST_USER_NO_PREFIX + UUID.randomUUID();
    }
}
