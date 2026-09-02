package com.apiops.web.integration;

import com.apiops.common.enums.ErrorCode;
import com.apiops.common.exception.BusinessException;
import com.apiops.common.result.Result;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.slf4j.MDC;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.context.TestComponent;
import org.springframework.boot.test.system.CapturedOutput;
import org.springframework.boot.test.system.OutputCaptureExtension;
import org.springframework.context.annotation.Import;
import org.springframework.test.context.ActiveProfiles;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.regex.Matcher;
import java.util.regex.Pattern;

import static org.hamcrest.Matchers.containsString;
import static org.hamcrest.Matchers.not;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.springframework.security.test.web.servlet.request.SecurityMockMvcRequestPostProcessors.user;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.content;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.header;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

@SpringBootTest
@AutoConfigureMockMvc
@ActiveProfiles("test")
@Import(WebFoundationIntegrationTest.TestOnlyController.class)
@ExtendWith(OutputCaptureExtension.class)
class WebFoundationIntegrationTest {

    private static final String BASE_PATH = "/test/integration/web-foundation";
    private static final String TRACE_HEADER = "X-Trace-Id";
    private static final String BUSINESS_MESSAGE = "integration task status conflict";
    private static final String BUSINESS_CAUSE_DETAIL = "business cause detail";
    private static final String UNKNOWN_DETAIL = "unknown sensitive detail";
    private static final String LOG_TRACE_ID = "stage3-integration-log-trace";
    private static final String LOG_MARKER = "STAGE3_WEB_FOUNDATION_MDC_MARKER";
    private static final Pattern REQUEST_ID_PATTERN =
            Pattern.compile("\\[requestId=([^]]+)]");

    @Autowired
    private MockMvc mockMvc;

    @Test
    void shouldHandleBusinessExceptionThroughApplicationContext() throws Exception {
        String traceId = mockMvc.perform(get(BASE_PATH + "/business-error")
                        .with(user("test-user")))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.success").value(false))
                .andExpect(jsonPath("$.code").value("B0001"))
                .andExpect(jsonPath("$.message").value(BUSINESS_MESSAGE))
                .andExpect(jsonPath("$.data").doesNotExist())
                .andExpect(content().string(not(containsString(BUSINESS_CAUSE_DETAIL))))
                .andExpect(content().string(not(containsString("IllegalStateException"))))
                .andReturn()
                .getResponse()
                .getHeader(TRACE_HEADER);

        assertNotNull(traceId);
        assertFalse(traceId.isBlank());
    }

    @Test
    void shouldHandleUnknownExceptionWithoutLeakingDetails() throws Exception {
        String traceId = mockMvc.perform(get(BASE_PATH + "/unknown-error")
                        .with(user("test-user")))
                .andExpect(status().isInternalServerError())
                .andExpect(jsonPath("$.success").value(false))
                .andExpect(jsonPath("$.code").value("S0001"))
                .andExpect(jsonPath("$.message").value("system error"))
                .andExpect(jsonPath("$.data").doesNotExist())
                .andExpect(content().string(not(containsString(UNKNOWN_DETAIL))))
                .andExpect(content().string(not(containsString("RuntimeException"))))
                .andExpect(content().string(not(containsString("stackTrace"))))
                .andReturn()
                .getResponse()
                .getHeader(TRACE_HEADER);

        assertNotNull(traceId);
        assertFalse(traceId.isBlank());
    }

    @Test
    void shouldRenderTraceIdAndRequestIdInRequestLog(CapturedOutput output) throws Exception {
        mockMvc.perform(get(BASE_PATH + "/log")
                        .with(user("test-user"))
                        .header(TRACE_HEADER, LOG_TRACE_ID))
                .andExpect(status().isOk())
                .andExpect(header().string(TRACE_HEADER, LOG_TRACE_ID))
                .andExpect(jsonPath("$.success").value(true));

        String markerLine = output.getOut()
                .lines()
                .filter(line -> line.contains(LOG_MARKER))
                .findFirst()
                .orElseThrow(() -> new AssertionError("marker log line was not captured"));

        assertTrue(markerLine.contains("[traceId=" + LOG_TRACE_ID + "]"));

        Matcher requestIdMatcher = REQUEST_ID_PATTERN.matcher(markerLine);
        assertTrue(requestIdMatcher.find());
        assertFalse(requestIdMatcher.group(1).isBlank());

        assertNull(MDC.get("traceId"));
        assertNull(MDC.get("requestId"));
    }

    @TestComponent
    @RestController
    @RequestMapping(BASE_PATH)
    static class TestOnlyController {

        private static final Logger LOGGER =
                LoggerFactory.getLogger(TestOnlyController.class);

        @GetMapping("/business-error")
        Result<Void> businessError() {
            throw new BusinessException(
                    ErrorCode.TASK_STATUS_INVALID,
                    BUSINESS_MESSAGE,
                    new IllegalStateException(BUSINESS_CAUSE_DETAIL)
            );
        }

        @GetMapping("/unknown-error")
        Result<Void> unknownError() {
            throw new RuntimeException(UNKNOWN_DETAIL);
        }

        @GetMapping("/log")
        Result<Void> log() {
            LOGGER.info(LOG_MARKER);
            return Result.success(null);
        }
    }
}
