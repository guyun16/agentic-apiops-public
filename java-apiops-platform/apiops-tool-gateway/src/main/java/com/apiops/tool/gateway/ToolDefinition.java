package com.apiops.tool.gateway;

import com.apiops.auth.enums.ProjectRole;

import java.math.BigDecimal;
import java.util.EnumSet;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.Objects;
import java.util.Set;

/** Stable model-facing tool contract; it contains no Java class or method identity. */
public record ToolDefinition(
        String name,
        String description,
        Set<String> requiredAuthorities,
        Set<ProjectRole> allowedProjectRoles,
        Map<String, Class<?>> argumentTypes,
        Map<String, ParameterContract> parameterContracts
) {

    public ToolDefinition(String name, String description) {
        this(name, description, Set.of(), allProjectRoles(), Map.of(), Map.of());
    }

    public ToolDefinition(
            String name,
            String description,
            Set<String> requiredAuthorities
    ) {
        this(name, description, requiredAuthorities, allProjectRoles(), Map.of(), Map.of());
    }

    public ToolDefinition(
            String name,
            String description,
            Map<String, Class<?>> argumentTypes
    ) {
        this(name, description, Set.of(), allProjectRoles(), argumentTypes,
                contractsFromTypes(argumentTypes));
    }

    public ToolDefinition(
            String name,
            String description,
            Set<String> requiredAuthorities,
            Set<ProjectRole> allowedProjectRoles
    ) {
        this(name, description, requiredAuthorities, allowedProjectRoles, Map.of(), Map.of());
    }

    /**
     * Keeps the existing five-argument contract source-compatible while allowing
     * richer parameter constraints to be attached when needed.
     */
    public ToolDefinition(
            String name,
            String description,
            Set<String> requiredAuthorities,
            Set<ProjectRole> allowedProjectRoles,
            Map<String, Class<?>> argumentTypes
    ) {
        this(name, description, requiredAuthorities, allowedProjectRoles, argumentTypes,
                contractsFromTypes(argumentTypes));
    }

    public static ToolDefinition withParameterContracts(
            String name,
            String description,
            Set<String> requiredAuthorities,
            Set<ProjectRole> allowedProjectRoles,
            Map<String, ParameterContract> parameterContracts
    ) {
        Objects.requireNonNull(parameterContracts, "parameterContracts must not be null");
        Map<String, Class<?>> argumentTypes = new LinkedHashMap<>();
        parameterContracts.forEach((argumentName, contract) -> {
            String normalizedName = requireText(argumentName, "argument name");
            argumentTypes.put(normalizedName,
                    Objects.requireNonNull(contract, "parameter contract must not be null").type());
        });
        return new ToolDefinition(
                name,
                description,
                requiredAuthorities,
                allowedProjectRoles,
                argumentTypes,
                parameterContracts
        );
    }

    public ToolDefinition {
        name = requireText(name, "name");
        description = requireText(description, "description");
        requiredAuthorities = normalizeAuthorities(requiredAuthorities);
        allowedProjectRoles = normalizeProjectRoles(allowedProjectRoles);
        argumentTypes = normalizeArgumentTypes(argumentTypes);
        parameterContracts = normalizeParameterContracts(argumentTypes, parameterContracts);
    }

    boolean isAllowedFor(ToolExecutionContext context, ProjectRole projectRole) {
        return allowedProjectRoles.contains(projectRole)
                && context.authorities().containsAll(requiredAuthorities);
    }

    private static Set<String> normalizeAuthorities(Set<String> values) {
        Objects.requireNonNull(values, "requiredAuthorities must not be null");
        return values.stream()
                .map(value -> requireText(value, "required authority"))
                .collect(java.util.stream.Collectors.toUnmodifiableSet());
    }

    private static Set<ProjectRole> normalizeProjectRoles(Set<ProjectRole> values) {
        Objects.requireNonNull(values, "allowedProjectRoles must not be null");
        if (values.isEmpty()) {
            throw new IllegalArgumentException("allowedProjectRoles must not be empty");
        }
        return Set.copyOf(values);
    }

    private static Map<String, Class<?>> normalizeArgumentTypes(
            Map<String, Class<?>> values
    ) {
        Objects.requireNonNull(values, "argumentTypes must not be null");
        Map<String, Class<?>> normalized = new LinkedHashMap<>();
        values.forEach((name, type) -> {
            normalized.put(requireText(name, "argument name"),
                    Objects.requireNonNull(type, "argument type must not be null"));
        });
        return Map.copyOf(normalized);
    }

    private static Map<String, ParameterContract> normalizeParameterContracts(
            Map<String, Class<?>> argumentTypes,
            Map<String, ParameterContract> values
    ) {
        Objects.requireNonNull(values, "parameterContracts must not be null");
        if (values.isEmpty()) {
            return contractsFromTypes(argumentTypes);
        }
        if (!values.keySet().equals(argumentTypes.keySet())) {
            throw new IllegalArgumentException(
                    "parameterContracts must define exactly the argument types");
        }

        Map<String, ParameterContract> normalized = new LinkedHashMap<>();
        values.forEach((name, contract) -> {
            String normalizedName = requireText(name, "argument name");
            ParameterContract normalizedContract = Objects.requireNonNull(
                    contract, "parameter contract must not be null");
            if (!argumentTypes.get(normalizedName).equals(normalizedContract.type())) {
                throw new IllegalArgumentException(
                        "parameter contract type must match argument type: " + normalizedName);
            }
            normalized.put(normalizedName, normalizedContract);
        });
        return Map.copyOf(normalized);
    }

    private static Map<String, ParameterContract> contractsFromTypes(
            Map<String, Class<?>> values
    ) {
        Map<String, Class<?>> normalizedTypes = normalizeArgumentTypes(values);
        Map<String, ParameterContract> contracts = new LinkedHashMap<>();
        normalizedTypes.forEach((name, type) -> contracts.put(name, ParameterContract.of(type)));
        return Map.copyOf(contracts);
    }

    private static Set<ProjectRole> allProjectRoles() {
        return Set.copyOf(EnumSet.allOf(ProjectRole.class));
    }

    private static String requireText(String value, String name) {
        Objects.requireNonNull(value, name + " must not be null");
        if (value.isBlank()) {
            throw new IllegalArgumentException(name + " must not be blank");
        }
        return value;
    }

    /** Contract for one model-supplied argument. */
    public record ParameterContract(
            Class<?> type,
            Set<?> allowedValues,
            Integer minLength,
            Integer maxLength,
            BigDecimal min,
            BigDecimal max,
            boolean required
    ) {

        /** Keeps existing required-parameter call sites source-compatible. */
        public ParameterContract(
                Class<?> type,
                Set<?> allowedValues,
                Integer minLength,
                Integer maxLength,
                BigDecimal min,
                BigDecimal max
        ) {
            this(type, allowedValues, minLength, maxLength, min, max, true);
        }

        public ParameterContract {
            type = Objects.requireNonNull(type, "parameter type must not be null");
            allowedValues = Set.copyOf(Objects.requireNonNull(
                    allowedValues, "allowedValues must not be null"));
            if (minLength != null && minLength < 0) {
                throw new IllegalArgumentException("minLength must not be negative");
            }
            if (maxLength != null && maxLength < 0) {
                throw new IllegalArgumentException("maxLength must not be negative");
            }
            if (minLength != null && maxLength != null && minLength > maxLength) {
                throw new IllegalArgumentException("minLength must not exceed maxLength");
            }
            if (min != null && max != null && min.compareTo(max) > 0) {
                throw new IllegalArgumentException("min must not exceed max");
            }
        }

        public static ParameterContract of(Class<?> type) {
            return new ParameterContract(type, Set.of(), null, null, null, null);
        }

        public static ParameterContract optionalOf(Class<?> type) {
            return new ParameterContract(type, Set.of(), null, null, null, null, false);
        }

        public static ParameterContract enumValues(Class<?> type, Set<?> allowedValues) {
            return new ParameterContract(type, allowedValues, null, null, null, null);
        }

        public static ParameterContract length(
                Class<?> type,
                Integer minLength,
                Integer maxLength
        ) {
            return new ParameterContract(type, Set.of(), minLength, maxLength, null, null);
        }

        public static ParameterContract range(Class<?> type, Number min, Number max) {
            return new ParameterContract(
                    type,
                    Set.of(),
                    null,
                    null,
                    decimal(min),
                    decimal(max)
            );
        }

        public static ParameterContract optionalRange(Class<?> type, Number min, Number max) {
            return new ParameterContract(
                    type,
                    Set.of(),
                    null,
                    null,
                    decimal(min),
                    decimal(max),
                    false
            );
        }

        private static BigDecimal decimal(Number value) {
            if (value == null) {
                return null;
            }
            if (value instanceof BigDecimal decimal) {
                return decimal;
            }
            try {
                return new BigDecimal(value.toString());
            } catch (NumberFormatException exception) {
                throw new IllegalArgumentException("range bound must be numeric", exception);
            }
        }
    }
}
