package com.apiops.tool.gateway;

import java.io.BufferedInputStream;
import java.io.ByteArrayOutputStream;
import java.io.EOFException;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.InetSocketAddress;
import java.net.Socket;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.ArrayList;
import java.util.List;

/** Minimal RESP2 adapter with only the four read methods exposed by RedisReadClient. */
public final class SocketRedisReadClient implements RedisReadClient {
    private final String host;
    private final int port;
    private final String password;
    private final int timeoutMillis;

    public SocketRedisReadClient(String host, int port, String password, Duration timeout) {
        if (host == null || host.isBlank() || port < 1 || port > 65_535) {
            throw new IllegalArgumentException("valid Redis host and port are required");
        }
        if (timeout == null || timeout.isZero() || timeout.isNegative()) {
            throw new IllegalArgumentException("Redis timeout must be positive");
        }
        this.host = host;
        this.port = port;
        this.password = password == null ? "" : password;
        this.timeoutMillis = Math.toIntExact(Math.max(1,
                Math.min(Integer.MAX_VALUE, timeout.toMillis())));
    }

    @Override public Object get(String key) throws Exception { return send("GET", key); }
    @Override public Object hget(String key, String field) throws Exception {
        return send("HGET", key, field);
    }
    @Override public Object hmget(String key, List<String> fields) throws Exception {
        List<String> command = new ArrayList<>();
        command.add("HMGET"); command.add(key); command.addAll(fields);
        return send(command.toArray(String[]::new));
    }
    @Override public Object ttl(String key) throws Exception { return send("TTL", key); }

    private Object send(String... command) throws Exception {
        try (Socket socket = new Socket()) {
            socket.connect(new InetSocketAddress(host, port), timeoutMillis);
            socket.setSoTimeout(timeoutMillis);
            InputStream input = new BufferedInputStream(socket.getInputStream());
            OutputStream output = socket.getOutputStream();
            if (!password.isEmpty()) {
                write(output, "AUTH", password);
                Object auth = read(input);
                if (!"OK".equals(auth)) throw new IOException("Redis authentication failed");
            }
            write(output, command);
            return read(input);
        }
    }

    private static void write(OutputStream output, String... values) throws IOException {
        output.write(("*" + values.length + "\r\n").getBytes(StandardCharsets.UTF_8));
        for (String value : values) {
            byte[] bytes = value.getBytes(StandardCharsets.UTF_8);
            output.write(("$" + bytes.length + "\r\n").getBytes(StandardCharsets.UTF_8));
            output.write(bytes); output.write('\r'); output.write('\n');
        }
        output.flush();
    }

    private static Object read(InputStream input) throws IOException {
        int type = input.read();
        if (type < 0) throw new EOFException("Redis closed the connection");
        return switch (type) {
            case '+' -> line(input);
            case '-' -> throw new IOException("Redis error: " + line(input));
            case ':' -> Long.parseLong(line(input));
            case '$' -> bulk(input);
            case '*' -> array(input);
            default -> throw new IOException("Unsupported Redis response type");
        };
    }

    private static Object bulk(InputStream input) throws IOException {
        int length = Integer.parseInt(line(input));
        if (length == -1) return null;
        if (length < 0 || length > RedisGuard.MAX_RESULT_BYTES) {
            throw new IOException("Redis bulk response exceeds byte limit");
        }
        byte[] bytes = input.readNBytes(length);
        if (bytes.length != length || input.read() != '\r' || input.read() != '\n') {
            throw new EOFException("Incomplete Redis bulk response");
        }
        return new String(bytes, StandardCharsets.UTF_8);
    }

    private static List<Object> array(InputStream input) throws IOException {
        int count = Integer.parseInt(line(input));
        if (count == -1) return List.of();
        if (count < 0 || count > RedisGuard.MAX_FIELDS) {
            throw new IOException("Redis array response exceeds item limit");
        }
        List<Object> result = new ArrayList<>(count);
        for (int index = 0; index < count; index++) result.add(read(input));
        return java.util.Collections.unmodifiableList(result);
    }

    private static String line(InputStream input) throws IOException {
        ByteArrayOutputStream bytes = new ByteArrayOutputStream();
        int previous = -1;
        while (true) {
            int current = input.read();
            if (current < 0) throw new EOFException("Incomplete Redis response");
            if (previous == '\r' && current == '\n') break;
            if (previous >= 0) bytes.write(previous);
            previous = current;
            if (bytes.size() > 1_024) throw new IOException("Redis response line is too long");
        }
        return bytes.toString(StandardCharsets.UTF_8);
    }
}
