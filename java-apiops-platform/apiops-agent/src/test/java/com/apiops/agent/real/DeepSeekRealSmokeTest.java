package com.apiops.agent.real;

import com.apiops.agent.model.AgentModelRequest;
import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertFalse;

class DeepSeekRealSmokeTest {

    @Test
    void springAiAgentModelClientReturnsNonEmptyRealDeepSeekContent() {
        var response = DeepSeekRealTestSupport.client().call(new AgentModelRequest(
                "deepseek-smoke",
                "v1",
                "Return only a JSON object.",
                "Return a small JSON object with an ok boolean set to true.",
                "{}"));

        assertFalse(response.content().isBlank());
        assertFalse(response.modelCallId().isBlank());
        System.out.println("REAL_DEEPSEEK_SMOKE success=true provider=DeepSeek"
                + " adapter=SpringAiAgentModelClient model=" + DeepSeekRealTestSupport.MODEL
                + " modelCallId=" + response.modelCallId()
                + " contentNonEmpty=true");
    }
}
