package com.apiops.report;

import com.apiops.common.enums.FailureType;
import com.apiops.runner.persistence.ExecutionFactRepository.CaseExecutionFacts;
import com.apiops.runner.persistence.ExecutionFactRepository.RunExecutionFacts;
import com.apiops.runner.persistence.ExecutionFactRepository.StepExecutionFacts;
import com.apiops.runner.state.RunStatus;

import java.time.Instant;
import java.util.List;

final class TestReportFacts {

    static final long PROJECT_ID = 41L;
    static final long TASK_ID = 71L;
    static final long RUN_ID = 101L;
    private static final Instant STARTED_AT = Instant.parse("2026-08-11T01:00:00Z");

    private TestReportFacts() {
    }

    static RunExecutionFacts success() {
        return singleStep(
                RunStatus.SUCCESS,
                FailureType.NONE,
                """
                        [
                          {"type":"STATUS_CODE","passed":true,"expected":200,
                           "actual":200,"message":"status matched"},
                          {"type":"RESPONSE_TIME","passed":true,"expected":500,
                           "actual":20,"message":"duration matched"}
                        ]
                        """,
                200,
                20L);
    }

    static RunExecutionFacts assertionFailed() {
        return singleStep(
                RunStatus.ASSERTION_FAILED,
                FailureType.ASSERTION_MISMATCH,
                """
                        [
                          {"type":"STATUS_CODE","passed":false,"expected":201,
                           "actual":200,"message":"status did not match"}
                        ]
                        """,
                200,
                25L);
    }

    static RunExecutionFacts executionFailed() {
        return singleStep(
                RunStatus.EXECUTION_FAILED,
                FailureType.CONNECT_ERROR,
                "[]",
                null,
                null);
    }

    static RunExecutionFacts multipleCasesAndSteps() {
        CaseExecutionFacts firstCase = caseFacts(
                201L,
                "case-success",
                RunStatus.SUCCESS,
                FailureType.NONE,
                List.of(
                        step(301L, 201L, "step-1", RunStatus.SUCCESS, FailureType.NONE,
                                """
                                        [
                                          {"type":"STATUS_CODE","passed":true,"expected":200,
                                           "actual":200,"message":"matched"},
                                          {"type":"JSON_PATH","passed":true,"expected":"ok",
                                           "actual":"ok","message":"matched"}
                                        ]
                                        """, 200, 10L),
                        step(302L, 201L, "step-2", RunStatus.SUCCESS, FailureType.NONE,
                                """
                                        [
                                          {"type":"RESPONSE_TIME","passed":true,"expected":100,
                                           "actual":20,"message":"matched"}
                                        ]
                                        """, 200, 20L)));
        CaseExecutionFacts secondCase = caseFacts(
                202L,
                "case-mismatch",
                RunStatus.ASSERTION_FAILED,
                FailureType.ASSERTION_MISMATCH,
                List.of(step(303L, 202L, "step-3",
                        RunStatus.ASSERTION_FAILED,
                        FailureType.ASSERTION_MISMATCH,
                        """
                                [
                                  {"type":"HEADER","passed":true,"expected":"[REDACTED]",
                                   "actual":"[REDACTED]","message":"matched"},
                                  {"type":"STATUS_CODE","passed":false,"expected":201,
                                   "actual":200,"message":"did not match"}
                                ]
                                """, 200, 30L)));
        return run(
                RunStatus.ASSERTION_FAILED,
                FailureType.ASSERTION_MISMATCH,
                List.of(firstCase, secondCase));
    }

    private static RunExecutionFacts singleStep(
            RunStatus status,
            FailureType failureType,
            String assertionResultsJson,
            Integer responseStatusCode,
            Long durationMs
    ) {
        return run(status, failureType, List.of(caseFacts(
                201L,
                "case-order",
                status,
                failureType,
                List.of(step(
                        301L,
                        201L,
                        "step-order",
                        status,
                        failureType,
                        assertionResultsJson,
                        responseStatusCode,
                        durationMs)))));
    }

    private static RunExecutionFacts run(
            RunStatus status,
            FailureType failureType,
            List<CaseExecutionFacts> cases
    ) {
        return new RunExecutionFacts(
                PROJECT_ID,
                TASK_ID,
                RUN_ID,
                "case-order",
                "createOrder",
                "create order report",
                status,
                failureType,
                STARTED_AT,
                STARTED_AT.plusSeconds(1),
                cases);
    }

    private static CaseExecutionFacts caseFacts(
            long caseResultId,
            String caseId,
            RunStatus status,
            FailureType failureType,
            List<StepExecutionFacts> steps
    ) {
        return new CaseExecutionFacts(
                PROJECT_ID,
                RUN_ID,
                caseResultId,
                caseId,
                status,
                failureType,
                STARTED_AT,
                STARTED_AT.plusSeconds(1),
                steps);
    }

    private static StepExecutionFacts step(
            long stepResultId,
            long caseResultId,
            String stepId,
            RunStatus status,
            FailureType failureType,
            String assertionResultsJson,
            Integer responseStatusCode,
            Long durationMs
    ) {
        return new StepExecutionFacts(
                PROJECT_ID,
                RUN_ID,
                caseResultId,
                stepResultId,
                stepId,
                status,
                failureType,
                assertionResultsJson,
                responseStatusCode,
                durationMs,
                STARTED_AT.plusSeconds(1));
    }
}
