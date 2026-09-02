package com.apiops.demo.order.validation;

import com.apiops.demo.order.order.dto.CreateOrderItemRequest;
import com.apiops.demo.order.order.dto.CreateOrderRequest;
import com.apiops.demo.order.product.dto.CreateProductRequest;
import com.apiops.demo.order.user.dto.CreateUserRequest;
import jakarta.validation.ConstraintViolation;
import jakarta.validation.Validation;
import jakarta.validation.Validator;
import jakarta.validation.ValidatorFactory;
import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.Test;

import java.math.BigDecimal;
import java.util.List;
import java.util.Set;

import static org.assertj.core.api.Assertions.assertThat;

class RequestDtoValidationTest {

    private static ValidatorFactory validatorFactory;
    private static Validator validator;

    @BeforeAll
    static void setUpValidator() {
        validatorFactory = Validation.buildDefaultValidatorFactory();
        validator = validatorFactory.getValidator();
    }

    @AfterAll
    static void closeValidatorFactory() {
        validatorFactory.close();
    }

    @Test
    void validRequestDtosHaveNoConstraintViolations() {
        assertThat(validator.validate(validUserRequest())).isEmpty();
        assertThat(validator.validate(validProductRequest())).isEmpty();
        assertThat(validator.validate(validOrderRequest())).isEmpty();
    }

    @Test
    void blankUserFieldsFailValidation() {
        CreateUserRequest request = validUserRequest();
        request.setUserNo(" ");
        assertThat(violatedProperties(request)).contains("userNo");

        request = validUserRequest();
        request.setUserName(" ");
        assertThat(violatedProperties(request)).contains("userName");
    }

    @Test
    void invalidProductPricesFailValidation() {
        CreateProductRequest request = validProductRequest();

        request.setPrice(null);
        assertThat(violatedProperties(request)).contains("price");

        request.setPrice(BigDecimal.ZERO);
        assertThat(violatedProperties(request)).contains("price");

        request.setPrice(new BigDecimal("1.001"));
        assertThat(violatedProperties(request)).contains("price");
    }

    @Test
    void missingOrderUserIdFailsValidation() {
        CreateOrderRequest request = validOrderRequest();
        request.setUserId(null);

        assertThat(violatedProperties(request)).contains("userId");
    }

    @Test
    void emptyOrderItemsFailValidation() {
        CreateOrderRequest request = validOrderRequest();
        request.setItems(List.of());

        assertThat(violatedProperties(request)).contains("items");
    }

    @Test
    void invalidNestedItemQuantityFailsValidation() {
        CreateOrderRequest request = validOrderRequest();
        request.getItems().getFirst().setQuantity(0);

        assertThat(violatedProperties(request)).contains("items[0].quantity");
    }

    @Test
    void couponIdIsOptionalButMustBePositiveWhenPresent() {
        CreateOrderRequest request = validOrderRequest();
        request.setCouponId(null);
        assertThat(validator.validate(request)).isEmpty();

        request.setCouponId(0L);
        assertThat(violatedProperties(request)).contains("couponId");
    }

    private static CreateUserRequest validUserRequest() {
        CreateUserRequest request = new CreateUserRequest();
        request.setUserNo("apiops-user-no");
        request.setUserName("apiops-user");
        return request;
    }

    private static CreateProductRequest validProductRequest() {
        CreateProductRequest request = new CreateProductRequest();
        request.setProductNo("SKU-001");
        request.setProductName("API product");
        request.setPrice(new BigDecimal("19.99"));
        return request;
    }

    private static CreateOrderRequest validOrderRequest() {
        CreateOrderItemRequest item = new CreateOrderItemRequest();
        item.setProductId(1L);
        item.setQuantity(2);

        CreateOrderRequest request = new CreateOrderRequest();
        request.setUserId(1L);
        request.setItems(List.of(item));
        return request;
    }

    private static Set<String> violatedProperties(Object request) {
        return validator.validate(request).stream()
                .map(ConstraintViolation::getPropertyPath)
                .map(Object::toString)
                .collect(java.util.stream.Collectors.toSet());
    }
}
