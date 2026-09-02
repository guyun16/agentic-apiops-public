package com.apiops.runner.application;

import java.util.concurrent.ArrayBlockingQueue;
import java.util.concurrent.ThreadFactory;
import java.util.concurrent.ThreadPoolExecutor;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;

/** Creates the explicitly bounded executor used only for TestCase execution. */
public final class RunnerExecutorFactory {

    private RunnerExecutorFactory() {
    }

    public static ThreadPoolExecutor create(RunnerExecutorProperties properties) {
        AtomicInteger sequence = new AtomicInteger();
        ThreadFactory threadFactory = task -> {
            Thread thread = new Thread(
                    task,
                    properties.threadNamePrefix() + sequence.incrementAndGet());
            thread.setDaemon(false);
            return thread;
        };
        return new ThreadPoolExecutor(
                properties.corePoolSize(),
                properties.maximumPoolSize(),
                properties.keepAliveTime().toMillis(),
                TimeUnit.MILLISECONDS,
                new ArrayBlockingQueue<>(properties.queueCapacity()),
                threadFactory,
                new ThreadPoolExecutor.AbortPolicy());
    }
}
