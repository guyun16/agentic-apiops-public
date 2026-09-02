package com.apiops.tool.gateway;

import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.Map;
import java.util.Objects;

/** JDK HTTP client with redirects disabled and bounded response reads. */
public final class JdkHttpDiagnosticClient implements HttpDiagnosticClient {
    private final HttpClient client;
    private final Duration timeout;

    public JdkHttpDiagnosticClient(Duration timeout) {
        this(HttpClient.newBuilder().connectTimeout(positive(timeout))
                .followRedirects(HttpClient.Redirect.NEVER).build(), timeout);
    }

    public JdkHttpDiagnosticClient(HttpClient client, Duration timeout) {
        this.client = Objects.requireNonNull(client);
        this.timeout = positive(timeout);
        if (client.followRedirects() != HttpClient.Redirect.NEVER) {
            throw new IllegalArgumentException("diagnostic HTTP redirects must be disabled");
        }
    }

    @Override
    public Response send(String method, URI uri, Map<String, String> headers) throws Exception {
        if (!HttpGuard.METHODS.contains(method)) {
            throw new IllegalArgumentException("only GET and HEAD are supported");
        }
        HttpRequest.Builder builder = HttpRequest.newBuilder(uri).timeout(timeout)
                .method(method, HttpRequest.BodyPublishers.noBody());
        headers.forEach(builder::header);
        HttpResponse<InputStream> response = client.send(
                builder.build(), HttpResponse.BodyHandlers.ofInputStream());
        try (InputStream input = response.body()) {
            return new Response(response.statusCode(), response.headers().map(), readBounded(input));
        }
    }

    private static String readBounded(InputStream input) throws java.io.IOException {
        ByteArrayOutputStream output = new ByteArrayOutputStream();
        byte[] buffer = new byte[4_096];
        int total = 0;
        int read;
        while ((read = input.read(buffer)) >= 0) {
            total += read;
            if (total > HttpGuard.MAX_RESPONSE_BYTES) {
                throw new java.io.IOException("HTTP response exceeds byte limit");
            }
            output.write(buffer, 0, read);
        }
        return output.toString(StandardCharsets.UTF_8);
    }

    private static Duration positive(Duration value) {
        if (value == null || value.isZero() || value.isNegative()) {
            throw new IllegalArgumentException("HTTP timeout must be positive");
        }
        return value;
    }
}
