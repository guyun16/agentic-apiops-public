package com.apiops.common.demo;

import java.util.List;
import java.util.Optional;

public class StreamDemo {

    public static void main(String[] args) {
        List<String> codes = List.of("PENDING", "RUNNING", "SUCCESS", "FAILED");

        List<String> successLikeCodes = codes.stream()
                .filter(code -> code.startsWith("S"))
                .toList();

        List<Integer> lengths = codes.stream()
                .map(code -> code.length())
                .toList();

        Optional<String> firstSuccessLikeCode = codes.stream()
                .filter(code -> code.startsWith("S"))
                .findFirst();

        System.out.println(successLikeCodes);
        System.out.println(lengths);
        System.out.println(firstSuccessLikeCode.orElse("NOT_FOUND"));
    }
}