package com.apiops.web.runner.rabbit;

import com.apiops.runner.application.AsyncExecutionApplicationService;
import com.apiops.runner.messaging.BatchExecutionMessage;
import org.springframework.amqp.rabbit.annotation.RabbitListener;

import java.util.Objects;

public final class BatchExecutionConsumer {

    private final AsyncExecutionApplicationService applicationService;

    public BatchExecutionConsumer(AsyncExecutionApplicationService applicationService) {
        this.applicationService = Objects.requireNonNull(
                applicationService, "applicationService must not be null");
    }

    @RabbitListener(
            queues = "${apiops.rabbitmq.execution.queue}",
            containerFactory = "batchExecutionRabbitListenerContainerFactory")
    public void consume(BatchExecutionMessage message) {
        applicationService.execute(message);
    }
}
