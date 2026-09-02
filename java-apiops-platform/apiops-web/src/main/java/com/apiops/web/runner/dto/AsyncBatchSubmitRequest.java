package com.apiops.web.runner.dto;

import com.apiops.runner.dsl.TestCase;

import java.util.List;

public record AsyncBatchSubmitRequest(List<TestCase> testCases) {
}
