package com.apiops.tool.gateway;

/** Minimal audit vocabulary for the public safety pipeline. */
public enum AuditStatus {
    SUCCESS,
    DENIED,
    INVALID,
    SAFETY_VIOLATION,
    TIMEOUT,
    FAILED
}
