package com.apiops.demo.order.user.converter;

import com.apiops.demo.order.user.entity.UserEntity;
import com.apiops.demo.order.user.vo.UserVO;

public class UserConverter {

    private UserConverter() {
    }

    public static UserVO toVO(UserEntity entity) {
        if (entity == null) {
            return null;
        }
        UserVO vo = new UserVO();
        vo.setId(entity.getId());
        vo.setUserNo(entity.getUserNo());
        vo.setUserName(entity.getUserName());
        vo.setStatus(entity.getStatus());
        vo.setCreatedAt(entity.getCreatedAt());
        vo.setUpdatedAt(entity.getUpdatedAt());
        return vo;
    }
}
