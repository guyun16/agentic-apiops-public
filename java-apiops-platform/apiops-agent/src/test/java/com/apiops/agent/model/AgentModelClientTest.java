package com.apiops.agent.model;

import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertEquals;

class AgentModelClientTest {

    @Test
    void deterministicFakeCanReplaceModelClient() {
        AgentModelClient client = new FakeAgentModelClient("{\"candidate\":true}");
        AgentModelRequest request = new AgentModelRequest(
                "generate-testcase", "v1", "fixed system",
                "fixed user", "fixed context");

        assertEquals(client.call(request), client.call(request));
        assertEquals("{\"candidate\":true}", client.call(request).content());
    }
}
