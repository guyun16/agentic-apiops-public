package com.apiops.demo.order.order;

import com.apiops.demo.order.order.application.CreateOrderApplicationService;
import com.apiops.demo.order.order.controller.BenchmarkOrderAuthFilter;
import com.apiops.demo.order.order.controller.BenchmarkOrderController;
import org.junit.jupiter.api.Test;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;
import org.springframework.mock.web.MockHttpServletRequest;
import org.springframework.mock.web.MockHttpServletResponse;
import org.springframework.mock.web.MockFilterChain;

import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.*;
import static org.junit.jupiter.api.Assertions.*;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.*;

class BenchmarkOrderContractTest {
    @Test
    void rejectsMissingAndWrongKeysBeforeBindingOrOrderMutation() throws Exception {
        var orders = mock(CreateOrderApplicationService.class);
        var mvc = MockMvcBuilders.standaloneSetup(new BenchmarkOrderController(orders))
                .addFilters(new BenchmarkOrderAuthFilter("test-only-key")).build();
        mvc.perform(post("/stage21/auth-check").contentType("application/json").content("{}"))
                .andExpect(status().isUnauthorized()).andExpect(jsonPath("$.code").value("AUTH_UNAUTHORIZED"));
        mvc.perform(post("/stage21/auth-check").header("Authorization", "wrong"))
                .andExpect(status().isUnauthorized());
        verifyNoInteractions(orders);
    }

    @Test
    void pathParametersAndEncodedPathsStillRequireAuthentication() throws Exception {
        var filter = new BenchmarkOrderAuthFilter("test-only-key");
        for (String path : new String[]{"/stage21/auth-check;test=1", "/stage21/%61uth-check"}) {
            var response = new MockHttpServletResponse();
            var chain = new MockFilterChain();
            filter.doFilter(new MockHttpServletRequest("POST", path), response, chain);
            assertEquals(401, response.getStatus());
            assertNull(chain.getRequest());
        }
    }

    @Test
    void authenticatedRequestUsesExistingOrderService() throws Exception {
        var orders = mock(CreateOrderApplicationService.class);
        var mvc = MockMvcBuilders.standaloneSetup(new BenchmarkOrderController(orders))
                .addFilters(new BenchmarkOrderAuthFilter("test-only-key")).build();
        mvc.perform(post("/stage21/auth-check").header("Authorization", "test-only-key")
                .contentType("application/json").content("{\"userId\":1,\"items\":[{\"productId\":1,\"quantity\":1}]}"))
                .andExpect(status().isOk()).andExpect(jsonPath("$.code").value("ORDER_SUCCESS"));
        verify(orders).createOrder(any());
    }

    @Test
    void publicOrdersBypassFilterAndEmptyConfigurationFailsClosed() throws Exception {
        var filter = new BenchmarkOrderAuthFilter("");
        var request = new MockHttpServletRequest("POST", "/orders");
        var chain = new MockFilterChain();
        filter.doFilter(request, new MockHttpServletResponse(), chain);
        assertSame(request, chain.getRequest());
        var denied = new MockHttpServletResponse();
        filter.doFilter(new MockHttpServletRequest("POST", "/stage21/auth-check"), denied, new MockFilterChain());
        assertEquals(401, denied.getStatus());
    }
}
