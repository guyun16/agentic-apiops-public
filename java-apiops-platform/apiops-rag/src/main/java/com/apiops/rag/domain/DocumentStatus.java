package com.apiops.rag.domain;

/** Minimal distinction between formal knowledge storage and derived index readiness. */
public enum DocumentStatus {
    STORED,
    INDEXED,
    INDEX_FAILED,
    DELETED
}
