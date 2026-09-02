package com.apiops.web.runner.rabbit;

import com.apiops.runner.messaging.BatchExecutionMessage;
import org.junit.jupiter.api.Test;
import org.springframework.amqp.AmqpException;
import org.springframework.amqp.rabbit.core.RabbitTemplate;

import java.time.Instant;
import java.util.UUID;

import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.mockito.Mockito.doThrow;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;

class RabbitBatchExecutionProducerTest {

    @Test
    void publishesToConfiguredExchangeAndRoutingKey() {
        RabbitTemplate rabbitTemplate = mock(RabbitTemplate.class);
        ExecutionRabbitProperties properties = properties();
        RabbitBatchExecutionProducer producer =
                new RabbitBatchExecutionProducer(rabbitTemplate, properties);
        BatchExecutionMessage message = message();

        producer.publish(message);

        verify(rabbitTemplate).convertAndSend("execution.exchange", "execution.run", message);
    }

    @Test
    void publishFailureIsNotSwallowed() {
        RabbitTemplate rabbitTemplate = mock(RabbitTemplate.class);
        ExecutionRabbitProperties properties = properties();
        BatchExecutionMessage message = message();
        doThrow(new AmqpException("broker unavailable"))
                .when(rabbitTemplate)
                .convertAndSend("execution.exchange", "execution.run", message);
        RabbitBatchExecutionProducer producer =
                new RabbitBatchExecutionProducer(rabbitTemplate, properties);

        assertThrows(AmqpException.class, () -> producer.publish(message));
    }

    private ExecutionRabbitProperties properties() {
        ExecutionRabbitProperties properties = new ExecutionRabbitProperties();
        properties.setExchange("execution.exchange");
        properties.setRoutingKey("execution.run");
        return properties;
    }

    private BatchExecutionMessage message() {
        return new BatchExecutionMessage(
                BatchExecutionMessage.CURRENT_VERSION,
                UUID.randomUUID(),
                101L,
                UUID.randomUUID(),
                401L,
                "trace-producer-test",
                Instant.parse("2026-08-11T12:00:00Z"));
    }
}
