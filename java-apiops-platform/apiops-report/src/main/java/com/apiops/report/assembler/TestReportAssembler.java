package com.apiops.report.assembler;

import com.apiops.report.vo.TestReportVO;
import com.apiops.runner.assertion.AssertionResult;
import com.apiops.runner.persistence.ExecutionFactRepository.CaseExecutionFacts;
import com.apiops.runner.persistence.ExecutionFactRepository.RunExecutionFacts;
import com.apiops.runner.persistence.ExecutionFactRepository.StepExecutionFacts;
import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;

import java.util.List;
import java.util.Objects;

/** Converts stored execution facts into the report read model. */
public final class TestReportAssembler {

    private static final TypeReference<List<AssertionResult>> ASSERTION_RESULTS_TYPE =
            new TypeReference<>() {
            };

    private final ObjectMapper objectMapper;

    public TestReportAssembler(ObjectMapper objectMapper) {
        this.objectMapper = Objects.requireNonNull(objectMapper, "objectMapper must not be null");
    }

    public TestReportVO assemble(RunExecutionFacts facts) {
        Objects.requireNonNull(facts, "facts must not be null");
        List<TestReportVO.CaseReport> cases = facts.caseResults().stream()
                .map(this::caseReport)
                .toList();
        int totalSteps = cases.stream().mapToInt(value -> value.steps().size()).sum();
        int totalAssertions = cases.stream()
                .flatMap(value -> value.steps().stream())
                .mapToInt(value -> value.assertionResults().size())
                .sum();
        int passedAssertions = cases.stream()
                .flatMap(value -> value.steps().stream())
                .flatMap(value -> value.assertionResults().stream())
                .mapToInt(value -> value.passed() ? 1 : 0)
                .sum();

        return new TestReportVO(
                facts.projectId(),
                facts.taskId(),
                facts.runId(),
                TestReportVO.reportIdForRun(facts.runId()),
                facts.status(),
                facts.startedAt(),
                facts.finishedAt(),
                new TestReportVO.Summary(
                        cases.size(),
                        totalSteps,
                        totalAssertions,
                        passedAssertions,
                        totalAssertions - passedAssertions,
                        facts.failureType()),
                cases);
    }

    private TestReportVO.CaseReport caseReport(CaseExecutionFacts facts) {
        return new TestReportVO.CaseReport(
                facts.caseId(),
                facts.status(),
                facts.failureType(),
                facts.stepResults().stream().map(this::stepReport).toList());
    }

    private TestReportVO.StepReport stepReport(StepExecutionFacts facts) {
        return new TestReportVO.StepReport(
                facts.stepId(),
                facts.status(),
                facts.failureType(),
                facts.responseStatusCode(),
                facts.durationMs(),
                assertionResults(facts.assertionResultsJson()));
    }

    private List<AssertionResult> assertionResults(String json) {
        try {
            return objectMapper.readValue(json, ASSERTION_RESULTS_TYPE);
        } catch (JsonProcessingException exception) {
            throw new IllegalStateException("Unable to read stored assertion results", exception);
        }
    }
}
