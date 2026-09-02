package com.apiops.common.demo;
import com.apiops.common.util.StringCheckUtils;
public class StringCheckDemo {
    public static void main(String[] args) {
        System.out.println(StringCheckUtils.hasText(null));
        System.out.println(StringCheckUtils.hasText(""));
        System.out.println(StringCheckUtils.hasText("   "));
        System.out.println(StringCheckUtils.hasText("trace_001"));

        System.out.println(StringCheckUtils.isBlank(null));
        System.out.println(StringCheckUtils.isBlank(""));
        System.out.println(StringCheckUtils.isBlank("   "));
        System.out.println(StringCheckUtils.isBlank("trace_001"));

    }
}
