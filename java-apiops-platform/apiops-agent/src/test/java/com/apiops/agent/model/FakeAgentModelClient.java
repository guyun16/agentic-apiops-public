package com.apiops.agent.model;

final class FakeAgentModelClient implements AgentModelClient {

    private final AgentModelResponse response;

    FakeAgentModelClient(String content) {
        this.response = new AgentModelResponse("fake-model-call-1", content);
    }

    @Override
    public AgentModelResponse call(AgentModelRequest request) {
        return response;
    }
}
