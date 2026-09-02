package com.apiops.report.exception;

public final class TestReportNotFoundException extends RuntimeException {

    public TestReportNotFoundException(long projectId, long runId) {
        super("Test report not found for project " + projectId + " and run " + runId);
    }
}
