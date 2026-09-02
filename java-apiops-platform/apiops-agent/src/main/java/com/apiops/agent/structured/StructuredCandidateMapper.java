package com.apiops.agent.structured;

/** Parses one model candidate into a contract-owned Java value. */
@FunctionalInterface
public interface StructuredCandidateMapper<T> {

    T parse(String candidate);
}
