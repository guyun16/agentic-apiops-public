package com.apiops.web.runner.config;

import com.apiops.web.runner.rabbit.ExecutionRabbitProperties;
import org.junit.jupiter.api.Test;
import org.springframework.amqp.core.Binding;
import org.springframework.amqp.core.DirectExchange;
import org.springframework.amqp.core.Queue;

import static org.junit.jupiter.api.Assertions.assertEquals;

class RabbitExecutionConfigurationTest {

    @Test
    void topologyUsesConfiguredNamesAndDeadLetterRoute() {
        ExecutionRabbitProperties properties = properties();
        RabbitExecutionConfiguration configuration = new RabbitExecutionConfiguration();

        DirectExchange exchange = configuration.executionExchange(properties);
        Queue queue = configuration.executionQueue(properties);
        Binding binding = configuration.executionBinding(queue, exchange, properties);
        DirectExchange deadLetterExchange =
                configuration.executionDeadLetterExchange(properties);
        Queue deadLetterQueue = configuration.executionDeadLetterQueue(properties);
        Binding deadLetterBinding = configuration.executionDeadLetterBinding(
                deadLetterQueue, deadLetterExchange, properties);

        assertEquals("execution.exchange", exchange.getName());
        assertEquals("execution.queue", queue.getName());
        assertEquals("execution.run", binding.getRoutingKey());
        assertEquals("execution.dlx", queue.getArguments().get("x-dead-letter-exchange"));
        assertEquals("execution.dead",
                queue.getArguments().get("x-dead-letter-routing-key"));
        assertEquals("execution.dlx", deadLetterExchange.getName());
        assertEquals("execution.dlq", deadLetterQueue.getName());
        assertEquals("execution.dead", deadLetterBinding.getRoutingKey());
    }

    private ExecutionRabbitProperties properties() {
        ExecutionRabbitProperties properties = new ExecutionRabbitProperties();
        properties.setExchange("execution.exchange");
        properties.setRoutingKey("execution.run");
        properties.setQueue("execution.queue");
        properties.setDeadLetterExchange("execution.dlx");
        properties.setDeadLetterRoutingKey("execution.dead");
        properties.setDeadLetterQueue("execution.dlq");
        return properties;
    }
}
