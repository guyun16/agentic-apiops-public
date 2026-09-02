package com.apiops.web.runner.rabbit;

import com.apiops.runner.messaging.BatchExecutionMessage;
import com.apiops.runner.messaging.BatchExecutionProducer;
import org.springframework.amqp.rabbit.core.RabbitTemplate;

import java.util.Objects;

public final class RabbitBatchExecutionProducer implements BatchExecutionProducer {

    private final RabbitTemplate rabbitTemplate;
    private final ExecutionRabbitProperties properties;

    public RabbitBatchExecutionProducer(
            RabbitTemplate rabbitTemplate,
            ExecutionRabbitProperties properties) {
        this.rabbitTemplate = Objects.requireNonNull(
                rabbitTemplate, "rabbitTemplate must not be null");
        this.properties = Objects.requireNonNull(properties, "properties must not be null");
    }

    @Override
    public void publish(BatchExecutionMessage message) {
        Objects.requireNonNull(message, "message must not be null");
        rabbitTemplate.convertAndSend(
                properties.getExchange(),
                properties.getRoutingKey(),
                message);
    }
}
