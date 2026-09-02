package com.apiops.common.util;

public class PageUtils {
    public PageUtils() {
    }
    public static long offset(long pageNo, long pageSize){
        if(pageNo < 1){
            throw new IllegalArgumentException("pageNo must be greater than or equal to 1");
        }
        if(pageSize < 1){
            throw new IllegalArgumentException("pageSize must be greater than or equal to 1");
        }
        return (pageNo-1)*pageSize;
    }
}
