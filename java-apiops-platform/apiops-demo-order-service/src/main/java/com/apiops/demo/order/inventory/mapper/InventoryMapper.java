package com.apiops.demo.order.inventory.mapper;

import com.apiops.demo.order.inventory.entity.InventoryEntity;
import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import org.apache.ibatis.annotations.Param;

public interface InventoryMapper extends BaseMapper<InventoryEntity> {
    int deductIfEnough(@Param("productId") Long productId,
                       @Param("quantity") Long quantity);
}
