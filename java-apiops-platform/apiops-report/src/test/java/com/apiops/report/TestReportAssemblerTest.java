package com.apiops.report;

import com.apiops.report.assembler.TestReportAssembler;
import com.apiops.report.vo.TestReportVO;
import com.apiops.runner.assertion.AssertionResult;
import com.apiops.runner.persistence.ExecutionFactRepository.RunExecutionFacts;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.Test;

import java.util.List;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertInstanceOf;
import static org.junit.jupiter.api.Assertions.assertNotEquals;
import static org.junit.jupiter.api.Assertions.assertSame;
import static org.junit.jupiter.api.Assertions.assertFalse;

class TestReportAssemblerTest {

    private final TestReportAssembler assembler = new TestReportAssembler(new ObjectMapper());

    @Test
    void aggregatesMultipleCasesAndStepsWithoutMutatingSourceFacts() {
        RunExecutionFacts facts = TestReportFacts.multipleCasesAndSteps();
        List<?> sourceCases = facts.caseResults();
        String sourceAssertionJson = facts.caseResults().get(1)
                .stepResults().getFirst().assertionResultsJson();

        TestReportVO report = assembler.assemble(facts);

        assertEquals("report:" + facts.runId(), report.reportId());
        assertEquals(2, report.summary().totalCases());
        assertEquals(3, report.summary().totalSteps());
        assertEquals(5, report.summary().totalAssertions());
        assertEquals(4, report.summary().passedAssertions());
        assertEquals(1, report.summary().failedAssertions());
        assertEquals(2, report.cases().size());
        assertEquals(2, report.cases().getFirst().steps().size());
        assertInstanceOf(AssertionResult.class,
                report.cases().getFirst().steps().getFirst().assertionResults().getFirst());
        assertSame(sourceCases, facts.caseResults());
        assertEquals(sourceAssertionJson, facts.caseResults().get(1)
                .stepResults().getFirst().assertionResultsJson());
    }

    @Test
    void reportIdentityIsStableNamespacedAndDistinctAcrossRuns() {
        RunExecutionFacts facts = TestReportFacts.success();

        TestReportVO first = assembler.assemble(facts);
        TestReportVO second = assembler.assemble(facts);
        RunExecutionFacts differentRunFacts = new RunExecutionFacts(
                facts.projectId(), facts.taskId(), facts.runId() + 1,
                facts.caseId(), facts.apiId(), facts.taskName(), facts.status(),
                facts.failureType(), facts.startedAt(), facts.finishedAt(), facts.caseResults());
        TestReportVO differentRun = assembler.assemble(differentRunFacts);

        assertEquals(first.reportId(), second.reportId());
        assertEquals("report:" + facts.runId(), first.reportId());
        assertFalse(first.reportId().isBlank());
        assertNotEquals(Long.toString(facts.runId()), first.reportId());
        assertNotEquals(first.reportId(), differentRun.reportId());
    }
}
