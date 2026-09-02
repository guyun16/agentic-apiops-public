package com.apiops.tool.gateway;

import java.math.BigDecimal;
import java.util.Collection;
import java.util.Map;
import java.util.Objects;

/** Validates model arguments against the registered ToolDefinition contract. */
public final class ParamValidator {

    public Validation validate(ToolCallIntent intent, ToolDefinition definition) {
        if (intent == null || definition == null) {
            return Validation.invalidResult("tool intent and definition are required");
        }
        if (!definition.name().equals(intent.toolName())) {
            return Validation.invalidResult("tool name does not match its definition");
        }

        Map<String, Object> arguments = intent.arguments();
        Map<String, Class<?>> argumentTypes = definition.argumentTypes();
        for (Map.Entry<String, Class<?>> entry : argumentTypes.entrySet()) {
            ToolDefinition.ParameterContract contract =
                    definition.parameterContracts().get(entry.getKey());
            if (!arguments.containsKey(entry.getKey())) {
                if (contract != null && !contract.required()) {
                    continue;
                }
                return Validation.invalidResult("missing required argument: " + entry.getKey());
            }
            Object value = arguments.get(entry.getKey());
            if (value == null || !accepts(entry.getValue(), value)) {
                return Validation.invalidResult("invalid argument type: " + entry.getKey());
            }
            Validation constraintValidation = validateConstraints(
                    entry.getKey(),
                    value,
                    contract
            );
            if (!constraintValidation.valid()) {
                return constraintValidation;
            }
        }
        for (String argumentName : arguments.keySet()) {
            if (!argumentTypes.containsKey(argumentName)) {
                return Validation.invalidResult("unknown argument: " + argumentName);
            }
        }
        return Validation.validResult();
    }

    private static Validation validateConstraints(
            String argumentName,
            Object value,
            ToolDefinition.ParameterContract contract
    ) {
        if (contract == null) {
            return Validation.invalidResult("missing parameter contract: " + argumentName);
        }
        if (!contract.allowedValues().isEmpty() && !contract.allowedValues().contains(value)) {
            return Validation.invalidResult("argument is not an allowed value: " + argumentName);
        }

        if (contract.minLength() != null || contract.maxLength() != null) {
            Integer length = lengthOf(value);
            if (length == null) {
                return Validation.invalidResult(
                        "length constraint requires String or Collection: " + argumentName);
            }
            if (contract.minLength() != null && length < contract.minLength()) {
                return Validation.invalidResult("argument is shorter than allowed: " + argumentName);
            }
            if (contract.maxLength() != null && length > contract.maxLength()) {
                return Validation.invalidResult("argument is longer than allowed: " + argumentName);
            }
        }

        if (contract.min() != null || contract.max() != null) {
            if (!(value instanceof Number number)) {
                return Validation.invalidResult(
                        "range constraint requires Number: " + argumentName);
            }
            BigDecimal numericValue;
            try {
                numericValue = decimal(number);
            } catch (NumberFormatException exception) {
                return Validation.invalidResult("invalid numeric range value: " + argumentName);
            }
            if (contract.min() != null && numericValue.compareTo(contract.min()) < 0) {
                return Validation.invalidResult("argument is below allowed range: " + argumentName);
            }
            if (contract.max() != null && numericValue.compareTo(contract.max()) > 0) {
                return Validation.invalidResult("argument is above allowed range: " + argumentName);
            }
        }

        return Validation.validResult();
    }

    private static Integer lengthOf(Object value) {
        if (value instanceof String string) {
            return string.length();
        }
        if (value instanceof Collection<?> collection) {
            return collection.size();
        }
        return null;
    }

    private static BigDecimal decimal(Number value) {
        if (value instanceof BigDecimal decimal) {
            return decimal;
        }
        return new BigDecimal(value.toString());
    }

    private static boolean accepts(Class<?> expectedType, Object value) {
        if (!expectedType.isPrimitive()) {
            return expectedType.isInstance(value);
        }
        return switch (expectedType.getName()) {
            case "boolean" -> value instanceof Boolean;
            case "byte" -> value instanceof Byte;
            case "short" -> value instanceof Short;
            case "int" -> value instanceof Integer;
            case "long" -> value instanceof Long;
            case "float" -> value instanceof Float;
            case "double" -> value instanceof Double;
            case "char" -> value instanceof Character;
            default -> false;
        };
    }

    public record Validation(boolean valid, String reason) {

        public Validation {
            reason = Objects.requireNonNull(reason, "reason must not be null");
        }

        static Validation validResult() {
            return new Validation(true, "valid");
        }

        static Validation invalidResult(String reason) {
            return new Validation(false, reason);
        }
    }
}
