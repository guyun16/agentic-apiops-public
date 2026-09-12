package com.apiops.runner.http;

import java.util.List;
import java.util.Map;

/** Bounded, redacted presentation data. Never used for assertions or HTTP execution. */
public record HttpExchangeSnapshot(Request request, Response response) {
    public record Request(String method, String url, Map<String, List<String>> headers,
                          String body, String bodyState, boolean truncated) { }
    public record Response(int statusCode, Map<String, List<String>> headers,
                           String body, String bodyState, boolean truncated) { }
}
