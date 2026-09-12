package com.apiops.agent.model.springai;

import com.apiops.agent.model.AgentModelClient;
import com.apiops.agent.diagnosis.DiagnosisAgent;
import com.apiops.agent.diagnosis.DiagnosisApplicationService;
import com.apiops.agent.diagnosis.DiagnosisCitationValidator;
import com.apiops.agent.diagnosis.DiagnosisReport;
import com.apiops.agent.diagnosis.DiagnosisReportCandidateMapper;
import com.apiops.agent.generation.GenerateTestCaseAgent;
import com.apiops.agent.generation.GenerateTestCaseApplicationService;
import com.apiops.agent.prompt.PromptTemplateService;
import com.apiops.agent.structured.BoundedStructuredOutputRepair;
import com.apiops.agent.structured.TestCaseCandidateMapper;
import com.apiops.auth.application.ProjectAuthorizationService;
import com.apiops.openapi.application.OpenApiQueryApplicationService;
import com.apiops.rag.retrieval.RagRetriever;
import com.apiops.rag.application.DiagnosticContextApplicationService;
import com.apiops.agent.tool.RagSearchToolCallbackFactory;
import com.apiops.report.application.TestReportQueryService;
import com.apiops.runner.application.RunExecutionService;
import com.apiops.runner.dsl.TestCase;
import com.apiops.runner.validation.TestCaseDslValidator;
import com.apiops.tool.gateway.Audit;
import com.apiops.tool.gateway.RagSearchTool;
import com.apiops.tool.gateway.RedisReadTool;
import com.apiops.tool.gateway.ResourceGuard;
import com.apiops.tool.gateway.ToolAuth;
import com.apiops.tool.gateway.ToolGateway;
import com.apiops.tool.gateway.ToolRegistry;
import com.apiops.tool.gateway.audit.ToolAuditRepository;
import com.fasterxml.jackson.databind.ObjectMapper;
import io.micrometer.core.instrument.MeterRegistry;
import org.springframework.ai.chat.model.ChatModel;
import org.springframework.boot.autoconfigure.condition.ConditionalOnBean;
import org.springframework.boot.autoconfigure.condition.ConditionalOnMissingBean;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.core.env.Environment;

import java.io.IOException;
import java.io.InputStream;
import java.time.Duration;

@Configuration(proxyBeanMethods = false)
public class AgentModelConfiguration {

    @Bean
    @ConditionalOnProperty(prefix = "spring.ai.model", name = "chat", havingValue = "openai")
    @ConditionalOnMissingBean(AgentModelClient.class)
    public AgentModelClient agentModelClient(ChatModel chatModel) {
        return new SpringAiAgentModelClient(chatModel);
    }

    @Bean
    @ConditionalOnBean(ProjectAuthorizationService.class)
    @ConditionalOnMissingBean(ToolRegistry.class)
    public ToolRegistry toolRegistry(ProjectAuthorizationService authorization) {
        ToolRegistry registry = new ToolRegistry(authorization);
        RagSearchTool.register(registry);
        RedisReadTool.register(registry);
        return registry;
    }

    @Bean
    @ConditionalOnBean({ToolRegistry.class, ProjectAuthorizationService.class})
    @ConditionalOnMissingBean(ToolAuth.class)
    public ToolAuth toolAuth(
            ToolRegistry registry,
            ProjectAuthorizationService authorization) {
        return new ToolAuth(registry, authorization);
    }

    @Bean
    @ConditionalOnMissingBean(Audit.class)
    public Audit toolAudit(ObjectProvider<ToolAuditRepository> repositoryProvider) {
        ToolAuditRepository repository = repositoryProvider.getIfAvailable();
        return repository == null ? new Audit() : new Audit(repository::save);
    }

    @Bean
    @ConditionalOnBean(ToolAuth.class)
    @ConditionalOnMissingBean(ToolGateway.class)
    public ToolGateway toolGateway(
            ToolAuth toolAuth,
            ProjectAuthorizationService authorization,
            Audit audit,
            ObjectProvider<MeterRegistry> meterRegistryProvider,
            ObjectProvider<ResourceGuard> resourceGuardProvider,
            Environment environment) {
        ResourceGuard configuredGuard = resourceGuardProvider.getIfAvailable(ResourceGuard::allowAll);
        ResourceGuard projectScopedGuard = ResourceGuard.allOf(
                configuredGuard,
                ResourceGuard.projectReadable(authorization));
        Duration executionTimeout = environment.getProperty(
                "apiops.tool.gateway.execution-timeout",
                Duration.class,
                Duration.ofSeconds(4));
        return new ToolGateway(
                toolAuth,
                projectScopedGuard,
                audit,
                meterRegistryProvider.getIfAvailable(),
                executionTimeout);
    }

    @Bean
    @ConditionalOnBean({ToolGateway.class, ToolRegistry.class, RagRetriever.class})
    @ConditionalOnMissingBean(RagSearchToolCallbackFactory.class)
    public RagSearchToolCallbackFactory ragSearchToolCallbackFactory(
            ToolGateway gateway,
            ToolRegistry registry,
            RagRetriever retriever,
            ObjectMapper objectMapper) {
        return new RagSearchToolCallbackFactory(gateway, registry, retriever, objectMapper);
    }

    @Bean
    @ConditionalOnMissingBean(PromptTemplateService.class)
    public PromptTemplateService promptTemplateService() {
        return new PromptTemplateService();
    }

    @Bean
    @ConditionalOnBean(AgentModelClient.class)
    @ConditionalOnMissingBean(GenerateTestCaseAgent.class)
    public GenerateTestCaseAgent generateTestCaseAgent(
            PromptTemplateService prompts,
            AgentModelClient modelClient,
            ObjectMapper objectMapper) {
        TestCaseDslValidator validator = testCaseDslValidator(objectMapper);
        TestCaseCandidateMapper mapper = new TestCaseCandidateMapper(validator);
        BoundedStructuredOutputRepair<TestCase> structuredOutput =
                new BoundedStructuredOutputRepair<>(modelClient, mapper);
        return new GenerateTestCaseAgent(prompts, structuredOutput, objectMapper);
    }

    @Bean
    @ConditionalOnBean({
            GenerateTestCaseAgent.class,
            RunExecutionService.class,
            ProjectAuthorizationService.class
    })
    @ConditionalOnMissingBean(GenerateTestCaseApplicationService.class)
    public GenerateTestCaseApplicationService generateTestCaseApplicationService(
            OpenApiQueryApplicationService metadataQueries,
            GenerateTestCaseAgent agent,
            RunExecutionService runner,
            ProjectAuthorizationService authorization) {
        return new GenerateTestCaseApplicationService(
                metadataQueries, agent, runner, authorization,
                new com.apiops.agent.structured.TestCaseTargetValidator());
    }

    @Bean
    @ConditionalOnMissingBean(DiagnosisReportCandidateMapper.class)
    public DiagnosisReportCandidateMapper diagnosisReportCandidateMapper(
            ObjectMapper objectMapper) {
        return DiagnosisReportCandidateMapper.fromClasspath(objectMapper);
    }

    @Bean
    @ConditionalOnBean(AgentModelClient.class)
    @ConditionalOnMissingBean(BoundedStructuredOutputRepair.class)
    public BoundedStructuredOutputRepair<DiagnosisReport> diagnosisStructuredOutput(
            AgentModelClient modelClient,
            DiagnosisReportCandidateMapper mapper) {
        return new BoundedStructuredOutputRepair<>(modelClient, mapper);
    }

    @Bean
    @ConditionalOnBean({AgentModelClient.class, BoundedStructuredOutputRepair.class})
    @ConditionalOnMissingBean(DiagnosisAgent.class)
    public DiagnosisAgent diagnosisAgent(
            PromptTemplateService prompts,
            BoundedStructuredOutputRepair<DiagnosisReport> structuredOutput,
            ObjectMapper objectMapper) {
        return new DiagnosisAgent(prompts, structuredOutput, objectMapper);
    }

    @Bean
    @ConditionalOnMissingBean(DiagnosisCitationValidator.class)
    public DiagnosisCitationValidator diagnosisCitationValidator() {
        return new DiagnosisCitationValidator();
    }

    @Bean
    @ConditionalOnBean({
            DiagnosticContextApplicationService.class,
            TestReportQueryService.class,
            DiagnosisAgent.class,
            ProjectAuthorizationService.class
    })
    @ConditionalOnMissingBean(DiagnosisApplicationService.class)
    public DiagnosisApplicationService diagnosisApplicationService(
            DiagnosticContextApplicationService contextService,
            TestReportQueryService reportQueryService,
            DiagnosisAgent agent,
            ProjectAuthorizationService authorization,
            DiagnosisCitationValidator citationValidator) {
        return new DiagnosisApplicationService(
                contextService, reportQueryService, agent, authorization, citationValidator);
    }

    private TestCaseDslValidator testCaseDslValidator(ObjectMapper objectMapper) {
        try (InputStream input = AgentModelConfiguration.class.getResourceAsStream(
                "/shared-schemas/testcase-dsl-schema.json")) {
            if (input == null) {
                throw new IllegalStateException(
                        "Shared TestCase DSL schema is not available on the classpath");
            }
            return new TestCaseDslValidator(objectMapper, objectMapper.readTree(input));
        } catch (IOException exception) {
            throw new IllegalStateException(
                    "Unable to load the shared TestCase DSL schema", exception);
        }
    }
}
