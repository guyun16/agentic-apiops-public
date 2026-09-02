package com.apiops.common.demo;

import com.apiops.common.annotation.ApiOpsField;

import java.lang.reflect.Field;

public class ReflectionDemo {

    static class ToolCallSample {

        @ApiOpsField(value = "Tool call id for audit tracking", required = true)
        private String toolCallId;

        @ApiOpsField(value = "Trace id across Java Platform and Python AgentLab", required = true)
        private String traceId;

        private String internalNote;
    }

    public static void main(String[] args) {
        printApiOpsFields(ToolCallSample.class);
    }

    private static void printApiOpsFields(Class<?> clazz) {
        Field[] fields = clazz.getDeclaredFields();

        for (Field field : fields) {
            if (!field.isAnnotationPresent(ApiOpsField.class)) {
                continue;
            }

            ApiOpsField apiOpsField = field.getAnnotation(ApiOpsField.class);

            System.out.println("fieldName=" + field.getName()
                    + ", fieldType=" + field.getType().getSimpleName()
                    + ", description=" + apiOpsField.value()
                    + ", required=" + apiOpsField.required());
        }
    }
}