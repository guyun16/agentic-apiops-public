package com.apiops.web.runner.config;

import com.apiops.auth.application.ProjectAuthorizationService;
import com.apiops.runner.persistence.ExecutionFactRepository;
import com.apiops.runner.progress.TaskProgressQueryService;
import com.apiops.runner.progress.TaskProgressStore;
import com.apiops.web.runner.progress.RedisTaskProgressStore;
import com.apiops.web.runner.progress.SseEmitterRegistry;
import com.apiops.web.runner.progress.TaskProgressProperties;
import com.apiops.web.runner.progress.TaskProgressSseApplicationService;
import com.apiops.web.runner.progress.TaskProgressSseController;
import com.apiops.web.runner.progress.TaskProgressSseService;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.data.redis.core.StringRedisTemplate;

@Configuration(proxyBeanMethods=false)
@EnableConfigurationProperties(TaskProgressProperties.class)
@ConditionalOnProperty(prefix="apiops.runner.progress",name="enabled",havingValue="true")
public class TaskProgressConfiguration {
    @Bean TaskProgressStore taskProgressStore(StringRedisTemplate redis,TaskProgressProperties p){return new RedisTaskProgressStore(redis,p.getTtl());}
    @Bean TaskProgressQueryService taskProgressQueryService(TaskProgressStore s,ExecutionFactRepository r){return new TaskProgressQueryService(s,r);}
    @Bean SseEmitterRegistry sseEmitterRegistry(){return new SseEmitterRegistry();}
    @Bean TaskProgressSseService taskProgressSseService(TaskProgressQueryService q,SseEmitterRegistry r,TaskProgressProperties p){return new TaskProgressSseService(q,r,p.getSseTimeout().toMillis());}
    @Bean TaskProgressSseApplicationService taskProgressSseApplicationService(ProjectAuthorizationService a,TaskProgressSseService s){return new TaskProgressSseApplicationService(a,s);}
    @Bean TaskProgressSseController taskProgressSseController(TaskProgressSseApplicationService s){return new TaskProgressSseController(s);}
}
