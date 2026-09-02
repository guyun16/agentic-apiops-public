package com.apiops.rag.repository;

import com.apiops.rag.retrieval.RagQueryRecord;

import java.util.Optional;

/** Persistence boundary for minimal retrieval facts. */
public interface RagQueryRecordRepository {

    void save(RagQueryRecord record);

    Optional<RagQueryRecord> findById(long projectId, String ragQueryId);
}
