package com.apiops.common.demo;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;

public class CheckedExceptionDemo {

    public static void main(String[] args) {
        try {
            String text = Files.readString(Path.of("not-exist.txt"));
            System.out.println(text);
        } catch (IOException e) {
            System.out.println("Checked exception caught: " + e.getClass().getSimpleName());
            System.out.println("Message: " + e.getMessage());
        }
    }
}