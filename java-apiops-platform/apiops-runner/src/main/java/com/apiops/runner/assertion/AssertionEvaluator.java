package com.apiops.runner.assertion;

import com.apiops.runner.dsl.AssertionSpec;
import com.apiops.runner.dsl.AssertionType;

public interface AssertionEvaluator<S extends AssertionSpec> {

    AssertionType supportedType();

    AssertionResult evaluate(S assertion, AssertionContext context);
}
