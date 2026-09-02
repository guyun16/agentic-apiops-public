package com.apiops.web.runner.config;

import com.apiops.runner.application.AsyncExecutionApplicationService;
import com.apiops.runner.application.BatchExecutionCoordinator;
import com.apiops.runner.application.RunExecutionService;
import com.apiops.runner.application.RunnerExecutorFactory;
import com.apiops.runner.application.RunnerExecutorProperties;
import com.apiops.runner.progress.TaskProgressListener;
import com.apiops.runner.progress.TaskProgressStore;
import com.apiops.runner.assertion.AssertionEngine;
import com.apiops.runner.assertion.AssertionEvaluatorRegistry;
import com.apiops.runner.assertion.HeaderAssertionEvaluator;
import com.apiops.runner.assertion.JsonPathAssertionEvaluator;
import com.apiops.runner.assertion.ResponseTimeAssertionEvaluator;
import com.apiops.runner.assertion.StatusCodeAssertionEvaluator;
import com.apiops.runner.execution.AssertionContextMapper;
import com.apiops.runner.execution.TestStepRunner;
import com.apiops.runner.http.HttpRequestBuilder;
import com.apiops.runner.http.JdkHttpTransport;
import com.apiops.runner.persistence.ExecutionFactRepository;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.beans.factory.ObjectProvider;
import io.micrometer.core.instrument.MeterRegistry;

import java.time.Duration;
import java.util.concurrent.ThreadPoolExecutor;

@Configuration(proxyBeanMethods = false)
@EnableConfigurationProperties(RunnerBatchProperties.class)
@ConditionalOnProperty(prefix = "apiops.datasource.runner", name = "url")
public class RunnerExecutionConfiguration {

    @Bean
    public TestStepRunner testStepRunner(ObjectMapper objectMapper) {
        AssertionEngine assertionEngine = new AssertionEngine(new AssertionEvaluatorRegistry(
                new StatusCodeAssertionEvaluator(),
                new HeaderAssertionEvaluator(),
                new JsonPathAssertionEvaluator(),
                new ResponseTimeAssertionEvaluator()));
        return new TestStepRunner(
                new HttpRequestBuilder(),
                new JdkHttpTransport(Duration.ofSeconds(5)),
                new AssertionContextMapper(objectMapper),
                assertionEngine);
    }

    @Bean
    public RunExecutionService runExecutionService(
            ExecutionFactRepository repository,
            TestStepRunner stepRunner,
            ObjectMapper objectMapper,
            ObjectProvider<MeterRegistry> meterRegistryProvider) {
        return new RunExecutionService(
                repository,
                stepRunner,
                objectMapper,
                java.time.Clock.systemUTC(),
                meterRegistryProvider.getIfAvailable());
    }

    @Bean
    public AsyncExecutionApplicationService asyncExecutionApplicationService(
            ExecutionFactRepository repository,
            BatchExecutionCoordinator batchExecutionCoordinator) {
        return new AsyncExecutionApplicationService(repository, batchExecutionCoordinator);
    }

    @Bean(destroyMethod = "shutdown")
    public ThreadPoolExecutor runnerExecutor(RunnerBatchProperties properties) {
        return RunnerExecutorFactory.create(new RunnerExecutorProperties(
                properties.getCorePoolSize(),
                properties.getMaximumPoolSize(),
                properties.getKeepAliveTime(),
                properties.getQueueCapacity(),
                properties.getThreadNamePrefix()));
    }

    @Bean
    public BatchExecutionCoordinator batchExecutionCoordinator(
            ThreadPoolExecutor runnerExecutor,
            RunExecutionService runExecutionService,
            ObjectProvider<TaskProgressStore> progressStore,
            ObjectProvider<TaskProgressListener> progressListener) {
        TaskProgressStore store=progressStore.getIfAvailable();
        return store==null?new BatchExecutionCoordinator(runnerExecutor,runExecutionService):
                new BatchExecutionCoordinator(runnerExecutor,runExecutionService,store,
                        progressListener.getIfAvailable(TaskProgressListener::noop));
    }
}
