package com.apiops.common.concurrency.design;

import java.util.concurrent.ThreadPoolExecutor;

public final class RunnerExecutorConfigDraft {

    private RunnerExecutorConfigDraft() {
    }

    public static ThreadPoolExecutor createRunnerExecutor() {
        return ExecutorFactory.newBoundedExecutor(
                "apiops-runner",
                16,
                64,
                1000
        );
    }
}