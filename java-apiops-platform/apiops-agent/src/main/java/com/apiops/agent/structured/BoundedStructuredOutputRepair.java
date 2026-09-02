package com.apiops.agent.structured;

import com.apiops.agent.model.AgentModelClient;
import com.apiops.agent.model.AgentModelRequest;
import com.apiops.agent.model.ModelCallIdentity;

import java.util.List;
import java.util.Objects;
import java.util.function.Function;

/** One initial model call plus at most one constrained repair call. */
public final class BoundedStructuredOutputRepair<T> {

    public static final int REPAIR_MAX_ATTEMPTS = 1;

    private final AgentModelClient modelClient;
    private final StructuredCandidateMapper<T> mapper;

    public BoundedStructuredOutputRepair(
            AgentModelClient modelClient, StructuredCandidateMapper<T> mapper) {
        this.modelClient = Objects.requireNonNull(modelClient, "modelClient");
        this.mapper = Objects.requireNonNull(mapper, "mapper");
    }

    public T call(
            AgentModelRequest initialRequest,
            Function<T, T> businessValidator) {
        return callWithResult(initialRequest, businessValidator).candidate();
    }

    public Result<T> callWithResult(
            AgentModelRequest initialRequest,
            Function<T, T> businessValidator) {
        Objects.requireNonNull(initialRequest, "initialRequest");
        Objects.requireNonNull(businessValidator, "businessValidator");
        var initialResponse = modelClient.call(initialRequest);
        String candidate = initialResponse.content();
        ModelCallIdentity initialCall = new ModelCallIdentity(
                initialResponse.modelCallId(), null);
        try {
            return new Result<>(validate(candidate, businessValidator), List.of(initialCall));
        } catch (StructuredOutputException firstFailure) {
            AgentModelRequest repairRequest = new AgentModelRequest(
                    initialRequest.promptName(), initialRequest.promptVersion(),
                    initialRequest.system(), initialRequest.user()
                            + "\n\nRepair the previous candidate for these validation codes: "
                            + String.join(", ", firstFailure.errors())
                            + "\nPrevious candidate:\n" + candidate,
                    initialRequest.context());
            var repairResponse = modelClient.call(repairRequest);
            ModelCallIdentity repairCall = new ModelCallIdentity(
                    repairResponse.modelCallId(), initialResponse.modelCallId());
            return new Result<>(validate(
                    repairResponse.content(), businessValidator),
                    List.of(initialCall, repairCall));
        }
    }

    private T validate(String candidate, Function<T, T> businessValidator) {
        return businessValidator.apply(mapper.parse(candidate));
    }

    public record Result<T>(T candidate, List<ModelCallIdentity> modelCalls) {

        public Result {
            Objects.requireNonNull(candidate, "candidate");
            modelCalls = List.copyOf(modelCalls);
            if (modelCalls.isEmpty() || modelCalls.size() > 2) {
                throw new IllegalArgumentException("modelCalls must contain one or two calls");
            }
        }

        public int modelCallCount() {
            return modelCalls.size();
        }
    }
}
