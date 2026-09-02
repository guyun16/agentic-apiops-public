package com.apiops.common.concurrency.design;

import java.util.concurrent.Executor;

public final class ContextAwareExecutor implements Executor {

    private final Executor delegate;

    public ContextAwareExecutor(Executor delegate) {
        this.delegate = delegate;
    }

    @Override
    public void execute(Runnable command) {
        TraceContextSnapshot captured = TraceContextHolder.get();

        delegate.execute(() -> {
            TraceContextSnapshot old = TraceContextHolder.get();

            try {
                if (captured != null) {
                    TraceContextHolder.set(captured);
                } else {
                    TraceContextHolder.clear();
                }

                command.run();
            } finally {
                if (old != null) {
                    TraceContextHolder.set(old);
                } else {
                    TraceContextHolder.clear();
                }
            }
        });
    }
}