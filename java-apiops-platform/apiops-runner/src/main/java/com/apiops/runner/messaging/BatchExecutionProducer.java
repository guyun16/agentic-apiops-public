package com.apiops.runner.messaging;

/** Publishes an already-prepared execution identity. */
public interface BatchExecutionProducer {

    void publish(BatchExecutionMessage message);
}
