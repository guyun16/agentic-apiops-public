package com.apiops.runner.dsl;

import com.fasterxml.jackson.annotation.JsonIgnore;
import com.fasterxml.jackson.annotation.JsonSubTypes;
import com.fasterxml.jackson.annotation.JsonTypeInfo;

@JsonTypeInfo(
        use = JsonTypeInfo.Id.NAME,
        include = JsonTypeInfo.As.PROPERTY,
        property = "type"
)
@JsonSubTypes({
        @JsonSubTypes.Type(value = StatusCodeAssertionSpec.class, name = "STATUS_CODE"),
        @JsonSubTypes.Type(value = HeaderAssertionSpec.class, name = "HEADER"),
        @JsonSubTypes.Type(value = JsonPathAssertionSpec.class, name = "JSON_PATH"),
        @JsonSubTypes.Type(value = ResponseTimeAssertionSpec.class, name = "RESPONSE_TIME")
})
public sealed interface AssertionSpec
        permits StatusCodeAssertionSpec, HeaderAssertionSpec,
        JsonPathAssertionSpec, ResponseTimeAssertionSpec {

    @JsonIgnore
    AssertionType type();
}
