package com.apiops.web.infrastructure.web;

import com.apiops.web.config.ApiOpsProperties;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.slf4j.MDC;
import org.springframework.mock.web.MockHttpServletRequest;
import org.springframework.mock.web.MockHttpServletResponse;

import java.util.concurrent.atomic.AtomicReference;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertThrows;

class TraceIdFilterTest {

    private static final String HEADER_NAME = "X-Test-Trace-Id";

    private TraceIdFilter filter;

    @BeforeEach
    void setUp() {
        removeMdcValues();
        ApiOpsProperties properties = new ApiOpsProperties(
                new ApiOpsProperties.Application("test", "test"),
                new ApiOpsProperties.Tracing(HEADER_NAME)
        );
        filter = new TraceIdFilter(properties);
    }

    @AfterEach
    void tearDown() {
        removeMdcValues();
    }

    @Test
    void shouldPreserveIncomingTraceIdInMdcAndResponseHeader() throws Exception {
        MockHttpServletRequest request = new MockHttpServletRequest();
        MockHttpServletResponse response = new MockHttpServletResponse();
        request.addHeader(HEADER_NAME, "incoming-trace-id");
        AtomicReference<String> traceIdInsideChain = new AtomicReference<>();

        filter.doFilter(request, response, (chainRequest, chainResponse) ->
                traceIdInsideChain.set(MDC.get(TraceIdFilter.TRACE_ID))
        );

        assertEquals("incoming-trace-id", traceIdInsideChain.get());
        assertEquals("incoming-trace-id", response.getHeader(HEADER_NAME));
    }

    @Test
    void shouldGenerateTraceIdWhenHeaderIsMissing() throws Exception {
        MockHttpServletRequest request = new MockHttpServletRequest();
        MockHttpServletResponse response = new MockHttpServletResponse();
        AtomicReference<String> traceIdInsideChain = new AtomicReference<>();

        filter.doFilter(request, response, (chainRequest, chainResponse) ->
                traceIdInsideChain.set(MDC.get(TraceIdFilter.TRACE_ID))
        );

        assertNotNull(traceIdInsideChain.get());
        assertFalse(traceIdInsideChain.get().isBlank());
        assertEquals(traceIdInsideChain.get(), response.getHeader(HEADER_NAME));
    }

    @Test
    void shouldGenerateTraceIdWhenHeaderIsBlank() throws Exception {
        MockHttpServletRequest request = new MockHttpServletRequest();
        MockHttpServletResponse response = new MockHttpServletResponse();
        request.addHeader(HEADER_NAME, "   ");
        AtomicReference<String> traceIdInsideChain = new AtomicReference<>();

        filter.doFilter(request, response, (chainRequest, chainResponse) ->
                traceIdInsideChain.set(MDC.get(TraceIdFilter.TRACE_ID))
        );

        assertNotNull(traceIdInsideChain.get());
        assertFalse(traceIdInsideChain.get().isBlank());
        assertNotEquals("   ", traceIdInsideChain.get());
        assertEquals(traceIdInsideChain.get(), response.getHeader(HEADER_NAME));
    }

    @Test
    void shouldGenerateNewRequestIdForEveryRequest() throws Exception {
        AtomicReference<String> firstRequestId = new AtomicReference<>();
        AtomicReference<String> secondRequestId = new AtomicReference<>();

        filter.doFilter(
                new MockHttpServletRequest(),
                new MockHttpServletResponse(),
                (request, response) ->
                        firstRequestId.set(MDC.get(TraceIdFilter.REQUEST_ID))
        );
        filter.doFilter(
                new MockHttpServletRequest(),
                new MockHttpServletResponse(),
                (request, response) ->
                        secondRequestId.set(MDC.get(TraceIdFilter.REQUEST_ID))
        );

        assertNotNull(firstRequestId.get());
        assertFalse(firstRequestId.get().isBlank());
        assertNotNull(secondRequestId.get());
        assertFalse(secondRequestId.get().isBlank());
        assertNotEquals(firstRequestId.get(), secondRequestId.get());
    }

    @Test
    void shouldRemoveMdcValuesAfterNormalCompletion() throws Exception {
        filter.doFilter(
                new MockHttpServletRequest(),
                new MockHttpServletResponse(),
                (request, response) -> {
                    assertNotNull(MDC.get(TraceIdFilter.TRACE_ID));
                    assertNotNull(MDC.get(TraceIdFilter.REQUEST_ID));
                }
        );

        assertNull(MDC.get(TraceIdFilter.TRACE_ID));
        assertNull(MDC.get(TraceIdFilter.REQUEST_ID));
    }

    @Test
    void shouldPropagateExceptionAndRemoveMdcValues() {
        IllegalStateException exception = assertThrows(
                IllegalStateException.class,
                () -> filter.doFilter(
                        new MockHttpServletRequest(),
                        new MockHttpServletResponse(),
                        (request, response) -> {
                            assertNotNull(MDC.get(TraceIdFilter.TRACE_ID));
                            assertNotNull(MDC.get(TraceIdFilter.REQUEST_ID));
                            throw new IllegalStateException("chain failure");
                        }
                )
        );

        assertEquals("chain failure", exception.getMessage());
        assertNull(MDC.get(TraceIdFilter.TRACE_ID));
        assertNull(MDC.get(TraceIdFilter.REQUEST_ID));
    }

    private void removeMdcValues() {
        MDC.remove(TraceIdFilter.TRACE_ID);
        MDC.remove(TraceIdFilter.REQUEST_ID);
    }
}
