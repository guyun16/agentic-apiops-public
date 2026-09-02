package com.apiops.agent.real;

import com.apiops.agent.model.AgentModelClient;
import com.apiops.agent.model.springai.SpringAiAgentModelClient;
import org.junit.jupiter.api.Assumptions;
import org.springframework.ai.openai.OpenAiChatModel;
import org.springframework.ai.openai.OpenAiChatOptions;
import org.springframework.ai.openai.api.OpenAiApi;
import org.springframework.ai.openai.api.ResponseFormat;

final class DeepSeekRealTestSupport {

    static final String API_KEY_ENV = "DEEPSEEK_API_KEY";
    static final String BASE_URL = "https://api.deepseek.com";
    static final String MODEL = "deepseek-v4-flash";

    private DeepSeekRealTestSupport() {
    }

    static AgentModelClient client() {
        String apiKey = System.getenv(API_KEY_ENV);
        Assumptions.assumeTrue(apiKey != null && !apiKey.isBlank(),
                () -> "Set " + API_KEY_ENV + " for the real DeepSeek acceptance tests");
        var api = OpenAiApi.builder()
                .apiKey(apiKey)
                .baseUrl(BASE_URL)
                .build();
        var options = OpenAiChatOptions.builder()
                .model(MODEL)
                .responseFormat(new ResponseFormat(ResponseFormat.Type.JSON_OBJECT, null))
                .build();
        return new SpringAiAgentModelClient(OpenAiChatModel.builder()
                .openAiApi(api)
                .defaultOptions(options)
                .build());
    }
}
