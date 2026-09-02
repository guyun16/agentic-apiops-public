package com.apiops.common.concurrency.design;

import java.util.concurrent.ThreadPoolExecutor;

public final class ToolGatewayExecutorConfigDraft {

    private ToolGatewayExecutorConfigDraft() {
    }

    public static ThreadPoolExecutor createToolGatewayExecutor() {
        return ExecutorFactory.newBoundedExecutor(
                "apiops-tool-gateway",
                8,
                32,
                300
        );
    }
}