package com.apiops.runner.http;

import com.apiops.runner.dsl.RequestSpec;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.DeserializationFeature;
import com.fasterxml.jackson.databind.node.ArrayNode;
import com.fasterxml.jackson.databind.node.ObjectNode;
import com.fasterxml.jackson.databind.node.TextNode;

import java.net.URI;
import java.net.URLDecoder;
import java.net.http.HttpRequest;
import java.nio.charset.StandardCharsets;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Set;

/** Fail-closed capture: only JSON structure/numbers/booleans and safe HTTP metadata survive.
 * All JSON string values, credentials, query values and substituted path values are hidden.
 * Plain text, binary, malformed and oversized input are omitted, never partially parsed.
 */
public final class HttpExchangeCapture {
    private static final ObjectMapper JSON = new ObjectMapper()
            .enable(DeserializationFeature.FAIL_ON_TRAILING_TOKENS);
    public static final int MAX_BODY_CHARS = 8192;
    private static final int MAX_INPUT_CHARS = 65536;
    private static final String REDACTED = "[REDACTED]";
    private static final Set<String> SAFE_HEADERS = Set.of("content-type", "content-length");
    private HttpExchangeCapture() { }

    public static HttpExchangeSnapshot capture(HttpRequest request, RequestSpec spec,
                                               HttpResponseSnapshot response) {
        try {
            Body requestBody = body(spec.body());
            var requestHeaders = headers(request.headers().map());
            String url = url(request.uri(), spec);
            var capturedRequest = new HttpExchangeSnapshot.Request(request.method(), url,
                    requestHeaders, requestBody.text(), requestBody.state(),
                    requestBody.truncated() || request.headers().map().size() > 32 || url.length() >= 2048
                            || (request.uri().getRawQuery() != null
                            && request.uri().getRawQuery().split("&").length > 32));
            if (response == null) return new HttpExchangeSnapshot(capturedRequest, null);
            Body responseBody = responseBody(response);
            return new HttpExchangeSnapshot(capturedRequest, new HttpExchangeSnapshot.Response(
                    response.statusCode(), headers(response.headers()), responseBody.text(),
                    responseBody.state(), responseBody.truncated() || response.headers().size() > 32));
        } catch (RuntimeException ignored) {
            // Observability must not turn a successful execution into a failed execution.
            return null;
        }
    }

    private record Body(String text, String state, boolean truncated) { }
    private static Body body(JsonNode value) {
        if (value == null) return new Body(null, "empty", false);
        if (value.toString().length() > MAX_INPUT_CHARS) return new Body(null, "omitted", true);
        String safe = sanitize(value, 0).toString();
        return safe.length() <= MAX_BODY_CHARS ? new Body(safe, "captured", safe.contains("\"[OMITTED]\""))
                : new Body(safe.substring(0, MAX_BODY_CHARS), "captured", true);
    }

    private static Body responseBody(HttpResponseSnapshot response) {
        String raw = response.body();
        if (raw == null || raw.isEmpty()) return new Body(null, "empty", false);
        if (raw.length() > MAX_INPUT_CHARS) return new Body(null, "omitted", true);
        String contentType = response.headers().getOrDefault("content-type", List.of("")).getFirst()
                .split(";", 2)[0].trim().toLowerCase(Locale.ROOT);
        if (!(contentType.equals("application/json") || contentType.endsWith("+json"))) {
            return new Body(null, "omitted", false);
        }
        try {
            return body(JSON.readTree(raw));
        } catch (Exception ignored) {
            return new Body(null, "omitted", false);
        }
    }

    private static JsonNode sanitize(JsonNode value, int depth) {
        if (depth >= 16) return TextNode.valueOf("[OMITTED]");
        if (value.isTextual()) return TextNode.valueOf(REDACTED);
        if (value.isObject()) {
            ObjectNode copy = JSON.createObjectNode();
            value.fields().forEachRemaining(entry -> {
                String key = entry.getKey();
                if (!key.matches("[A-Za-z_][A-Za-z0-9_.-]{0,63}")) key = "[REDACTED_KEY]";
                copy.set(key, sensitive(key) ? TextNode.valueOf(REDACTED)
                        : sanitize(entry.getValue(), depth + 1));
            });
            return copy;
        }
        if (value.isArray()) {
            ArrayNode copy = JSON.createArrayNode();
            value.forEach(item -> copy.add(sanitize(item, depth + 1)));
            return copy;
        }
        return value;
    }

    private static boolean sensitive(String key) {
        return key.toLowerCase(Locale.ROOT).replaceAll("[^a-z0-9]", "")
                .matches(".*(authorization|cookie|password|passwd|pwd|secret|token|apikey|credential|session|privatekey|signature|otp|pin|email|phone|address|creditcard).*");
    }

    private static Map<String, List<String>> headers(Map<String, List<String>> input) {
        Map<String, List<String>> safe = new LinkedHashMap<>();
        input.entrySet().stream().limit(32).forEach(entry -> {
            String name = entry.getKey().toLowerCase(Locale.ROOT);
            if (!name.matches("[a-z0-9-]{1,64}")) return;
            String value = entry.getValue().isEmpty() ? "" : entry.getValue().getFirst();
            if (!SAFE_HEADERS.contains(name)) value = REDACTED;
            else if (name.equals("content-type")) {
                // Parameters may contain arbitrary secrets; keep only a valid MIME type.
                value = value.split(";", 2)[0].trim();
                if (!value.matches("[a-zA-Z0-9.+-]{1,64}/[a-zA-Z0-9.+-]{1,64}")) value = REDACTED;
            } else if (!value.matches("[0-9]{1,15}")) value = REDACTED;
            safe.put(name, List.of(value));
        });
        return Map.copyOf(safe);
    }

    private static String url(URI uri, RequestSpec spec) {
        String path = uri.getRawPath();
        // Keep actual static path segments but hide every parameter segment, including encoded ones.
        if (spec.pathParams() != null) {
            for (JsonNode value : spec.pathParams().values()) {
                String encoded = java.net.URLEncoder.encode(value.asText(), StandardCharsets.UTF_8)
                        .replace("+", "%20").replace("%7E", "~").replace("*", "%2A");
                if (!encoded.isEmpty()) path = path.replace(encoded, REDACTED);
            }
        }
        String[] segments = path.split("/", -1);
        boolean previousSensitive = false;
        for (int i = 1; i < segments.length; i++) {
            String decoded = URLDecoder.decode(segments[i], StandardCharsets.UTF_8);
            boolean currentSensitive = sensitive(decoded);
            if (currentSensitive || previousSensitive) segments[i] = REDACTED;
            previousSensitive = currentSensitive;
        }
        StringBuilder safe = new StringBuilder(uri.getScheme()).append("://")
                .append(uri.getHost()).append(uri.getPort() < 0 ? "" : ":" + uri.getPort())
                .append(String.join("/", segments));
        if (uri.getRawQuery() != null) {
            safe.append('?');
            String[] pairs = uri.getRawQuery().split("&");
            for (int i = 0; i < Math.min(pairs.length, 32); i++) {
                if (i > 0) safe.append('&');
                String key = URLDecoder.decode(pairs[i].split("=", 2)[0], StandardCharsets.UTF_8);
                safe.append(key.matches("[A-Za-z_][A-Za-z0-9_.-]{0,63}") ? key : REDACTED)
                        .append('=').append(REDACTED);
            }
        }
        return safe.substring(0, Math.min(safe.length(), 2048));
    }
}
