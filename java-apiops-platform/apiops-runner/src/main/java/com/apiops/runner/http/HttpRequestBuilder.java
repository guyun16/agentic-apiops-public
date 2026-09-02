package com.apiops.runner.http;

import com.apiops.common.enums.FailureType;
import com.apiops.runner.dsl.EnvironmentSpec;
import com.apiops.runner.dsl.RequestSpec;
import com.fasterxml.jackson.databind.JsonNode;

import java.net.URI;
import java.net.http.HttpRequest;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Set;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

public final class HttpRequestBuilder {

    private static final Pattern PATH_PARAMETER = Pattern.compile("\\{([^{}]+)}");
    private static final Set<String> METHODS = Set.of(
            "GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS", "TRACE");
    private static final char[] HEX = "0123456789ABCDEF".toCharArray();

    public HttpRequest build(EnvironmentSpec environment, RequestSpec request) {
        if (environment == null) {
            throw buildFailure("environment must not be null");
        }
        return build(environment.baseUrl(), request);
    }

    public HttpRequest build(String baseUrl, RequestSpec request) {
        if (request == null) {
            throw buildFailure("request must not be null");
        }
        URI baseUri = parseBaseUri(baseUrl);
        String method = normalizeMethod(request.method());
        String path = resolvePath(request.path(), request.pathParams());
        String encodedPath = encodePath(path);
        String query = encodeQuery(request.query());
        String target = baseUri.getScheme() + "://" + baseUri.getRawAuthority()
                + joinPaths(baseUri.getRawPath(), encodedPath)
                + (query.isEmpty() ? "" : "?" + query);

        final URI targetUri;
        try {
            targetUri = URI.create(target);
        } catch (IllegalArgumentException exception) {
            throw new HttpRequestBuildException(
                    FailureType.INVALID_TARGET_URI, "target URI is invalid", exception);
        }

        try {
            HttpRequest.Builder builder = HttpRequest.newBuilder(targetUri);
            if (request.headers() != null) {
                request.headers().forEach((name, value) -> {
                    if (name == null || name.isBlank() || value == null) {
                        throw buildFailure("header name and value must not be null or blank");
                    }
                    builder.header(name, value);
                });
            }
            JsonNode body = request.body();
            builder.method(method, body == null
                    ? HttpRequest.BodyPublishers.noBody()
                    : HttpRequest.BodyPublishers.ofString(
                            body.toString(), StandardCharsets.UTF_8));
            return builder.build();
        } catch (HttpRequestBuildException exception) {
            throw exception;
        } catch (RuntimeException exception) {
            throw new HttpRequestBuildException(
                    FailureType.REQUEST_BUILD_ERROR, "HTTP request could not be built", exception);
        }
    }

    private URI parseBaseUri(String baseUrl) {
        if (baseUrl == null || baseUrl.isBlank()) {
            throw buildFailure("baseUrl must not be blank");
        }
        final URI baseUri;
        try {
            baseUri = URI.create(baseUrl);
        } catch (IllegalArgumentException exception) {
            throw new HttpRequestBuildException(
                    FailureType.INVALID_TARGET_URI, "baseUrl is invalid", exception);
        }
        String scheme = baseUri.getScheme();
        if (!baseUri.isAbsolute()
                || baseUri.getRawAuthority() == null
                || !("http".equalsIgnoreCase(scheme) || "https".equalsIgnoreCase(scheme))
                || baseUri.getRawQuery() != null
                || baseUri.getRawFragment() != null) {
            throw new HttpRequestBuildException(
                    FailureType.INVALID_TARGET_URI, "baseUrl must be an absolute HTTP(S) URI");
        }
        return baseUri;
    }

    private String normalizeMethod(String method) {
        if (method == null || method.isBlank()) {
            throw buildFailure("HTTP method must not be blank");
        }
        String normalized = method.toUpperCase(Locale.ROOT);
        if (!METHODS.contains(normalized)) {
            throw buildFailure("HTTP method is not supported");
        }
        return normalized;
    }

    private String resolvePath(String path, Map<String, JsonNode> pathParams) {
        if (path == null || path.isBlank() || path.indexOf('?') >= 0 || path.indexOf('#') >= 0) {
            throw buildFailure("request path must be non-blank and must not contain query or fragment");
        }
        String normalizedPath = path.startsWith("/") ? path : "/" + path;
        Map<String, JsonNode> params = pathParams == null ? Map.of() : pathParams;
        Matcher matcher = PATH_PARAMETER.matcher(normalizedPath);
        Set<String> used = new HashSet<>();
        StringBuffer resolved = new StringBuffer();
        while (matcher.find()) {
            String name = matcher.group(1);
            JsonNode value = params.get(name);
            if (value == null || value.isNull()) {
                throw buildFailure("path parameter is missing");
            }
            matcher.appendReplacement(
                    resolved, Matcher.quoteReplacement(encodePathSegment(scalarValue(value))));
            used.add(name);
        }
        matcher.appendTail(resolved);
        if (used.size() != params.size() || !params.keySet().equals(used)) {
            throw buildFailure("path parameters contain an unused name");
        }
        return resolved.toString();
    }

    private String encodeQuery(Map<String, JsonNode> query) {
        if (query == null || query.isEmpty()) {
            return "";
        }
        List<String> pairs = new ArrayList<>();
        query.forEach((name, value) -> {
            if (name == null || name.isBlank() || value == null || value.isNull()) {
                throw buildFailure("query parameter name and value must be present");
            }
            if (value.isArray()) {
                if (value.isEmpty()) {
                    throw buildFailure("query parameter array must not be empty");
                }
                value.forEach(item -> pairs.add(
                        encodeComponent(name) + "=" + encodeComponent(scalarValue(item))));
            } else {
                pairs.add(encodeComponent(name) + "=" + encodeComponent(scalarValue(value)));
            }
        });
        return String.join("&", pairs);
    }

    private String scalarValue(JsonNode value) {
        if (value == null || value.isNull() || !value.isValueNode()) {
            throw buildFailure("path and query parameters must be scalar values");
        }
        return value.asText();
    }

    private String encodePath(String path) {
        StringBuilder encoded = new StringBuilder(path.length());
        for (int index = 0; index < path.length();) {
            char current = path.charAt(index);
            if (current == '/') {
                encoded.append(current);
                index++;
            } else if (current == '%' && index + 2 < path.length()
                    && isHex(path.charAt(index + 1)) && isHex(path.charAt(index + 2))) {
                encoded.append(current).append(path.charAt(index + 1)).append(path.charAt(index + 2));
                index += 3;
            } else {
                int codePoint = path.codePointAt(index);
                String value = new String(Character.toChars(codePoint));
                encoded.append(isPathSafe(codePoint) ? value : encodeComponent(value));
                index += Character.charCount(codePoint);
            }
        }
        return encoded.toString();
    }

    private String encodePathSegment(String value) {
        return encodeComponent(value);
    }

    private String encodeComponent(String value) {
        StringBuilder encoded = new StringBuilder();
        for (byte current : value.getBytes(StandardCharsets.UTF_8)) {
            int unsigned = current & 0xFF;
            if (isUnreserved(unsigned)) {
                encoded.append((char) unsigned);
            } else {
                encoded.append('%')
                        .append(HEX[unsigned >>> 4])
                        .append(HEX[unsigned & 0x0F]);
            }
        }
        return encoded.toString();
    }

    private String joinPaths(String basePath, String requestPath) {
        String left = basePath == null ? "" : basePath;
        if (left.endsWith("/")) {
            left = left.substring(0, left.length() - 1);
        }
        return (left + requestPath).isEmpty() ? "/" : left + requestPath;
    }

    private boolean isPathSafe(int codePoint) {
        return isUnreserved(codePoint)
                || ":@!$&'()*+,;=".indexOf(codePoint) >= 0;
    }

    private boolean isUnreserved(int codePoint) {
        return codePoint >= 'a' && codePoint <= 'z'
                || codePoint >= 'A' && codePoint <= 'Z'
                || codePoint >= '0' && codePoint <= '9'
                || codePoint == '-' || codePoint == '.' || codePoint == '_' || codePoint == '~';
    }

    private boolean isHex(char value) {
        return value >= '0' && value <= '9'
                || value >= 'a' && value <= 'f'
                || value >= 'A' && value <= 'F';
    }

    private HttpRequestBuildException buildFailure(String message) {
        return new HttpRequestBuildException(FailureType.REQUEST_BUILD_ERROR, message);
    }
}
