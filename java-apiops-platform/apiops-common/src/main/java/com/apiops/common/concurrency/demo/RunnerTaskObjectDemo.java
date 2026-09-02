package com.apiops.common.concurrency.demo;

public final class RunnerTaskObjectDemo {

    public static void main(String[] args) {
        RunnerTask task = new RunnerTask(
                "task_001",
                "case_001",
                "trace_001"
        );

        System.out.println(task.getTaskId());
        System.out.println(task.getCaseId());
        System.out.println(task.getTraceId());
    }

    static final class RunnerTask {
        private final String taskId;
        private final String caseId;
        private final String traceId;

        RunnerTask(String taskId, String caseId, String traceId) {
            this.taskId = taskId;
            this.caseId = caseId;
            this.traceId = traceId;
        }

        String getTaskId() {
            return taskId;
        }

        String getCaseId() {
            return caseId;
        }

        String getTraceId() {
            return traceId;
        }
    }
}