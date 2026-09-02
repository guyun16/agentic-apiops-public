package com.apiops.tool.gateway;

import java.time.Instant;
import java.util.List;

/** Server-owned logical log source; callers cannot supply filesystem paths. */
@FunctionalInterface
public interface LogSource {
    List<String> search(String logicalService, String query, Instant from, Instant to,
                        int maxLines) throws Exception;
}
