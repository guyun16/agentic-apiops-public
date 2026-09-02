package com.apiops.runner.http;

import com.apiops.common.enums.FailureType;

import javax.net.ssl.SSLException;
import java.io.IOException;
import java.net.ConnectException;
import java.net.UnknownHostException;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.net.http.HttpTimeoutException;
import java.nio.channels.UnresolvedAddressException;
import java.time.Duration;
import java.util.Objects;

public final class JdkHttpTransport implements HttpTransport {

    private final HttpClient client;
    private final Duration timeout;

    public JdkHttpTransport(Duration timeout) {
        this(HttpClient.newBuilder().connectTimeout(requirePositive(timeout)).build(), timeout);
    }

    public JdkHttpTransport(HttpClient client, Duration timeout) {
        this.client = Objects.requireNonNull(client, "client must not be null");
        this.timeout = requirePositive(timeout);
    }

    @Override
    public HttpResponseSnapshot execute(HttpRequest request) {
        Objects.requireNonNull(request, "request must not be null");
        HttpRequest effectiveRequest = withTimeout(request);
        long started = System.nanoTime();
        try {
            HttpResponse<String> response = client.send(
                    effectiveRequest, HttpResponse.BodyHandlers.ofString());
            long durationMs = Duration.ofNanos(System.nanoTime() - started).toMillis();
            return new HttpResponseSnapshot(
                    response.statusCode(), response.headers().map(), response.body(), durationMs);
        } catch (HttpTimeoutException exception) {
            throw transportFailure(FailureType.TIMEOUT, "HTTP request timed out", exception);
        } catch (UnresolvedAddressException exception) {
            throw transportFailure(FailureType.DNS_ERROR, "HTTP target could not be resolved", exception);
        } catch (IOException exception) {
            throw transportFailure(classify(exception), "HTTP request failed", exception);
        } catch (InterruptedException exception) {
            Thread.currentThread().interrupt();
            throw transportFailure(FailureType.IO_ERROR, "HTTP request was interrupted", exception);
        }
    }

    private HttpRequest withTimeout(HttpRequest request) {
        if (request.timeout().isPresent()) {
            return request;
        }
        HttpRequest.Builder builder = HttpRequest.newBuilder(request.uri())
                .timeout(timeout)
                .expectContinue(request.expectContinue())
                .method(request.method(), request.bodyPublisher()
                        .orElse(HttpRequest.BodyPublishers.noBody()));
        request.version().ifPresent(builder::version);
        request.headers().map().forEach((name, values) ->
                values.forEach(value -> builder.header(name, value)));
        return builder.build();
    }

    private FailureType classify(IOException exception) {
        if (hasCause(exception, UnknownHostException.class)
                || hasCause(exception, UnresolvedAddressException.class)) {
            return FailureType.DNS_ERROR;
        }
        if (hasCause(exception, SSLException.class)) {
            return FailureType.TLS_ERROR;
        }
        if (hasCause(exception, ConnectException.class)) {
            return FailureType.CONNECT_ERROR;
        }
        return FailureType.IO_ERROR;
    }

    private boolean hasCause(Throwable source, Class<? extends Throwable> type) {
        for (Throwable current = source; current != null; current = current.getCause()) {
            if (type.isInstance(current)) {
                return true;
            }
        }
        return false;
    }

    private HttpTransportException transportFailure(
            FailureType failureType, String message, Throwable cause) {
        return new HttpTransportException(failureType, message, cause);
    }

    private static Duration requirePositive(Duration timeout) {
        Objects.requireNonNull(timeout, "timeout must not be null");
        if (timeout.isZero() || timeout.isNegative()) {
            throw new IllegalArgumentException("timeout must be positive");
        }
        return timeout;
    }
}
