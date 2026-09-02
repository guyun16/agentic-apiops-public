package com.apiops.openapi.application;

import com.apiops.auth.application.ProjectAuthorizationService;
import com.apiops.auth.security.ApiOpsPrincipal;
import com.apiops.openapi.config.OpenApiImportProperties;
import com.apiops.openapi.domain.ApiDocument;
import com.apiops.openapi.domain.ApiExample;
import com.apiops.openapi.exception.OpenApiImportErrorCode;
import com.apiops.openapi.exception.OpenApiImportException;
import com.apiops.openapi.normalizer.NormalizedOpenApiMetadata;
import com.apiops.openapi.normalizer.OpenApiMetadataNormalizer;
import com.apiops.openapi.parser.OpenApiDocumentParser;
import com.apiops.openapi.parser.OpenApiParseErrorType;
import com.apiops.openapi.parser.OpenApiParseException;
import com.apiops.openapi.parser.ParsedOpenApiDocument;
import com.apiops.openapi.repository.OpenApiMetadataRepository;
import com.fasterxml.jackson.databind.JsonNode;
import io.swagger.v3.core.util.Json;
import org.springframework.security.access.AccessDeniedException;
import org.springframework.security.access.prepost.PreAuthorize;
import org.springframework.security.core.Authentication;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.support.TransactionTemplate;
import org.springframework.web.multipart.MultipartFile;

import java.io.IOException;
import java.net.URI;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.HexFormat;
import java.util.Iterator;
import java.util.HashMap;
import java.util.Map;
import java.util.Objects;
import java.util.Optional;
import java.util.UUID;

public class OpenApiImportApplicationService {

    private final ProjectAuthorizationService projectAuthorizationService;
    private final OpenApiDocumentParser parser;
    private final OpenApiImportProperties properties;
    private final OpenApiMetadataNormalizer normalizer;
    private final OpenApiMetadataRepository repository;
    private final TransactionTemplate transactionTemplate;

    public OpenApiImportApplicationService(
            ProjectAuthorizationService projectAuthorizationService,
            OpenApiDocumentParser parser,
            OpenApiImportProperties properties,
            OpenApiMetadataNormalizer normalizer,
            OpenApiMetadataRepository repository,
            PlatformTransactionManager transactionManager
    ) {
        this.projectAuthorizationService = projectAuthorizationService;
        this.parser = parser;
        this.properties = properties;
        this.normalizer = normalizer;
        this.repository = repository;
        this.transactionTemplate = new TransactionTemplate(transactionManager);
    }

    @PreAuthorize("isAuthenticated()")
    public OpenApiImportResult importDocument(
            long projectId,
            String sourceKey,
            MultipartFile file
    ) {
        long userId = currentUserId();
        projectAuthorizationService.requireProjectEditable(userId, projectId);

        if (sourceKey == null || sourceKey.isBlank()) {
            throw new OpenApiImportException(OpenApiImportErrorCode.INVALID_SOURCE_KEY);
        }
        if (file == null || file.isEmpty()) {
            throw new OpenApiImportException(OpenApiImportErrorCode.EMPTY_FILE);
        }
        if (file.getSize() > properties.getMaxFileSize().toBytes()) {
            throw new OpenApiImportException(OpenApiImportErrorCode.FILE_TOO_LARGE);
        }

        byte[] rawBytes = read(file);
        String contentHash = sha256(rawBytes);
        String normalizedSourceKey = sourceKey.trim();
        ParsedOpenApiDocument parsed = parse(rawBytes);
        if (containsRemoteReference(Json.mapper().valueToTree(parsed.openApi()))) {
            throw new OpenApiImportException(OpenApiImportErrorCode.REMOTE_REF_NOT_ALLOWED);
        }

        Optional<ApiDocument> existing = repository.findDocument(
                projectId, normalizedSourceKey, contentHash);
        if (existing.isPresent()) {
            return result(existing.get(), rawBytes.length, parsed, true);
        }

        String apiDocId = businessId("api_doc");
        NormalizedOpenApiMetadata metadata = normalizer.normalize(
                parsed, apiDocId, projectId, (method, path) -> businessId("api"));

        try {
            return Objects.requireNonNull(transactionTemplate.execute(status -> {
                Optional<ApiDocument> raced = repository.findDocument(
                        projectId, normalizedSourceKey, contentHash);
                if (raced.isPresent()) {
                    return result(raced.get(), rawBytes.length, parsed, true);
                }
                int version = repository.findLatestDocument(projectId, normalizedSourceKey)
                        .map(document -> document.versionNo() + 1)
                        .orElse(1);
                ApiDocument document = repository.save(document(
                        parsed, apiDocId, projectId, normalizedSourceKey,
                        file.getOriginalFilename(), rawBytes, contentHash, version, userId));
                saveMetadata(metadata);
                return result(document, rawBytes.length, parsed, false);
            }));
        } catch (RuntimeException failure) {
            Optional<ApiDocument> concurrent = repository.findDocument(
                    projectId, normalizedSourceKey, contentHash);
            if (concurrent.isPresent()) {
                return result(concurrent.get(), rawBytes.length, parsed, true);
            }
            throw failure;
        }
    }

    private ApiDocument document(
            ParsedOpenApiDocument parsed,
            String apiDocId,
            long projectId,
            String sourceKey,
            String filename,
            byte[] rawBytes,
            String contentHash,
            int version,
            long userId
    ) {
        String rawContent = new String(rawBytes, StandardCharsets.UTF_8);
        String title = parsed.openApi().getInfo().getTitle();
        String apiVersion = parsed.openApi().getInfo().getVersion();
        return new ApiDocument(
                0, apiDocId, projectId, sourceKey,
                filename == null || filename.isBlank() ? sourceKey : filename,
                parsed.openapiVersion(), title, apiVersion,
                rawContent.stripLeading().startsWith("{") ? "JSON" : "YAML",
                contentHash, rawContent, version, "ACTIVE", userId, null, null
        );
    }

    private void saveMetadata(NormalizedOpenApiMetadata metadata) {
        metadata.endpoints().forEach(repository::save);
        Map<Long, Long> ownerIds = new HashMap<>();
        metadata.parameters().forEach(value ->
                ownerIds.put(value.id(), repository.save(value).id()));
        metadata.requestSchemas().forEach(value ->
                ownerIds.put(value.id(), repository.save(value).id()));
        metadata.responseSchemas().forEach(value ->
                ownerIds.put(value.id(), repository.save(value).id()));
        metadata.examples().forEach(value -> {
            Long ownerId = ownerIds.get(value.ownerRefId());
            if (ownerId == null) {
                throw new IllegalStateException(
                        "Example owner was not persisted: " + value.ownerRefId());
            }
            repository.save(new ApiExample(
                    0, value.apiId(), value.projectId(), value.ownerType(), ownerId,
                    value.exampleName(), value.summary(), value.description(),
                    value.valueJson(), null));
        });
    }

    private OpenApiImportResult result(
            ApiDocument document,
            long fileSize,
            ParsedOpenApiDocument parsed,
            boolean existing
    ) {
        return new OpenApiImportResult(
                document.projectId(), document.sourceKey(), document.documentName(),
                fileSize, document.contentHash(), parsed,
                document.apiDocId(), document.versionNo(), existing
        );
    }

    private String businessId(String prefix) {
        return prefix + "_" + UUID.randomUUID().toString().replace("-", "");
    }

    private long currentUserId() {
        Authentication authentication = SecurityContextHolder.getContext().getAuthentication();
        if (authentication == null
                || !authentication.isAuthenticated()
                || !(authentication.getPrincipal() instanceof ApiOpsPrincipal principal)) {
            throw new AccessDeniedException("Authenticated ApiOpsPrincipal required");
        }
        return principal.getUserId();
    }

    private byte[] read(MultipartFile file) {
        try {
            return file.getBytes();
        } catch (IOException exception) {
            throw new OpenApiImportException(OpenApiImportErrorCode.FILE_READ_FAILED, exception);
        }
    }

    private String sha256(byte[] rawBytes) {
        try {
            return HexFormat.of().formatHex(
                    MessageDigest.getInstance("SHA-256").digest(rawBytes)
            );
        } catch (NoSuchAlgorithmException exception) {
            throw new IllegalStateException("SHA-256 is unavailable", exception);
        }
    }

    private ParsedOpenApiDocument parse(byte[] rawBytes) {
        try {
            return parser.parse(new String(rawBytes, StandardCharsets.UTF_8));
        } catch (OpenApiParseException exception) {
            OpenApiImportErrorCode errorCode =
                    exception.errorType() == OpenApiParseErrorType.UNSUPPORTED_OPENAPI_VERSION
                            ? OpenApiImportErrorCode.UNSUPPORTED_OPENAPI_VERSION
                            : OpenApiImportErrorCode.INVALID_OPENAPI;
            throw new OpenApiImportException(errorCode, exception);
        }
    }

    private boolean containsRemoteReference(JsonNode node) {
        if (node.isObject()) {
            Iterator<Map.Entry<String, JsonNode>> fields = node.properties().iterator();
            while (fields.hasNext()) {
                Map.Entry<String, JsonNode> field = fields.next();
                if ("$ref".equals(field.getKey())
                        && field.getValue().isTextual()
                        && isRemote(field.getValue().textValue())) {
                    return true;
                }
                if (containsRemoteReference(field.getValue())) {
                    return true;
                }
            }
        } else if (node.isArray()) {
            for (JsonNode child : node) {
                if (containsRemoteReference(child)) {
                    return true;
                }
            }
        }
        return false;
    }

    private boolean isRemote(String reference) {
        try {
            return reference.startsWith("//") || URI.create(reference).isAbsolute();
        } catch (IllegalArgumentException exception) {
            return false;
        }
    }
}
