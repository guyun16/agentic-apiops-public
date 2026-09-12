package com.apiops.web.config;

import com.apiops.auth.repository.AuthUserRepository;
import com.apiops.auth.repository.GlobalRbacRepository;
import com.apiops.auth.repository.JdbcAuthUserRepository;
import com.apiops.auth.repository.JdbcGlobalRbacRepository;
import com.apiops.auth.repository.JdbcProjectMembershipRepository;
import com.apiops.auth.repository.ProjectMembershipRepository;
import com.apiops.openapi.repository.JdbcOpenApiMetadataRepository;
import com.apiops.openapi.repository.OpenApiMetadataRepository;
import com.apiops.rag.repository.DocumentRepository;
import com.apiops.rag.repository.JdbcDocumentRepository;
import com.apiops.runner.application.AsyncExecutionApplicationService;
import com.apiops.runner.application.RunExecutionService;
import com.apiops.runner.persistence.ExecutionFactRepository;
import com.apiops.runner.persistence.JdbcExecutionFactRepository;
import com.apiops.tool.gateway.audit.JdbcToolAuditRepository;
import com.apiops.tool.gateway.audit.ToolAuditRepository;
import com.apiops.web.project.repository.JdbcProjectRepository;
import com.apiops.web.project.repository.ProjectRepository;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.jdbc.datasource.DataSourceTransactionManager;
import org.springframework.jdbc.datasource.TransactionAwareDataSourceProxy;
import org.springframework.test.context.ActiveProfiles;
import org.springframework.test.util.ReflectionTestUtils;

import javax.sql.DataSource;

import static org.junit.jupiter.api.Assertions.assertInstanceOf;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertSame;
@SpringBootTest(properties = {
        "apiops.datasource.auth.url=jdbc:mysql://localhost:3306/apiops_auth",
        "apiops.datasource.auth.username=root",
        "apiops.datasource.openapi.url=jdbc:mysql://localhost:3306/apiops_openapi",
        "apiops.datasource.openapi.username=root",
        "apiops.datasource.runner.url=jdbc:mysql://localhost:3306/apiops_runner",
        "apiops.datasource.runner.username=root",
        "apiops.datasource.tool-gateway.url=jdbc:mysql://localhost:3306/apiops_tool_gateway",
        "apiops.datasource.tool-gateway.username=root",
        "apiops.datasource.rag.url=jdbc:mysql://localhost:3306/apiops_rag",
        "apiops.datasource.rag.username=root"
})
@ActiveProfiles("test")
class RepositoryDataSourceBindingTest {

    @Autowired
    @Qualifier("authDataSource")
    private DataSource authDataSource;

    @Autowired
    @Qualifier("openApiDataSource")
    private DataSource openApiDataSource;

    @Autowired
    @Qualifier("runnerDataSource")
    private DataSource runnerDataSource;

    @Autowired
    @Qualifier("toolGatewayDataSource")
    private DataSource toolGatewayDataSource;

    @Autowired
    @Qualifier("ragDataSource")
    private DataSource ragDataSource;

    @Autowired
    private AuthUserRepository authUserRepository;

    @Autowired
    private GlobalRbacRepository globalRbacRepository;

    @Autowired
    private ProjectMembershipRepository projectMembershipRepository;

    @Autowired
    private ProjectRepository projectRepository;

    @Autowired
    private OpenApiMetadataRepository openApiMetadataRepository;

    @Autowired
    private ExecutionFactRepository executionFactRepository;

    @Autowired
    private ToolAuditRepository toolAuditRepository;

    @Autowired
    private DocumentRepository documentRepository;

    @Autowired
    private RunExecutionService runExecutionService;

    @Autowired
    private AsyncExecutionApplicationService asyncExecutionApplicationService;

    @Autowired
    @Qualifier("openApiTransactionManager")
    private DataSourceTransactionManager openApiTransactionManager;

    @Test
    void shouldBindEveryJdbcRepositoryToItsOwnedDataSource() {
        assertSame(authDataSource, repositoryDataSource(
                assertInstanceOf(JdbcAuthUserRepository.class, authUserRepository)));
        assertSame(authDataSource, repositoryDataSource(
                assertInstanceOf(JdbcGlobalRbacRepository.class, globalRbacRepository)));
        assertSame(authDataSource, repositoryDataSource(
                assertInstanceOf(JdbcProjectMembershipRepository.class,
                        projectMembershipRepository)));
        assertSame(authDataSource, repositoryDataSource(
                assertInstanceOf(JdbcProjectRepository.class, projectRepository)));

        JdbcOpenApiMetadataRepository openApiRepository = assertInstanceOf(
                JdbcOpenApiMetadataRepository.class, openApiMetadataRepository);
        TransactionAwareDataSourceProxy proxy = assertInstanceOf(
                TransactionAwareDataSourceProxy.class,
                repositoryDataSource(openApiRepository));
        assertSame(openApiDataSource, proxy.getTargetDataSource());

        assertSame(runnerDataSource, repositoryDataSource(
                assertInstanceOf(JdbcExecutionFactRepository.class,
                        executionFactRepository)));
        assertSame(toolGatewayDataSource, repositoryDataSource(
                assertInstanceOf(JdbcToolAuditRepository.class, toolAuditRepository)));
        assertSame(ragDataSource, repositoryDataSource(
                assertInstanceOf(JdbcDocumentRepository.class, documentRepository)));
        assertNotNull(runExecutionService);
        assertNotNull(asyncExecutionApplicationService);
        assertSame(openApiDataSource, openApiTransactionManager.getDataSource());
    }

    private static DataSource repositoryDataSource(Object repository) {
        return (DataSource) ReflectionTestUtils.getField(repository, "dataSource");
    }
}
