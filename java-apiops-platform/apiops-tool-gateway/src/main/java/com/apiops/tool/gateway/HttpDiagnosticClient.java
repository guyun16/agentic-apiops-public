package com.apiops.tool.gateway;

import java.net.URI;
import java.util.List;
import java.util.Map;

/** Narrow GET/HEAD transport used only after HttpGuard approval. */
public interface HttpDiagnosticClient {
    Response send(String method, URI uri, Map<String, String> headers) throws Exception;

    record Response(int status, Map<String, List<String>> headers, String body) {
        public Response {
            headers = headers == null ? Map.of() : Map.copyOf(headers);
            body = body == null ? "" : body;
        }
    }
}
