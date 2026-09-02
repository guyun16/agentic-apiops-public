package com.apiops.agent.structured;

import com.apiops.agent.model.AgentModelClient;
import com.apiops.agent.model.AgentModelRequest;
import com.apiops.agent.model.AgentModelResponse;
import com.apiops.runner.dsl.TestCase;
import org.junit.jupiter.api.Test;

import java.util.ArrayDeque;
import java.util.List;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

class BoundedStructuredOutputRepairTest {

    private static final AgentModelRequest REQUEST = new AgentModelRequest(
            "generate-testcase", "v1", "immutable system",
            "generate candidate", "untrusted metadata");
    private final TestCaseCandidateMapper mapper = StructuredOutputTestSupport.mapper();
    private final TestCaseTargetValidator target = new TestCaseTargetValidator();

    @Test
    void firstInvalidRepairValidSucceedsWithExactlyTwoCalls() {
        SequenceClient client = new SequenceClient(List.of(
                "{malformed", StructuredOutputTestSupport.validCandidate()));

        var candidate = new BoundedStructuredOutputRepair<TestCase>(client, mapper).call(
                REQUEST, value -> target.validate(value, 42L, "api_create_order"));

        assertEquals("api_create_order", candidate.apiId());
        assertEquals(2, client.calls);
        assertEquals("immutable system", client.requests.getLast().system());
        assertEquals("untrusted metadata", client.requests.getLast().context());
        assertTrue(client.requests.getLast().user().contains("JSON_PARSE_ERROR"));
        var result = new BoundedStructuredOutputRepair<TestCase>(clientForIdentity(), mapper)
                .callWithResult(REQUEST, value -> target.validate(
                        value, 42L, "api_create_order"));
        assertEquals("provider-call-1", result.modelCalls().getFirst().modelCallId());
        assertEquals("provider-call-2", result.modelCalls().getLast().modelCallId());
        assertEquals("provider-call-1", result.modelCalls().getLast().repairOfModelCallId());
    }

    private SequenceClient clientForIdentity() {
        return new SequenceClient(List.of(
                "{malformed", StructuredOutputTestSupport.validCandidate()));
    }

    @Test
    void repairStillInvalidFailsAndNeverMakesThirdCall() {
        SequenceClient client = new SequenceClient(List.of("{bad", "{still-bad"));

        StructuredOutputException exception = assertThrows(
                StructuredOutputException.class,
                () -> new BoundedStructuredOutputRepair<TestCase>(client, mapper).call(
                        REQUEST, value -> target.validate(
                                value, 42L, "api_create_order")));

        assertEquals(StructuredOutputFailureType.JSON_PARSE, exception.failureType());
        assertEquals(2, client.calls);
        assertEquals(1, BoundedStructuredOutputRepair.REPAIR_MAX_ATTEMPTS);
    }

    @Test
    void validCandidateUsesOneCallAndWrongTargetCannotBeAccepted() {
        SequenceClient valid = new SequenceClient(List.of(
                StructuredOutputTestSupport.validCandidate()));
        new BoundedStructuredOutputRepair<TestCase>(valid, mapper).call(
                REQUEST, value -> target.validate(value, 42L, "api_create_order"));
        assertEquals(1, valid.calls);

        String wrongTarget = StructuredOutputTestSupport.validCandidate()
                .replace("api_create_order", "api_other");
        SequenceClient mismatch = new SequenceClient(List.of(wrongTarget, wrongTarget));
        assertThrows(StructuredOutputException.class,
                () -> new BoundedStructuredOutputRepair<TestCase>(mismatch, mapper).call(
                        REQUEST, value -> target.validate(
                                value, 42L, "api_create_order")));
        assertEquals(2, mismatch.calls);
    }

    private static final class SequenceClient implements AgentModelClient {
        private final ArrayDeque<String> responses;
        private final java.util.ArrayList<AgentModelRequest> requests = new java.util.ArrayList<>();
        private int calls;

        private SequenceClient(List<String> responses) {
            this.responses = new ArrayDeque<>(responses);
        }

        @Override
        public AgentModelResponse call(AgentModelRequest request) {
            calls++;
            requests.add(request);
            return new AgentModelResponse(
                    "provider-call-" + calls, responses.removeFirst());
        }
    }
}
