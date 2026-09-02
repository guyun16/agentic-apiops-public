package com.apiops.tool.gateway;

import com.apiops.auth.enums.ProjectRole;
import com.apiops.auth.security.ApiOpsPrincipal;
import com.apiops.common.tool.ToolResult;
import com.apiops.rag.domain.EvidenceCitation;
import com.apiops.rag.retrieval.RagRetrieval;
import com.apiops.rag.retrieval.RagSearchResult;
import com.apiops.rag.retrieval.RagRetriever;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.authority.SimpleGrantedAuthority;
import org.springframework.security.core.context.SecurityContext;
import org.springframework.security.core.context.SecurityContextHolder;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.Set;

/** Stable rag.search contract and adapter to the existing Stage 10 RagRetriever. */
public final class RagSearchTool {

    public static final String TOOL_NAME = "rag.search";
    public static final String QUERY_ARGUMENT = "query";
    public static final String TOP_K_ARGUMENT = "topK";
    public static final String TARGET_PROJECT_ARGUMENT = "targetProjectId";
    public static final int MAX_QUERY_LENGTH = 4_096;
    public static final int MAX_TOP_K = 20;

    private RagSearchTool() {
    }

    public static ToolDefinition definition() {
        return ToolDefinition.withParameterContracts(
                TOOL_NAME,
                "Search project-scoped diagnostic knowledge and return cited evidence",
                Set.of("TOOL_READ"),
                Set.of(ProjectRole.OWNER, ProjectRole.EDITOR, ProjectRole.VIEWER),
                Map.of(
                        QUERY_ARGUMENT, ToolDefinition.ParameterContract.length(
                                String.class, 1, MAX_QUERY_LENGTH),
                        TOP_K_ARGUMENT, ToolDefinition.ParameterContract.range(
                                Integer.class, 1, MAX_TOP_K),
                        TARGET_PROJECT_ARGUMENT, ToolDefinition.ParameterContract.optionalRange(
                                Integer.class, 1, Integer.MAX_VALUE)
                ));
    }

    public static void register(ToolRegistry registry) {
        Objects.requireNonNull(registry, "registry must not be null").register(definition());
    }

    public static ToolResult<Object> execute(
            ToolGateway gateway,
            RagRetriever retriever,
            ToolExecutionContext context,
            ToolCallIntent intent
    ) {
        Objects.requireNonNull(gateway, "gateway must not be null");
        return gateway.execute(context, intent, handler(retriever));
    }

    /** Generic Gateway handler; it intentionally exposes no RAG internals to model callbacks. */
    public static ToolGateway.ToolHandler handler(RagRetriever retriever) {
        Objects.requireNonNull(retriever, "retriever must not be null");
        return (trustedContext, intent) -> retrieve(trustedContext, intent, retriever);
    }

    private static Object retrieve(
            ToolExecutionContext trustedContext,
            ToolCallIntent intent,
            RagRetriever retriever
    ) {
        Object queryValue = intent.arguments().get(QUERY_ARGUMENT);
        Object topKValue = intent.arguments().get(TOP_K_ARGUMENT);
        if (!(queryValue instanceof String query) || !(topKValue instanceof Number topKNumber)) {
            throw new IllegalArgumentException("RAG arguments are invalid");
        }
        final int topK;
        try {
            topK = new java.math.BigDecimal(topKNumber.toString()).intValueExact();
        } catch (ArithmeticException | NumberFormatException exception) {
            throw new IllegalArgumentException("topK must be an integer", exception);
        }

        long effectiveProjectId = effectiveProjectId(trustedContext, intent);

        return withTrustedSecurityContext(trustedContext, () ->
                toModelResult(retriever.retrieve(
                        effectiveProjectId, query, topK)));
    }

    /** Returns the untrusted requested scope, or the trusted current scope when omitted. */
    static long effectiveProjectId(ToolExecutionContext context, ToolCallIntent intent) {
        Objects.requireNonNull(context, "trusted context must not be null");
        Objects.requireNonNull(intent, "tool intent must not be null");
        Object targetValue = intent.arguments().get(TARGET_PROJECT_ARGUMENT);
        if (targetValue == null) {
            return context.projectId();
        }
        if (!(targetValue instanceof Integer targetProjectId) || targetProjectId < 1) {
            throw new IllegalArgumentException(
                    TARGET_PROJECT_ARGUMENT + " must be a positive integer");
        }
        return targetProjectId.longValue();
    }

    /** Returns only an explicitly supplied, schema-shaped target for safe audit facts. */
    static Long requestedTargetProjectId(ToolCallIntent intent) {
        if (intent == null || !TOOL_NAME.equals(intent.toolName())) {
            return null;
        }
        Object targetValue = intent.arguments().get(TARGET_PROJECT_ARGUMENT);
        return targetValue instanceof Integer targetProjectId && targetProjectId > 0
                ? targetProjectId.longValue()
                : null;
    }

    /**
     * Stage 10 reads the authenticated Java principal for its user identity. The Gateway
     * worker is a separate thread, so this scoped bridge copies only trusted context facts
     * into a temporary principal and always restores the previous worker context.
     */
    private static Object withTrustedSecurityContext(
            ToolExecutionContext context,
            java.util.function.Supplier<Object> action
    ) {
        Objects.requireNonNull(context, "trusted context must not be null");
        SecurityContext previous = SecurityContextHolder.getContext();
        SecurityContext trusted = SecurityContextHolder.createEmptyContext();
        ApiOpsPrincipal principal = new ApiOpsPrincipal(
                context.userId(),
                "tool-gateway-user-" + context.userId(),
                "[not-used-by-rag-tool]",
                true,
                context.authorities().stream()
                        .map(SimpleGrantedAuthority::new)
                        .toList());
        trusted.setAuthentication(UsernamePasswordAuthenticationToken.authenticated(
                principal, null, principal.getAuthorities()));
        SecurityContextHolder.setContext(trusted);
        try {
            return action.get();
        } finally {
            SecurityContextHolder.setContext(previous);
        }
    }

    /** Converts Stage 10 records to a sanitizer-friendly model result without losing citations. */
    private static Map<String, Object> toModelResult(RagRetrieval retrieval) {
        List<Map<String, Object>> results = new ArrayList<>();
        for (RagSearchResult result : retrieval.results()) {
            Map<String, Object> modelResult = new LinkedHashMap<>();
            modelResult.put("projectId", result.projectId());
            modelResult.put("documentId", result.documentId());
            modelResult.put("chunkId", result.chunkId());
            modelResult.put("content", result.content());
            modelResult.put("relevanceScore", result.relevanceScore());
            modelResult.put("citation", citation(result.citation()));
            results.add(modelResult);
        }
        Map<String, Object> modelResult = new LinkedHashMap<>();
        modelResult.put("ragQueryId", retrieval.ragQueryId());
        modelResult.put("results", List.copyOf(results));
        return modelResult;
    }

    private static Map<String, Object> citation(EvidenceCitation citation) {
        Map<String, Object> value = new LinkedHashMap<>();
        value.put("sourceType", citation.sourceType());
        value.put("sourceId", citation.sourceId());
        value.put("projectId", citation.projectId());
        value.put("documentId", citation.documentId());
        value.put("chunkId", citation.chunkId());
        value.put("score", citation.score());
        value.put("title", citation.title());
        value.put("location", citation.location());
        value.put("excerpt", citation.excerpt());
        return value;
    }
}
