package com.apiops.runner.assertion;

import com.apiops.runner.dsl.AssertionSpec;

import java.util.ArrayList;
import java.util.List;
import java.util.Objects;

public final class AssertionEngine {

    private final AssertionEvaluatorRegistry registry;

    public AssertionEngine(AssertionEvaluatorRegistry registry) {
        this.registry = Objects.requireNonNull(registry, "registry must not be null");
    }

    public List<AssertionResult> evaluate(
            List<? extends AssertionSpec> assertions,
            AssertionContext context) {
        Objects.requireNonNull(assertions, "assertions must not be null");
        Objects.requireNonNull(context, "context must not be null");

        List<AssertionResult> results = new ArrayList<>(assertions.size());
        for (AssertionSpec assertion : assertions) {
            Objects.requireNonNull(assertion, "assertion must not be null");
            AssertionEvaluator<AssertionSpec> evaluator = registry.lookup(assertion.type());
            results.add(evaluator.evaluate(assertion, context));
        }
        return List.copyOf(results);
    }
}
