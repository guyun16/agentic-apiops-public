package com.apiops.web.runner.config;

import com.apiops.runner.application.AsyncExecutionApplicationService;
import com.apiops.runner.application.PermanentExecutionMessageException;
import com.apiops.runner.application.UnresolvedRunningExecutionException;
import com.apiops.runner.messaging.BatchExecutionProducer;
import com.apiops.web.runner.rabbit.BatchExecutionConsumer;
import com.apiops.web.runner.rabbit.ExecutionRabbitProperties;
import com.apiops.web.runner.rabbit.RabbitBatchExecutionProducer;
import com.apiops.web.runner.application.AsyncBatchHttpApplicationService;
import com.apiops.auth.application.ProjectAuthorizationService;
import com.apiops.runner.application.BatchExecutionCoordinator;
import com.apiops.runner.persistence.ExecutionFactRepository;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.aopalliance.aop.Advice;
import org.springframework.amqp.core.Binding;
import org.springframework.amqp.core.BindingBuilder;
import org.springframework.amqp.core.DirectExchange;
import org.springframework.amqp.core.Queue;
import org.springframework.amqp.core.QueueBuilder;
import org.springframework.amqp.rabbit.config.RetryInterceptorBuilder;
import org.springframework.amqp.rabbit.config.SimpleRabbitListenerContainerFactory;
import org.springframework.amqp.core.AcknowledgeMode;
import org.springframework.amqp.rabbit.connection.ConnectionFactory;
import org.springframework.amqp.rabbit.core.RabbitTemplate;
import org.springframework.amqp.rabbit.retry.RejectAndDontRequeueRecoverer;
import org.springframework.amqp.support.converter.Jackson2JsonMessageConverter;
import org.springframework.amqp.support.converter.MessageConverter;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.retry.policy.SimpleRetryPolicy;

import java.util.Map;

@Configuration(proxyBeanMethods = false)
@EnableConfigurationProperties(ExecutionRabbitProperties.class)
@ConditionalOnProperty(
        prefix = "apiops.rabbitmq.execution",
        name = "enabled",
        havingValue = "true")
public class RabbitExecutionConfiguration {

    @Bean
    public DirectExchange executionExchange(ExecutionRabbitProperties properties) {
        return new DirectExchange(properties.getExchange(), true, false);
    }

    @Bean
    public Queue executionQueue(ExecutionRabbitProperties properties) {
        return QueueBuilder.durable(properties.getQueue())
                .deadLetterExchange(properties.getDeadLetterExchange())
                .deadLetterRoutingKey(properties.getDeadLetterRoutingKey())
                .build();
    }

    @Bean
    public Binding executionBinding(
            Queue executionQueue,
            DirectExchange executionExchange,
            ExecutionRabbitProperties properties) {
        return BindingBuilder.bind(executionQueue)
                .to(executionExchange)
                .with(properties.getRoutingKey());
    }

    @Bean
    public DirectExchange executionDeadLetterExchange(ExecutionRabbitProperties properties) {
        return new DirectExchange(properties.getDeadLetterExchange(), true, false);
    }

    @Bean
    public Queue executionDeadLetterQueue(ExecutionRabbitProperties properties) {
        return QueueBuilder.durable(properties.getDeadLetterQueue()).build();
    }

    @Bean
    public Binding executionDeadLetterBinding(
            Queue executionDeadLetterQueue,
            DirectExchange executionDeadLetterExchange,
            ExecutionRabbitProperties properties) {
        return BindingBuilder.bind(executionDeadLetterQueue)
                .to(executionDeadLetterExchange)
                .with(properties.getDeadLetterRoutingKey());
    }

    @Bean
    public MessageConverter executionMessageConverter(ObjectMapper objectMapper) {
        return new Jackson2JsonMessageConverter(objectMapper);
    }

    @Bean
    public RabbitTemplate rabbitTemplate(
            ConnectionFactory connectionFactory,
            MessageConverter executionMessageConverter) {
        RabbitTemplate rabbitTemplate = new RabbitTemplate(connectionFactory);
        rabbitTemplate.setMessageConverter(executionMessageConverter);
        return rabbitTemplate;
    }

    @Bean
    public SimpleRabbitListenerContainerFactory batchExecutionRabbitListenerContainerFactory(
            ConnectionFactory connectionFactory,
            MessageConverter executionMessageConverter,
            ExecutionRabbitProperties properties) {
        SimpleRabbitListenerContainerFactory factory =
                new SimpleRabbitListenerContainerFactory();
        factory.setConnectionFactory(connectionFactory);
        factory.setMessageConverter(executionMessageConverter);
        factory.setAcknowledgeMode(AcknowledgeMode.AUTO);
        factory.setDefaultRequeueRejected(false);
        factory.setAdviceChain(retryAdvice(properties));
        return factory;
    }

    @Bean
    public BatchExecutionProducer batchExecutionProducer(
            RabbitTemplate rabbitTemplate,
            ExecutionRabbitProperties properties) {
        return new RabbitBatchExecutionProducer(rabbitTemplate, properties);
    }

    @Bean
    public BatchExecutionConsumer batchExecutionConsumer(
            AsyncExecutionApplicationService applicationService) {
        return new BatchExecutionConsumer(applicationService);
    }

    @Bean
    public AsyncBatchHttpApplicationService asyncBatchHttpApplicationService(
            ProjectAuthorizationService authorization,
            ExecutionFactRepository repository,
            BatchExecutionProducer producer,
            BatchExecutionCoordinator coordinator,
            ObjectMapper objectMapper) {
        return new AsyncBatchHttpApplicationService(
                authorization, repository, producer, coordinator, objectMapper);
    }

    private Advice retryAdvice(ExecutionRabbitProperties properties) {
        SimpleRetryPolicy retryPolicy = new SimpleRetryPolicy(
                properties.getMaxAttempts(),
                Map.of(
                        PermanentExecutionMessageException.class, false,
                        UnresolvedRunningExecutionException.class, false),
                true,
                true);
        return RetryInterceptorBuilder.stateless()
                .retryPolicy(retryPolicy)
                .recoverer(new RejectAndDontRequeueRecoverer())
                .build();
    }
}
