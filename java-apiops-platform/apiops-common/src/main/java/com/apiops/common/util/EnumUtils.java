package com.apiops.common.util;

import com.apiops.common.enums.BaseEnum;

import java.util.Arrays;
import java.util.Collections;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.Optional;
import java.util.stream.Collectors;

/**
 * Utility methods for querying enums that implement BaseEnum.
 */
public final class EnumUtils {

    private EnumUtils() {
    }

    public static <E extends Enum<E> & BaseEnum> E fromCode(Class<E> enumClass, String code) {
        return fromCodeOptional(enumClass, code).orElse(null);
    }

    public static <E extends Enum<E> & BaseEnum> Optional<E> fromCodeOptional(Class<E> enumClass, String code) {
        if (enumClass == null || code == null) {
            return Optional.empty();
        }

        return Arrays.stream(enumClass.getEnumConstants())
                .filter(item -> Objects.equals(item.getCode(), code))
                .findFirst();
    }

    public static <E extends Enum<E> & BaseEnum> List<String> toCodeList(Class<E> enumClass) {
        if (enumClass == null) {
            return Collections.emptyList();
        }

        return Arrays.stream(enumClass.getEnumConstants())
                .map(BaseEnum::getCode)
                .toList();
    }

    public static <E extends Enum<E> & BaseEnum> Map<String, String> toMessageMap(Class<E> enumClass) {
        if (enumClass == null) {
            return Collections.emptyMap();
        }

        return Arrays.stream(enumClass.getEnumConstants())
                .collect(Collectors.toMap(
                        BaseEnum::getCode,
                        BaseEnum::getMessage
                ));
    }
}

//public final class EnumUtils {
//
//    private EnumUtils() {
//    }
//
//    public static <E extends Enum<E> & BaseEnum> E fromCode(Class<E> enumClass, String code) {
//        if (enumClass == null || code == null) {
//            return null;
//        }
//
////        E[] enumConstants = enumClass.getEnumConstants();
////        if (enumConstants == null) {
////            return null;
////        }
////
////        for (E item : enumConstants) {
////            if (code.equals(item.getCode())) {
////                return item;
////            }
////        }
////
////        return null;
//        return Arrays.stream(enumClass.getEnumConstants())
//                .filter(item -> Objects.equals(item.getCode(),code))
//                .findFirst()
//                .orElse(null);
//    }
//}
