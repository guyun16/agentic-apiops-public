package com.apiops.common.concurrency.design;

public final class
TraceContextHolder {

    private static final ThreadLocal<TraceContextSnapshot> LOCAL = new ThreadLocal<>();

    private TraceContextHolder() {
    }

    public static void set(TraceContextSnapshot snapshot) {
        LOCAL.set(snapshot);
    }

    public static TraceContextSnapshot get() {
        return LOCAL.get();
    }

    public static void clear() {
        LOCAL.remove();
    }
}