package com.apiops.tool.gateway;

import java.util.List;

/** Deliberately narrow Redis client: there is no raw-command or write entry point. */
public interface RedisReadClient {
    Object get(String key) throws Exception;
    Object hget(String key, String field) throws Exception;
    Object hmget(String key, List<String> fields) throws Exception;
    Object ttl(String key) throws Exception;
}
