package com.apiops.demo.order.user.application;

import com.apiops.demo.order.common.exception.DemoOrderBusinessException;
import com.apiops.demo.order.common.exception.DemoOrderErrorCode;
import com.apiops.demo.order.common.exception.ResourceNotFoundException;
import com.apiops.demo.order.user.converter.UserConverter;
import com.apiops.demo.order.user.entity.UserEntity;
import com.apiops.demo.order.user.mapper.UserMapper;
import com.apiops.demo.order.user.vo.UserVO;
import com.baomidou.mybatisplus.core.conditions.update.LambdaUpdateWrapper;
import com.baomidou.mybatisplus.core.toolkit.Wrappers;
import org.springframework.dao.DuplicateKeyException;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.time.LocalDateTime;

/**
 * Application service for user operations.
 *
 * <p>{@code demo_user} has a single unique constraint on {@code user_no}.
 * An INSERT {@link DuplicateKeyException} is therefore attributable to a
 * duplicate {@code user_no} and is mapped to a business conflict error.</p>
 */
@Service
public class UserApplicationService {

    private final UserMapper userMapper;

    public UserApplicationService(UserMapper userMapper) {
        this.userMapper = userMapper;
    }

    @Transactional
    public UserVO createUser(String userNo, String userName) {
        // Application-layer duplicate pre-check
        Long existingCount = userMapper.selectCount(
                Wrappers.<UserEntity>lambdaQuery()
                        .eq(UserEntity::getUserNo, userNo));
        if (existingCount != null && existingCount > 0) {
            throw new DemoOrderBusinessException(
                    DemoOrderErrorCode.BUSINESS_CONFLICT,
                    "user with userNo " + userNo + " already exists");
        }

        UserEntity entity = new UserEntity();
        entity.setUserNo(userNo);
        entity.setUserName(userName);
        entity.setStatus("ENABLED");
        LocalDateTime now = LocalDateTime.now();
        entity.setCreatedAt(now);
        entity.setUpdatedAt(now);

        try {
            userMapper.insert(entity);
        } catch (DuplicateKeyException e) {
            // demo_user has only one unique constraint (user_no) —
            // any DuplicateKeyException is from a concurrent userNo collision.
            throw new DemoOrderBusinessException(
                    DemoOrderErrorCode.BUSINESS_CONFLICT,
                    "user with userNo " + userNo + " already exists");
        }

        return UserConverter.toVO(entity);
    }

    public UserVO queryById(Long id) {
        UserEntity entity = userMapper.selectById(id);
        if (entity == null) {
            throw new ResourceNotFoundException("user id " + id + " not found");
        }
        return UserConverter.toVO(entity);
    }

    /**
     * Disables an enabled user with a conditional update.
     *
     * <p>The generated SQL is approximately:
     * <pre>{@code
     * UPDATE demo_user
     * SET status = 'DISABLED'
     * WHERE id = ?
     *   AND status = 'ENABLED'
     * }</pre>
     * This is an idempotent, concurrency-safe conditional update —
     * no prior {@code selectById} or version check is needed.</p>
     *
     * <p>When the conditional update matches zero rows, we re-query to
     * distinguish "already disabled" from "does not exist" from any other
     * unexpected state.</p>
     */
    @Transactional
    public UserVO disableUser(Long id) {
        LambdaUpdateWrapper<UserEntity> wrapper =
                Wrappers.<UserEntity>lambdaUpdate()
                        .eq(UserEntity::getId, id)
                        .eq(UserEntity::getStatus, "ENABLED")
                        .set(UserEntity::getStatus, "DISABLED");

        int rows = userMapper.update(wrapper);

        if (rows == 1) {
            // Happy path: one row transitioned ENABLED → DISABLED
            UserEntity updated = userMapper.selectById(id);
            return UserConverter.toVO(updated);
        }

        // rows == 0 — conditional update matched nothing.
        // Re-query to determine why.
        UserEntity current = userMapper.selectById(id);
        if (current == null) {
            throw new ResourceNotFoundException("user id " + id + " not found");
        }
        if ("DISABLED".equals(current.getStatus())) {
            // Concurrent duplicate disable — idempotent, return success.
            return UserConverter.toVO(current);
        }
        // User exists but is neither ENABLED nor DISABLED —
        // unexpected status, report as conflict.
        throw new DemoOrderBusinessException(
                DemoOrderErrorCode.BUSINESS_CONFLICT,
                "user id " + id + " is in unexpected status, disable failed");
    }
}
