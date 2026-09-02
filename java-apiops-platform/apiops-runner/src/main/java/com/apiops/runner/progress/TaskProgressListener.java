package com.apiops.runner.progress;

public interface TaskProgressListener {
    void progress(TaskProgressSnapshot snapshot);
    void terminal(TaskProgressSnapshot snapshot);

    static TaskProgressListener noop() {
        return new TaskProgressListener() {
            public void progress(TaskProgressSnapshot ignored) { }
            public void terminal(TaskProgressSnapshot ignored) { }
        };
    }
}
