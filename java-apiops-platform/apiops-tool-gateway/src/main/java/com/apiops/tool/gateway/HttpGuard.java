package com.apiops.tool.gateway;

import java.net.Inet6Address;
import java.net.InetAddress;
import java.net.URI;
import java.net.UnknownHostException;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Objects;
import java.util.Set;

/** Exact-origin and DNS-aware SSRF policy for diagnostic HTTP reads. */
public final class HttpGuard implements ResourceGuard {
    public static final String TOOL_NAME = "http.read";
    public static final Set<String> METHODS = Set.of("GET", "HEAD");
    public static final int MAX_RESPONSE_BYTES = 65_536;
    private static final Set<String> CREDENTIAL_HEADERS = Set.of(
            "authorization", "cookie", "proxy-authorization");
    private static final Set<String> ALLOWED_REQUEST_HEADERS = Set.of("accept");

    private final Set<String> allowedOrigins;
    private final Set<String> privateOrigins;
    private final DnsResolver dnsResolver;

    public HttpGuard(Set<URI> allowedOrigins, DnsResolver dnsResolver) {
        this(allowedOrigins, Set.of(), dnsResolver);
    }

    public HttpGuard(Set<URI> allowedOrigins, Set<URI> privateOrigins,
                     DnsResolver dnsResolver) {
        this.allowedOrigins = normalizeOrigins(allowedOrigins);
        this.privateOrigins = normalizeOrigins(privateOrigins);
        if (!this.allowedOrigins.containsAll(this.privateOrigins)) {
            throw new IllegalArgumentException("private origins must also be allowlisted");
        }
        this.dnsResolver = Objects.requireNonNull(dnsResolver);
    }

    public static DnsResolver systemDns() {
        return host -> List.of(InetAddress.getAllByName(host));
    }

    @Override
    public Decision check(ToolExecutionContext context, ToolDefinition definition,
                          ToolCallIntent intent) {
        if (definition == null || !TOOL_NAME.equals(definition.name())) return Decision.allow();
        Validation validation = validate(intent);
        return validation.allowed() ? Decision.allow() : Decision.reject(validation.reason());
    }

    public Validation validate(ToolCallIntent intent) {
        if (intent == null) return Validation.reject("HTTP intent is required");
        Object methodValue = intent.arguments().get("method");
        Object urlValue = intent.arguments().get("url");
        if (!(methodValue instanceof String rawMethod) || !(urlValue instanceof String rawUrl)) {
            return Validation.reject("HTTP method and URL are required");
        }
        String method = rawMethod.toUpperCase(Locale.ROOT);
        if (!METHODS.contains(method)) return Validation.reject("HTTP method is not allowlisted");
        URI uri;
        try { uri = URI.create(rawUrl).normalize(); }
        catch (RuntimeException exception) { return Validation.reject("HTTP URL is malformed"); }
        if (!Set.of("http", "https").contains(lower(uri.getScheme())) || uri.getHost() == null
                || uri.getUserInfo() != null || uri.getFragment() != null) {
            return Validation.reject("HTTP URL scheme or authority is not allowed");
        }
        String origin;
        try { origin = origin(uri); }
        catch (RuntimeException exception) { return Validation.reject("HTTP origin is invalid"); }
        if (!allowedOrigins.contains(origin)) return Validation.reject("HTTP origin is not allowlisted");

        Map<String, String> headers = headers(intent.arguments().get("headers"));
        if (headers == null) return Validation.reject("HTTP headers are malformed");
        for (String name : headers.keySet()) {
            String normalized = lower(name);
            if (CREDENTIAL_HEADERS.contains(normalized)) {
                return Validation.reject("credential header injection is forbidden");
            }
            if (!ALLOWED_REQUEST_HEADERS.contains(normalized)) {
                return Validation.reject("HTTP request header is not allowlisted");
            }
        }

        boolean explicitlyPrivate = privateOrigins.contains(origin);
        if (isIpLiteral(uri.getHost()) && !explicitlyPrivate) {
            return Validation.reject("HTTP IP literals are forbidden");
        }
        List<InetAddress> addresses;
        try { addresses = dnsResolver.resolve(uri.getHost()); }
        catch (UnknownHostException exception) { return Validation.reject("HTTP hostname cannot be resolved"); }
        if (addresses == null || addresses.isEmpty()) return Validation.reject("HTTP hostname has no address");
        if (!explicitlyPrivate && addresses.stream().anyMatch(HttpGuard::isUnsafeAddress)) {
            return Validation.reject("HTTP hostname resolves to a private or local address");
        }
        return new Validation(true, "allowed", method, uri, headers, List.copyOf(addresses));
    }

    private static Map<String, String> headers(Object value) {
        if (!(value instanceof Map<?, ?> map) || map.size() > 8) return null;
        Map<String, String> result = new LinkedHashMap<>();
        for (Map.Entry<?, ?> entry : map.entrySet()) {
            if (!(entry.getKey() instanceof String key) || !(entry.getValue() instanceof String text)
                    || key.isBlank() || key.length() > 64 || text.length() > 1_024
                    || key.indexOf('\r') >= 0 || key.indexOf('\n') >= 0
                    || text.indexOf('\r') >= 0 || text.indexOf('\n') >= 0) return null;
            result.put(key, text);
        }
        return Map.copyOf(result);
    }

    private static Set<String> normalizeOrigins(Set<URI> values) {
        Objects.requireNonNull(values);
        return values.stream().map(HttpGuard::origin).collect(java.util.stream.Collectors.toUnmodifiableSet());
    }

    static String origin(URI uri) {
        Objects.requireNonNull(uri);
        String scheme = lower(uri.getScheme());
        if (!Set.of("http", "https").contains(scheme) || uri.getHost() == null
                || uri.getUserInfo() != null) throw new IllegalArgumentException("invalid origin");
        int port = uri.getPort() >= 0 ? uri.getPort() : ("https".equals(scheme) ? 443 : 80);
        return scheme + "://" + lower(uri.getHost()) + ":" + port;
    }

    private static boolean isIpLiteral(String host) {
        return host.indexOf(':') >= 0 || host.chars().allMatch(c -> Character.isDigit(c) || c == '.');
    }

    private static boolean isUnsafeAddress(InetAddress address) {
        if (address.isAnyLocalAddress() || address.isLoopbackAddress()
                || address.isLinkLocalAddress() || address.isSiteLocalAddress()
                || address.isMulticastAddress()) return true;
        if (address instanceof Inet6Address) {
            byte first = address.getAddress()[0];
            return (first & 0xfe) == 0xfc;
        }
        byte[] bytes = address.getAddress();
        return bytes.length == 4 && (bytes[0] & 0xff) == 169 && (bytes[1] & 0xff) == 254;
    }

    private static String lower(String value) {
        return value == null ? null : value.toLowerCase(Locale.ROOT);
    }

    @FunctionalInterface public interface DnsResolver {
        List<InetAddress> resolve(String host) throws UnknownHostException;
    }

    public record Validation(boolean allowed, String reason, String method, URI uri,
                             Map<String, String> headers, List<InetAddress> addresses) {
        public Validation {
            Objects.requireNonNull(reason);
            headers = headers == null ? Map.of() : Map.copyOf(headers);
            addresses = addresses == null ? List.of() : List.copyOf(addresses);
        }
        static Validation reject(String reason) {
            return new Validation(false, reason, null, null, Map.of(), List.of());
        }
    }
}
