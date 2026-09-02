package com.apiops.web.runner.vo;

import java.util.List;
import java.util.UUID;

public record AsyncBatchSubmission(
        UUID batchId,
        List<Long> taskIds,
        List<Long> runIds
) {
    public AsyncBatchSubmission {
        taskIds = List.copyOf(taskIds);
        runIds = List.copyOf(runIds);
    }
}
