package com.apiops.web.runner.controller;

import com.apiops.web.exception.GlobalExceptionHandler;
import com.apiops.web.runner.application.AsyncBatchHttpApplicationService;
import org.junit.jupiter.api.Test;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;

import static org.hamcrest.Matchers.not;
import static org.hamcrest.Matchers.containsString;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.content;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

class AsyncBatchControllerTest {

    @Test
    void dispatchFailureReturnsStableSystemError() throws Exception {
        AsyncBatchHttpApplicationService service = mock(AsyncBatchHttpApplicationService.class);
        when(service.submit(eq(101L), any()))
                .thenThrow(new IllegalStateException("Unable to dispatch execution batch"));
        MockMvc mvc = MockMvcBuilders.standaloneSetup(new AsyncBatchController(service))
                .setControllerAdvice(new GlobalExceptionHandler())
                .build();

        mvc.perform(post("/api/v1/projects/101/test-batches")
                        .contentType("application/json")
                        .content("{\"testCases\":[]}"))
                .andExpect(status().isInternalServerError())
                .andExpect(jsonPath("$.success").value(false))
                .andExpect(jsonPath("$.code").value("S0001"))
                .andExpect(jsonPath("$.message").value("system error"))
                .andExpect(content().string(not(containsString("Unable to dispatch"))));
    }
}
