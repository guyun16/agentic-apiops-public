package com.apiops.runner.http;

import java.net.http.HttpRequest;

public interface HttpTransport {

    HttpResponseSnapshot execute(HttpRequest request);
}
