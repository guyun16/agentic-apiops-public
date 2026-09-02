package com.apiops.web.runner.rabbit;

import com.apiops.runner.application.AsyncExecutionApplicationService;
import com.apiops.runner.application.PermanentExecutionMessageException;
import com.apiops.runner.application.UnresolvedRunningExecutionException;
import com.apiops.runner.messaging.BatchExecutionMessage;
import com.apiops.runner.messaging.BatchExecutionProducer;
import com.apiops.runner.application.BatchExecutionCoordinator;
import com.apiops.runner.persistence.ExecutionFactRepository;
import com.apiops.auth.application.ProjectAuthorizationService;
import com.apiops.web.runner.config.RabbitExecutionConfiguration;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.TestInstance;
import org.springframework.amqp.core.Message;
import org.springframework.amqp.rabbit.core.RabbitAdmin;
import org.springframework.amqp.rabbit.core.RabbitTemplate;
import org.springframework.boot.SpringBootConfiguration;
import org.springframework.boot.autoconfigure.EnableAutoConfiguration;
import org.springframework.boot.autoconfigure.jdbc.DataSourceAutoConfiguration;
import org.springframework.boot.autoconfigure.jdbc.DataSourceTransactionManagerAutoConfiguration;
import org.springframework.boot.autoconfigure.jdbc.JdbcTemplateAutoConfiguration;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Import;
import org.springframework.test.annotation.DirtiesContext;
import org.springframework.test.context.DynamicPropertyRegistry;
import org.springframework.test.context.DynamicPropertySource;
import org.testcontainers.containers.RabbitMQContainer;
import org.testcontainers.junit.jupiter.EnabledIfDockerAvailable;

import java.time.Instant;
import java.util.UUID;

import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.doAnswer;
import static org.mockito.Mockito.doThrow;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.reset;
import static org.mockito.Mockito.timeout;
import static org.mockito.Mockito.verify;

@SpringBootTest(
        classes = RabbitExecutionIntegrationTest.TestApplication.class,
        properties = {
                "apiops.rabbitmq.execution.enabled=true",
                "apiops.rabbitmq.execution.exchange=apiops.execution.it.exchange",
                "apiops.rabbitmq.execution.routing-key=apiops.execution.it.run",
                "apiops.rabbitmq.execution.queue=apiops.execution.it.queue",
                "apiops.rabbitmq.execution.dead-letter-exchange=apiops.execution.it.dlx",
                "apiops.rabbitmq.execution.dead-letter-routing-key=apiops.execution.it.dead",
                "apiops.rabbitmq.execution.dead-letter-queue=apiops.execution.it.dlq",
                "apiops.rabbitmq.execution.max-attempts=3"
        })
@DirtiesContext
@TestInstance(TestInstance.Lifecycle.PER_CLASS)
@EnabledIfDockerAvailable
class RabbitExecutionIntegrationTest {

    private static final String RABBIT_USERNAME = "stage13-it";
    private static final String RABBIT_PASSWORD = "stage13-it-password";

    private static final RabbitMQContainer RABBITMQ = new RabbitMQContainer(
            "rabbitmq:3.13-management")
            .withUser(RABBIT_USERNAME, RABBIT_PASSWORD)
            .withPermission("/", RABBIT_USERNAME, ".*", ".*", ".*");

    @DynamicPropertySource
    static void registerRabbitMqEndpoint(DynamicPropertyRegistry registry) {
        registry.add("spring.rabbitmq.host", () -> {
            startRabbitMq();
            return RABBITMQ.getHost();
        });
        registry.add("spring.rabbitmq.port", () -> {
            startRabbitMq();
            return RABBITMQ.getMappedPort(5672);
        });
        registry.add("spring.rabbitmq.username", () -> RABBIT_USERNAME);
        registry.add("spring.rabbitmq.password", () -> RABBIT_PASSWORD);
    }

    private static synchronized void startRabbitMq() {
        if (!RABBITMQ.isRunning()) {
            RABBITMQ.start();
        }
    }

    @org.springframework.beans.factory.annotation.Autowired
    private RabbitAdmin rabbitAdmin;

    @org.springframework.beans.factory.annotation.Autowired
    private RabbitTemplate rabbitTemplate;

    @org.springframework.beans.factory.annotation.Autowired
    private BatchExecutionProducer producer;

    @org.springframework.beans.factory.annotation.Autowired
    private AsyncExecutionApplicationService applicationService;

    @org.springframework.beans.factory.annotation.Autowired
    private ExecutionRabbitProperties properties;

    @BeforeEach
    void purgeQueuesAndResetService() {
        rabbitAdmin.purgeQueue(properties.getQueue(), false);
        rabbitAdmin.purgeQueue(properties.getDeadLetterQueue(), false);
        reset(applicationService);
    }

    @AfterAll
    void removeTestTopologyFromLocalBroker() {
        rabbitAdmin.deleteQueue(properties.getQueue());
        rabbitAdmin.deleteQueue(properties.getDeadLetterQueue());
        rabbitAdmin.deleteExchange(properties.getExchange());
        rabbitAdmin.deleteExchange(properties.getDeadLetterExchange());
        RABBITMQ.stop();
    }

    @Test
    void unsupportedVersionIsRejectedToDeadLetterQueueWithoutRetry() {
        doAnswer(invocation -> {
            BatchExecutionMessage message = invocation.getArgument(0);
            if (!BatchExecutionMessage.CURRENT_VERSION.equals(message.messageVersion())) {
                throw new PermanentExecutionMessageException("unsupported messageVersion");
            }
            return null;
        }).when(applicationService).execute(any());

        producer.publish(message("2.0"));

        Message deadLetter = receiveDeadLetter();
        assertNotNull(deadLetter);
        String payload = new String(deadLetter.getBody(), java.nio.charset.StandardCharsets.UTF_8);
        assertTrue(payload.contains("\"messageId\""));
        assertTrue(payload.contains("\"batchId\""));
        assertTrue(payload.contains("\"traceId\":\"trace-rabbit-it\""));
        verify(applicationService, timeout(10_000).times(1)).execute(any());
    }

    @Test
    void preClaimTransientFailureRetriesOnlyToConfiguredLimitThenDeadLetters() {
        doThrow(new IllegalStateException("temporary database outage"))
                .when(applicationService)
                .execute(any());

        producer.publish(message(BatchExecutionMessage.CURRENT_VERSION));

        assertNotNull(receiveDeadLetter());
        verify(applicationService, timeout(10_000).times(3)).execute(any());
    }

    @Test
    void unresolvedPostClaimRunningFailureDoesNotRetryWholeExecutionAndDeadLetters() {
        doThrow(new UnresolvedRunningExecutionException(
                "claimed run could not be terminalized"))
                .when(applicationService)
                .execute(any());

        producer.publish(message(BatchExecutionMessage.CURRENT_VERSION));

        assertNotNull(receiveDeadLetter());
        verify(applicationService, timeout(10_000).times(1)).execute(any());
    }

    private Message receiveDeadLetter() {
        return rabbitTemplate.receive(properties.getDeadLetterQueue(), 10_000L);
    }

    private BatchExecutionMessage message(String version) {
        return new BatchExecutionMessage(
                version,
                UUID.randomUUID(),
                101L,
                UUID.randomUUID(),
                401L,
                "trace-rabbit-it",
                Instant.parse("2026-08-11T12:00:00Z"));
    }

    @SpringBootConfiguration
    @EnableAutoConfiguration(exclude = {
            DataSourceAutoConfiguration.class,
            DataSourceTransactionManagerAutoConfiguration.class,
            JdbcTemplateAutoConfiguration.class
    })
    @Import(RabbitExecutionConfiguration.class)
    static class TestApplication {

        @Bean
        AsyncExecutionApplicationService asyncExecutionApplicationService() {
            return mock(AsyncExecutionApplicationService.class);
        }

        @Bean
        ProjectAuthorizationService projectAuthorizationService() {
            return mock(ProjectAuthorizationService.class);
        }

        @Bean
        ExecutionFactRepository executionFactRepository() {
            return mock(ExecutionFactRepository.class);
        }

        @Bean
        BatchExecutionCoordinator batchExecutionCoordinator() {
            return mock(BatchExecutionCoordinator.class);
        }
    }
}
