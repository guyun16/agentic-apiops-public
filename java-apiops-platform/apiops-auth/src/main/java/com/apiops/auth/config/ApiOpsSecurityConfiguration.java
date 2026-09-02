package com.apiops.auth.config;

import com.apiops.auth.controller.AuthController;
import com.apiops.auth.application.AuthenticationService;
import com.apiops.auth.application.ProjectAuthorizationService;
import com.apiops.auth.jwt.JwtTokenService;
import com.apiops.auth.repository.AuthUserRepository;
import com.apiops.auth.repository.EmptyAuthUserRepository;
import com.apiops.auth.repository.EmptyGlobalRbacRepository;
import com.apiops.auth.repository.GlobalRbacRepository;
import com.apiops.auth.repository.InMemoryAuthUserRepository;
import com.apiops.auth.repository.JdbcAuthUserRepository;
import com.apiops.auth.repository.JdbcGlobalRbacRepository;
import com.apiops.auth.repository.EmptyProjectMembershipRepository;
import com.apiops.auth.repository.JdbcProjectMembershipRepository;
import com.apiops.auth.repository.ProjectMembershipRepository;
import com.apiops.auth.security.ApiOpsUserDetailsService;
import com.apiops.auth.web.JwtAuthenticationFilter;
import com.apiops.auth.web.RestAccessDeniedHandler;
import com.apiops.auth.web.RestAuthenticationEntryPoint;
import org.springframework.boot.autoconfigure.condition.ConditionalOnMissingBean;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.context.annotation.Import;
import org.springframework.core.env.Environment;
import org.springframework.core.env.Profiles;
import org.springframework.http.HttpMethod;
import org.springframework.security.authentication.AuthenticationManager;
import org.springframework.security.authentication.ProviderManager;
import org.springframework.security.authentication.dao.DaoAuthenticationProvider;
import org.springframework.security.config.annotation.web.builders.HttpSecurity;
import org.springframework.security.config.annotation.method.configuration.EnableMethodSecurity;
import org.springframework.security.config.annotation.web.configurers.AbstractHttpConfigurer;
import org.springframework.security.config.http.SessionCreationPolicy;
import org.springframework.security.crypto.bcrypt.BCryptPasswordEncoder;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.security.core.userdetails.UserDetailsService;
import org.springframework.security.web.access.intercept.AuthorizationFilter;
import org.springframework.security.web.SecurityFilterChain;

import javax.sql.DataSource;

/**
 * Stateless username/password authentication baseline. Token issuance and
 * authorization remain outside this stage.
 */
@Configuration(proxyBeanMethods = false)
@EnableMethodSecurity
@Import({AuthController.class, AuthenticationService.class, JwtConfiguration.class})
public class ApiOpsSecurityConfiguration {

    @Bean
    public SecurityFilterChain apiOpsSecurityFilterChain(
            HttpSecurity http,
            JwtTokenService jwtTokenService,
            UserDetailsService userDetailsService,
            GlobalRbacRepository globalRbacRepository,
            RestAuthenticationEntryPoint authenticationEntryPoint,
            RestAccessDeniedHandler accessDeniedHandler
    ) throws Exception {
        JwtAuthenticationFilter jwtAuthenticationFilter = new JwtAuthenticationFilter(
                jwtTokenService,
                userDetailsService,
                globalRbacRepository,
                authenticationEntryPoint
        );
        http
                .csrf(AbstractHttpConfigurer::disable)
                .formLogin(AbstractHttpConfigurer::disable)
                .httpBasic(AbstractHttpConfigurer::disable)
                .sessionManagement(session -> session
                        .sessionCreationPolicy(SessionCreationPolicy.STATELESS))
                .exceptionHandling(exceptionHandling -> exceptionHandling
                        .authenticationEntryPoint(authenticationEntryPoint)
                        .accessDeniedHandler(accessDeniedHandler))
                .addFilterBefore(jwtAuthenticationFilter, AuthorizationFilter.class)
                .authorizeHttpRequests(authorize -> authorize
                        .requestMatchers(HttpMethod.POST, "/api/v1/auth/login").permitAll()
                        .requestMatchers(HttpMethod.GET, "/actuator/health").permitAll()
                        .requestMatchers(HttpMethod.GET, "/actuator/prometheus").permitAll()
                        .anyRequest().authenticated());

        return http.build();
    }

    @Bean
    public RestAuthenticationEntryPoint restAuthenticationEntryPoint() {
        return new RestAuthenticationEntryPoint();
    }

    @Bean
    public RestAccessDeniedHandler restAccessDeniedHandler() {
        return new RestAccessDeniedHandler();
    }

    @Bean
    public PasswordEncoder passwordEncoder() {
        return new BCryptPasswordEncoder();
    }

    @Bean
    public AuthUserRepository authUserRepository(
            @Qualifier("authDataSource")
            ObjectProvider<DataSource> dataSourceProvider,
            Environment environment
    ) {
        DataSource dataSource = dataSourceProvider.getIfAvailable();
        if (dataSource != null) {
            return new JdbcAuthUserRepository(dataSource);
        }
        if (environment.acceptsProfiles(Profiles.of("test"))) {
            return InMemoryAuthUserRepository.demoUser();
        }
        return new EmptyAuthUserRepository();
    }

    @Bean
    public GlobalRbacRepository globalRbacRepository(
            @Qualifier("authDataSource")
            ObjectProvider<DataSource> dataSourceProvider
    ) {
        DataSource dataSource = dataSourceProvider.getIfAvailable();
        return dataSource == null
                ? new EmptyGlobalRbacRepository()
                : new JdbcGlobalRbacRepository(dataSource);
    }

    @Bean
    public ProjectMembershipRepository projectMembershipRepository(
            @Qualifier("authDataSource")
            ObjectProvider<DataSource> dataSourceProvider
    ) {
        DataSource dataSource = dataSourceProvider.getIfAvailable();
        return dataSource == null
                ? new EmptyProjectMembershipRepository()
                : new JdbcProjectMembershipRepository(dataSource);
    }

    @Bean
    public ProjectAuthorizationService projectAuthorizationService(
            ProjectMembershipRepository membershipRepository
    ) {
        return new ProjectAuthorizationService(membershipRepository);
    }

    /**
     * Keeps the application context explicit without enabling Boot's generated
     * development user. Password verification remains in Spring Security's
     * authentication provider.
     */
    @Bean
    @ConditionalOnMissingBean(UserDetailsService.class)
    public ApiOpsUserDetailsService apiOpsUserDetailsService(
            AuthUserRepository authUserRepository
    ) {
        return new ApiOpsUserDetailsService(authUserRepository);
    }

    @Bean
    public AuthenticationManager authenticationManager(
            UserDetailsService userDetailsService,
            PasswordEncoder passwordEncoder
    ) {
        DaoAuthenticationProvider provider = new DaoAuthenticationProvider(userDetailsService);
        provider.setPasswordEncoder(passwordEncoder);
        return new ProviderManager(provider);
    }
}
