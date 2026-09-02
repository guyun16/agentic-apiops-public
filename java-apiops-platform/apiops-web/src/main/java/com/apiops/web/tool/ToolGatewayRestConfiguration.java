package com.apiops.web.tool;

import com.apiops.rag.retrieval.RagRetriever;
import com.apiops.tool.gateway.RagSearchTool;
import com.apiops.tool.gateway.RedisGuard;
import com.apiops.tool.gateway.RedisReadClient;
import com.apiops.tool.gateway.RedisReadExecutor;
import com.apiops.tool.gateway.ResourceGuard;
import com.apiops.tool.gateway.ToolGateway;
import com.apiops.tool.gateway.ToolGateway.ToolHandler;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.boot.autoconfigure.condition.ConditionalOnMissingBean;
import org.springframework.boot.convert.DurationStyle;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.core.env.Environment;

import java.time.Duration;
import java.util.LinkedHashMap;
import java.util.Map;

/** Wires existing Stage 12 handlers behind one authenticated Gateway REST boundary. */
@Configuration(proxyBeanMethods = false)
public class ToolGatewayRestConfiguration {

    @Bean
    @ConditionalOnMissingBean(ResourceGuard.class)
    public ResourceGuard toolResourceGuard() {
        return new RedisGuard();
    }

    @Bean
    public RedisReadClient toolRedisReadClient(Environment environment) {
        return new com.apiops.tool.gateway.SocketRedisReadClient(
                environment.getProperty("spring.data.redis.host", "localhost"),
                Integer.parseInt(environment.getProperty("spring.data.redis.port", "6379")),
                environment.getProperty("spring.data.redis.password", ""),
                redisTimeout(environment));
    }

    @Bean
    public RedisReadExecutor toolRedisReadExecutor(
            RedisReadClient client,
            ResourceGuard resourceGuard
    ) {
        RedisGuard redisGuard = resourceGuard instanceof RedisGuard guard
                ? guard
                : new RedisGuard();
        return new RedisReadExecutor(redisGuard, client);
    }

    @Bean
    public ToolGatewayRestApplicationService toolGatewayRestApplicationService(
            ToolGateway gateway,
            RedisReadExecutor redisReadExecutor,
            ObjectProvider<RagRetriever> retrieverProvider
    ) {
        Map<String, ToolHandler> handlers = new LinkedHashMap<>();
        handlers.put(RedisGuard.TOOL_NAME, redisReadExecutor::execute);
        RagRetriever retriever = retrieverProvider.getIfAvailable();
        if (retriever != null) {
            handlers.put(RagSearchTool.TOOL_NAME, RagSearchTool.handler(retriever));
        }
        return new ToolGatewayRestApplicationService(gateway, handlers);
    }

    private static Duration redisTimeout(Environment environment) {
        return DurationStyle.detectAndParse(
                environment.getProperty("spring.data.redis.timeout", "2s"));
    }
}
