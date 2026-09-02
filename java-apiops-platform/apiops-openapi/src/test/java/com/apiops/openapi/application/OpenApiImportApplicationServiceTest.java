package com.apiops.openapi.application;

import com.apiops.auth.application.ProjectAuthorizationService;
import com.apiops.auth.enums.ProjectRole;
import com.apiops.auth.repository.ProjectMembershipRepository;
import com.apiops.auth.security.ApiOpsPrincipal;
import com.apiops.openapi.config.OpenApiImportProperties;
import com.apiops.openapi.domain.ApiDocument;
import com.apiops.openapi.domain.ApiEndpoint;
import com.apiops.openapi.domain.ApiExample;
import com.apiops.openapi.domain.ApiParameter;
import com.apiops.openapi.domain.ApiRequestSchema;
import com.apiops.openapi.domain.ApiResponseSchema;
import com.apiops.openapi.exception.OpenApiImportErrorCode;
import com.apiops.openapi.exception.OpenApiImportException;
import com.apiops.openapi.normalizer.OpenApiMetadataNormalizer;
import com.apiops.openapi.parser.OpenApiDocumentParser;
import com.apiops.openapi.repository.OpenApiMetadataRepository;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;
import org.springframework.mock.web.MockMultipartFile;
import org.springframework.security.access.AccessDeniedException;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.util.unit.DataSize;
import org.springframework.web.multipart.MultipartFile;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.support.SimpleTransactionStatus;

import java.io.IOException;
import java.io.InputStream;
import java.net.ServerSocket;
import java.net.SocketTimeoutException;
import java.nio.charset.StandardCharsets;
import java.util.List;
import java.util.Optional;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.ArgumentMatchers.anyString;

class OpenApiImportApplicationServiceTest {

    private static final long PROJECT_ID = 41L;
    private static final long USER_ID = 7L;

    @AfterEach
    void clearSecurityContext() {
        SecurityContextHolder.clearContext();
    }

    @Test
    void shouldRejectEmptyFile() {
        OpenApiImportException exception = assertThrows(
                OpenApiImportException.class,
                () -> service(DataSize.ofKilobytes(10), ProjectRole.OWNER).importDocument(
                        PROJECT_ID,
                        "orders",
                        file("openapi.yaml", new byte[0])
                )
        );

        assertEquals(OpenApiImportErrorCode.EMPTY_FILE, exception.errorCode());
    }

    @Test
    void shouldRejectOversizedFileBeforeReadingBytes() throws IOException {
        MultipartFile file = mock(MultipartFile.class);
        when(file.isEmpty()).thenReturn(false);
        when(file.getSize()).thenReturn(11L);

        OpenApiImportException exception = assertThrows(
                OpenApiImportException.class,
                () -> service(DataSize.ofBytes(10), ProjectRole.EDITOR)
                        .importDocument(PROJECT_ID, "orders", file)
        );

        assertEquals(OpenApiImportErrorCode.FILE_TOO_LARGE, exception.errorCode());
        verify(file, never()).getBytes();
    }

    @Test
    void shouldParseValidJsonAndYamlThroughTheExistingParser() {
        OpenApiImportApplicationService service = service(
                DataSize.ofKilobytes(20),
                ProjectRole.OWNER
        );

        OpenApiImportResult json = service.importDocument(
                PROJECT_ID,
                "orders-json",
                file("minimal.json", fixtureBytes("minimal.json"))
        );
        OpenApiImportResult yaml = service.importDocument(
                PROJECT_ID,
                "orders-yaml",
                file("minimal.yaml", fixtureBytes("minimal.yaml"))
        );

        assertEquals("3.0.3", json.parsedDocument().openapiVersion());
        assertEquals("getHealth", json.parsedDocument().openApi()
                .getPaths().get("/health").getGet().getOperationId());
        assertEquals("3.0.3", yaml.parsedDocument().openapiVersion());
    }

    @Test
    void shouldUseContentInsteadOfFilenameExtension() {
        OpenApiImportResult imported = service(DataSize.ofKilobytes(10), ProjectRole.OWNER)
                .importDocument(
                        PROJECT_ID,
                        "stable-source",
                        file("misleading.txt", fixtureBytes("minimal.yaml"))
                );

        assertEquals("stable-source", imported.sourceKey());
        assertEquals("misleading.txt", imported.filename());
        assertEquals("3.0.3", imported.parsedDocument().openapiVersion());
    }

    @Test
    void shouldRejectOrdinaryJsonThatIsNotOpenApi() {
        assertImportError("not-openapi.json", OpenApiImportErrorCode.INVALID_OPENAPI);
    }

    @Test
    void shouldRejectUnsupportedOpenApiVersion() {
        assertImportError(
                "unsupported-version.json",
                OpenApiImportErrorCode.UNSUPPORTED_OPENAPI_VERSION
        );
    }

    @Test
    void shouldHashOnlyTheExactRawBytes() {
        OpenApiImportApplicationService service = service(
                DataSize.ofKilobytes(20),
                ProjectRole.OWNER
        );
        byte[] original = fixtureBytes("minimal.json");
        byte[] changed = (new String(original, StandardCharsets.UTF_8) + "\n")
                .getBytes(StandardCharsets.UTF_8);

        String first = service.importDocument(
                PROJECT_ID, "source-a", file("one.json", original)
        ).contentHash();
        String same = service.importDocument(
                PROJECT_ID, "source-b", file("renamed.yaml", original)
        ).contentHash();
        String different = service.importDocument(
                PROJECT_ID, "source-a", file("one.json", changed)
        ).contentHash();

        assertEquals(first, same);
        assertNotEquals(first, different);
        assertEquals(64, first.length());
    }

    @Test
    void shouldRejectRemoteReferenceWithoutOpeningNetworkConnection() throws IOException {
        try (ServerSocket server = new ServerSocket(0)) {
            server.setSoTimeout(250);
            String document = """
                    openapi: 3.0.3
                    info:
                      title: Remote Ref
                      version: 1.0.0
                    paths: {}
                    components:
                      schemas:
                        Remote:
                          $ref: http://127.0.0.1:%d/schema.yaml#/Remote
                    """.formatted(server.getLocalPort());

            OpenApiImportException exception = assertThrows(
                    OpenApiImportException.class,
                    () -> service(DataSize.ofKilobytes(10), ProjectRole.OWNER)
                            .importDocument(
                                    PROJECT_ID,
                                    "remote-ref",
                                    file("remote.yaml", document.getBytes(StandardCharsets.UTF_8))
                            )
            );

            assertEquals(OpenApiImportErrorCode.REMOTE_REF_NOT_ALLOWED, exception.errorCode());
            assertThrows(SocketTimeoutException.class, server::accept);
        }
    }

    @Test
    void shouldDenyProjectAccessBeforeInspectingTheFile() throws IOException {
        authenticate();
        MultipartFile file = mock(MultipartFile.class);
        ProjectMembershipRepository noMembership = (userId, projectId) -> Optional.empty();
        OpenApiImportApplicationService service = new OpenApiImportApplicationService(
                new ProjectAuthorizationService(noMembership),
                new OpenApiDocumentParser(),
                properties(DataSize.ofKilobytes(10)),
                new OpenApiMetadataNormalizer(),
                repository(),
                transactionManager()
        );

        assertThrows(
                AccessDeniedException.class,
                () -> service.importDocument(PROJECT_ID, "orders", file)
        );
        verify(file, never()).isEmpty();
        verify(file, never()).getSize();
        verify(file, never()).getBytes();
    }

    private void assertImportError(String fixture, OpenApiImportErrorCode expected) {
        OpenApiImportException exception = assertThrows(
                OpenApiImportException.class,
                () -> service(DataSize.ofKilobytes(10), ProjectRole.OWNER)
                        .importDocument(
                                PROJECT_ID,
                                "orders",
                                file(fixture, fixtureBytes(fixture))
                        )
        );
        assertEquals(expected, exception.errorCode());
    }

    private OpenApiImportApplicationService service(DataSize limit, ProjectRole role) {
        authenticate();
        ProjectMembershipRepository membership = (userId, projectId) -> Optional.of(role);
        return new OpenApiImportApplicationService(
                new ProjectAuthorizationService(membership),
                new OpenApiDocumentParser(),
                properties(limit),
                new OpenApiMetadataNormalizer(),
                repository(),
                transactionManager()
        );
    }

    private OpenApiMetadataRepository repository() {
        OpenApiMetadataRepository repository = mock(OpenApiMetadataRepository.class);
        when(repository.findDocument(anyLong(), anyString(), anyString()))
                .thenReturn(Optional.empty());
        when(repository.findLatestDocument(anyLong(), anyString()))
                .thenReturn(Optional.empty());
        when(repository.save(any(ApiDocument.class)))
                .thenAnswer(invocation -> invocation.getArgument(0));
        when(repository.save(any(ApiEndpoint.class)))
                .thenAnswer(invocation -> invocation.getArgument(0));
        when(repository.save(any(ApiParameter.class)))
                .thenAnswer(invocation -> invocation.getArgument(0));
        when(repository.save(any(ApiRequestSchema.class)))
                .thenAnswer(invocation -> invocation.getArgument(0));
        when(repository.save(any(ApiResponseSchema.class)))
                .thenAnswer(invocation -> invocation.getArgument(0));
        when(repository.save(any(ApiExample.class)))
                .thenAnswer(invocation -> invocation.getArgument(0));
        return repository;
    }

    private PlatformTransactionManager transactionManager() {
        PlatformTransactionManager transactionManager = mock(PlatformTransactionManager.class);
        when(transactionManager.getTransaction(any()))
                .thenReturn(new SimpleTransactionStatus());
        return transactionManager;
    }

    private OpenApiImportProperties properties(DataSize limit) {
        OpenApiImportProperties properties = new OpenApiImportProperties();
        properties.setMaxFileSize(limit);
        return properties;
    }

    private void authenticate() {
        ApiOpsPrincipal principal = new ApiOpsPrincipal(
                USER_ID,
                "upload-user",
                "not-used",
                true,
                List.of()
        );
        SecurityContextHolder.getContext().setAuthentication(
                UsernamePasswordAuthenticationToken.authenticated(
                        principal,
                        null,
                        principal.getAuthorities()
                )
        );
    }

    private MockMultipartFile file(String filename, byte[] content) {
        return new MockMultipartFile("file", filename, null, content);
    }

    private byte[] fixtureBytes(String name) {
        try (InputStream input = getClass().getResourceAsStream("/openapi/" + name)) {
            if (input == null) {
                throw new IllegalArgumentException("Missing fixture: " + name);
            }
            return input.readAllBytes();
        } catch (IOException exception) {
            throw new IllegalStateException("Cannot read fixture: " + name, exception);
        }
    }
}
