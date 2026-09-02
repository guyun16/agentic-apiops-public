package com.apiops.runner.assertion;

import com.apiops.runner.dsl.AssertionSpec;
import com.apiops.runner.dsl.AssertionType;

import java.util.EnumMap;
import java.util.List;
import java.util.Map;
import java.util.Objects;

public final class AssertionEvaluatorRegistry {

    private final Map<AssertionType, AssertionEvaluator<? extends AssertionSpec>> evaluators;

    @SafeVarargs
    public AssertionEvaluatorRegistry(
            AssertionEvaluator<? extends AssertionSpec>... evaluators) {
        this(List.of(evaluators));
    }

    public AssertionEvaluatorRegistry(
            List<? extends AssertionEvaluator<? extends AssertionSpec>> evaluators) {
        Objects.requireNonNull(evaluators, "evaluators must not be null");
        EnumMap<AssertionType, AssertionEvaluator<? extends AssertionSpec>> registered =
                new EnumMap<>(AssertionType.class);
        for (AssertionEvaluator<? extends AssertionSpec> evaluator : evaluators) {
            Objects.requireNonNull(evaluator, "evaluator must not be null");
            AssertionType type = Objects.requireNonNull(
                    evaluator.supportedType(), "evaluator type must not be null");
            if (registered.putIfAbsent(type, evaluator) != null) {
                throw new AssertionEvaluatorRegistryException(
                        "Duplicate evaluator for assertion type: " + type);
            }
        }
        this.evaluators = Map.copyOf(registered);
    }

    @SuppressWarnings("unchecked")
    public <S extends AssertionSpec> AssertionEvaluator<S> lookup(AssertionType type) {
        Objects.requireNonNull(type, "type must not be null");
        AssertionEvaluator<? extends AssertionSpec> evaluator = evaluators.get(type);
        if (evaluator == null) {
            throw new AssertionEvaluatorRegistryException(
                    "No evaluator registered for assertion type: " + type);
        }
        return (AssertionEvaluator<S>) evaluator;
    }
}
