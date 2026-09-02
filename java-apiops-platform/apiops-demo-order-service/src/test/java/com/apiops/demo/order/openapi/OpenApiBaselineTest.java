package com.apiops.demo.order.openapi;

import com.apiops.demo.order.common.web.ApiResponse;
import com.apiops.demo.order.coupon.mapper.CouponMapper;
import com.apiops.demo.order.coupon.mapper.UserCouponMapper;
import com.apiops.demo.order.fault.SlowSqlMapper;
import com.apiops.demo.order.inventory.mapper.InventoryMapper;
import com.apiops.demo.order.order.mapper.OrderItemMapper;
import com.apiops.demo.order.order.mapper.OrderMapper;
import com.apiops.demo.order.payment.mapper.PaymentCallbackMapper;
import com.apiops.demo.order.payment.mapper.PaymentMapper;
import com.apiops.demo.order.product.mapper.ProductMapper;
import com.apiops.demo.order.user.mapper.UserMapper;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.http.MediaType;
import org.springframework.test.context.ActiveProfiles;
import org.springframework.test.context.TestPropertySource;
import org.springframework.test.context.bean.override.mockito.MockitoBean;
import org.springframework.test.web.servlet.MockMvc;

import java.util.ArrayList;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Set;

import static org.assertj.core.api.Assertions.assertThat;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

@SpringBootTest
@AutoConfigureMockMvc
@ActiveProfiles("test")
@TestPropertySource(properties = "spring.datasource.url=jdbc:test")
class OpenApiBaselineTest {

    private static final String API_TITLE = "Agentic APIOps Demo Order Service API";
    private static final String OPENAPI_VERSION = "3.0.1";
    private static final String API_VERSION = "0.1.0";
    private static final List<String> CORE_TAGS = List.of(
            "Orders", "Products", "Inventory", "Payments", "Coupons", "Users", "Faults");

    private static final Set<String> HTTP_METHODS = Set.of(
            "get", "put", "post", "delete", "options", "head", "patch", "trace");

    private static final List<ExpectedOperation> EXPECTED_OPERATIONS = List.of(
            operation("/orders", "post", "createOrder", "Orders", "200", "OrderDetailResponse",
                    "createdOrder", "CreateOrderRequest", "createOrderRequest",
                    error("400", "invalidParameter", "ORDER_PARAM_INVALID"),
                    error("404", "missingUser", "ORDER_RESOURCE_NOT_FOUND"),
                    error("409", "insufficientInventory", "ORDER_BUSINESS_CONFLICT"),
                    error("500", "systemError", "ORDER_SYSTEM_ERROR")),
            operation("/orders/{orderId}", "get", "getOrderDetail", "Orders", "200", "OrderDetailResponse",
                    "orderDetails", null, null,
                    error("400", "invalidOrderId", "ORDER_PARAM_INVALID"),
                    error("404", "missingOrder", "ORDER_RESOURCE_NOT_FOUND"),
                    error("500", "systemError", "ORDER_SYSTEM_ERROR")),
            operation("/orders/{orderId}/cancel", "post", "cancelOrder", "Orders", "200", "OrderDetailResponse",
                    "cancelledOrder", null, null,
                    error("400", "invalidOrderId", "ORDER_PARAM_INVALID"),
                    error("404", "missingOrder", "ORDER_RESOURCE_NOT_FOUND"),
                    error("409", "orderStatusConflict", "ORDER_BUSINESS_CONFLICT"),
                    error("500", "systemError", "ORDER_SYSTEM_ERROR")),
            operation("/products", "post", "createProduct", "Products", "200", "ProductResponse",
                    "createdProduct", "CreateProductRequest", "createProductRequest",
                    error("400", "invalidParameter", "ORDER_PARAM_INVALID"),
                    error("409", "duplicateProductNumber", "ORDER_BUSINESS_CONFLICT"),
                    error("500", "systemError", "ORDER_SYSTEM_ERROR")),
            operation("/products/{id}", "get", "getProduct", "Products", "200", "ProductResponse",
                    "product", null, null,
                    error("404", "missingProduct", "ORDER_RESOURCE_NOT_FOUND"),
                    error("500", "systemError", "ORDER_SYSTEM_ERROR")),
            operation("/products", "get", "listProducts", "Products", "200", "ProductPageResponse",
                    "productPage", null, null,
                    error("400", "invalidPage", "ORDER_PARAM_INVALID"),
                    error("500", "systemError", "ORDER_SYSTEM_ERROR")),
            operation("/products/{id}/off-shelf", "put", "offShelfProduct", "Products", "200", "ProductResponse",
                    "offShelfProduct", null, null,
                    error("404", "missingProduct", "ORDER_RESOURCE_NOT_FOUND"),
                    error("409", "productStatusConflict", "ORDER_BUSINESS_CONFLICT"),
                    error("500", "systemError", "ORDER_SYSTEM_ERROR")),
            operation("/coupons/{couponId}", "get", "getCoupon", "Coupons", "200", "CouponResponse",
                    "couponTemplate", null, null,
                    error("400", "invalidParameter", "ORDER_PARAM_INVALID"),
                    error("404", "missingCoupon", "ORDER_RESOURCE_NOT_FOUND"),
                    error("500", "systemError", "ORDER_SYSTEM_ERROR")),
            operation("/users/{userId}/coupons/{couponId}", "post", "claimCoupon", "Coupons", "200", "UserCouponResponse",
                    "claimedCoupon", null, null,
                    error("400", "invalidParameter", "ORDER_PARAM_INVALID"),
                    error("404", "missingUser", "ORDER_RESOURCE_NOT_FOUND"),
                    error("409", "duplicateClaim", "ORDER_BUSINESS_CONFLICT"),
                    error("500", "systemError", "ORDER_SYSTEM_ERROR")),
            operation("/users/{userId}/coupons", "get", "listUserCoupons", "Coupons", "200", "UserCouponListResponse",
                    "userCoupons", null, null,
                    error("400", "invalidStatus", "ORDER_PARAM_INVALID"),
                    error("404", "missingUser", "ORDER_RESOURCE_NOT_FOUND"),
                    error("500", "systemError", "ORDER_SYSTEM_ERROR")),
            operation("/users", "post", "createUser", "Users", "200", "UserResponse",
                    "createdUser", "CreateUserRequest", "createUserRequest",
                    error("400", "invalidParameter", "ORDER_PARAM_INVALID"),
                    error("409", "duplicateUserNumber", "ORDER_BUSINESS_CONFLICT"),
                    error("500", "systemError", "ORDER_SYSTEM_ERROR")),
            operation("/users/{id}", "get", "getUser", "Users", "200", "UserResponse",
                    "user", null, null,
                    error("404", "missingUser", "ORDER_RESOURCE_NOT_FOUND"),
                    error("500", "systemError", "ORDER_SYSTEM_ERROR")),
            operation("/users/{id}/disable", "put", "disableUser", "Users", "200", "UserResponse",
                    "disabledUser", null, null,
                    error("404", "missingUser", "ORDER_RESOURCE_NOT_FOUND"),
                    error("409", "userStatusConflict", "ORDER_BUSINESS_CONFLICT"),
                    error("500", "systemError", "ORDER_SYSTEM_ERROR")),
            operation("/payments/callback", "post", "receivePaymentCallback", "Payments", "200", "PaymentCallbackResponse",
                    "firstSuccess", "PaymentCallbackRequest", "paymentCallbackRequest",
                    error("400", "invalidCallback", "ORDER_PARAM_INVALID"),
                    error("404", "missingPayment", "ORDER_RESOURCE_NOT_FOUND"),
                    error("409", "callbackConflict", "ORDER_BUSINESS_CONFLICT"),
                    error("500", "systemError", "ORDER_SYSTEM_ERROR")),
            operation("/api/faults/token-expired", "post", "simulateTokenExpiredFault", "Faults", null, null,
                    null, null, null,
                    error("401", "tokenExpired", "ORDER_TOKEN_EXPIRED"),
                    error("500", "systemError", "ORDER_SYSTEM_ERROR")),
            operation("/api/faults/slow-sql", "get", "simulateSlowSqlFault", "Faults", "200", "SlowSqlResponse",
                    "slowSql", null, null,
                    error("400", "invalidDelay", "ORDER_PARAM_INVALID"),
                    error("500", "systemError", "ORDER_SYSTEM_ERROR")));

    @Autowired
    private MockMvc mockMvc;

    @Autowired
    private ObjectMapper objectMapper;

    @MockitoBean
    private UserMapper userMapper;

    @MockitoBean
    private ProductMapper productMapper;

    @MockitoBean
    private CouponMapper couponMapper;

    @MockitoBean
    private UserCouponMapper userCouponMapper;

    @MockitoBean
    private InventoryMapper inventoryMapper;

    @MockitoBean
    private OrderMapper orderMapper;

    @MockitoBean
    private OrderItemMapper orderItemMapper;

    @MockitoBean
    private PaymentMapper paymentMapper;

    @MockitoBean
    private PaymentCallbackMapper paymentCallbackMapper;

    @MockitoBean
    private SlowSqlMapper slowSqlMapper;

    @Test
    void openApiJsonExposesTheDocumentedOperations() throws Exception {
        JsonNode document = openApiDocument();

        assertThat(document.path("openapi").asText()).isEqualTo(OPENAPI_VERSION);
        assertThat(document.path("info").path("title").asText()).isEqualTo(API_TITLE);
        assertThat(document.path("info").path("version").asText()).isEqualTo(API_VERSION);
        List<String> declaredTags = new ArrayList<>();
        document.path("tags").forEach(tag -> declaredTags.add(tag.path("name").asText()));
        assertThat(declaredTags).doesNotHaveDuplicates();
        assertThat(declaredTags).containsExactlyInAnyOrderElementsOf(CORE_TAGS);
        assertThat(document.path("paths").isObject()).isTrue();
        assertThat(document.path("paths").size()).isEqualTo(EXPECTED_OPERATIONS.stream()
                .map(ExpectedOperation::path)
                .distinct()
                .count());

        for (ExpectedOperation expected : EXPECTED_OPERATIONS) {
            JsonNode operation = operation(document, expected);
            assertThat(operation.isObject())
                    .as("operation %s %s exists", expected.method(), expected.path())
                    .isTrue();
            assertThat(operation.path("operationId").asText())
                    .as("operationId for %s %s", expected.method(), expected.path())
                    .isEqualTo(expected.operationId());
            assertThat(operation.path("tags").isArray()).isTrue();
            assertThat(operation.path("tags").size()).isEqualTo(1);
            assertThat(operation.path("tags").get(0).asText()).isEqualTo(expected.tag());

            Set<String> expectedResponseCodes = new LinkedHashSet<>();
            if (expected.successResponse() != null) {
                expectedResponseCodes.add(expected.successResponse());
                JsonNode successContent = requiredResponseContent(operation, expected.successResponse(), expected);
                assertSchemaReference(successContent, expected.successSchema(), expected,
                        expected.successResponse());
                JsonNode successExample = exampleValue(successContent, expected.successExample(),
                        "success example for " + expected.operationId());
                assertThat(successExample.path("success").asBoolean()).isTrue();
                assertThat(successExample.path("code").asText()).isEqualTo("ORDER_SUCCESS");
                assertThat(successExample.path("message").asText()).isEqualTo("success");
                assertThat(successExample.has("data")).isTrue();
                assertThat(successExample.path("data").isNull()).isFalse();
            }

            for (ExpectedError expectedError : expected.errors()) {
                expectedResponseCodes.add(expectedError.responseCode());
                JsonNode errorContent = requiredResponseContent(operation, expectedError.responseCode(), expected);
                assertSchemaReference(errorContent, "ApiResponse", expected, expectedError.responseCode());
                JsonNode errorExample = exampleValue(errorContent, expectedError.exampleName(),
                        "error example " + expectedError.responseCode() + " for " + expected.operationId());
                assertThat(errorExample.path("success").asBoolean()).isFalse();
                assertThat(errorExample.path("code").asText()).isEqualTo(expectedError.businessCode());
                assertThat(errorExample.path("message").asText()).isNotBlank();
                assertThat(errorExample.has("data")).isTrue();
                assertThat(errorExample.path("data").isNull()).isTrue();
            }

            assertThat(fieldNames(operation.path("responses")))
                    .as("response status set for %s %s", expected.method(), expected.path())
                    .containsExactlyInAnyOrderElementsOf(expectedResponseCodes);

            if (expected.requestSchema() != null) {
                JsonNode requestBody = operation.path("requestBody");
                assertThat(requestBody.isObject())
                        .as("request body for %s %s", expected.method(), expected.path())
                        .isTrue();
                assertThat(requestBody.path("required").asBoolean())
                        .as("request body must be required for %s %s", expected.method(), expected.path())
                        .isTrue();
                JsonNode requestContent = requestBody.path("content").path(MediaType.APPLICATION_JSON_VALUE);
                assertThat(requestContent.isObject())
                        .as("request content for %s %s", expected.method(), expected.path())
                        .isTrue();
                assertSchemaReference(requestContent, expected.requestSchema(), expected, "request");
                JsonNode requestExample = exampleValue(requestContent, expected.requestExample(),
                        "request example for " + expected.operationId());
                assertThat(requestExample.isObject())
                        .as("request example must be a JSON object for %s", expected.operationId())
                        .isTrue();
            }
        }
    }

    @Test
    void operationIdsAreNonEmptyLowerCamelCaseAndGloballyUnique() throws Exception {
        JsonNode document = openApiDocument();
        List<String> operationIds = new ArrayList<>();
        for (ActualOperation actual : actualOperations(document)) {
            String operationId = actual.operation().path("operationId").asText();
            assertThat(operationId)
                    .as("operationId for %s %s", actual.method(), actual.path())
                    .isNotBlank()
                    .matches("^[a-z][A-Za-z0-9]*$");
            operationIds.add(operationId);
        }
        assertThat(operationIds).hasSize(EXPECTED_OPERATIONS.size());
        assertThat(operationIds).doesNotHaveDuplicates();
        assertThat(operationIds).containsExactlyInAnyOrderElementsOf(
                EXPECTED_OPERATIONS.stream().map(ExpectedOperation::operationId).toList());
    }

    @Test
    void schemasExposeDtosVosAndRealValidationConstraints() throws Exception {
        JsonNode document = openApiDocument();
        JsonNode schemas = document.path("components").path("schemas");
        assertThat(schemas.isObject()).isTrue();
        Set<String> schemaNames = new LinkedHashSet<>();
        schemas.fieldNames().forEachRemaining(schemaNames::add);
        assertThat(schemaNames).contains(
                "ApiResponse",
                "OrderDetailResponse", "ProductResponse", "ProductPageResponse",
                "CouponResponse", "UserCouponResponse", "UserCouponListResponse",
                "UserResponse", "PaymentCallbackResponse", "SlowSqlResponse", "SlowSqlData",
                "CreateOrderRequest", "CreateOrderItemRequest", "OrderDetailVO", "OrderItemVO",
                "CreateProductRequest", "ProductVO", "ProductPageVO",
                "CreateUserRequest", "UserVO",
                "CouponVO", "UserCouponVO",
                "PaymentCallbackRequest", "PaymentCallbackResultVO");

        assertRequired(schemas, "ApiResponse", "success", "code", "message");
        for (String responseSchema : List.of(
                "OrderDetailResponse", "ProductResponse", "ProductPageResponse", "CouponResponse",
                "UserCouponResponse", "UserCouponListResponse", "UserResponse",
                "PaymentCallbackResponse", "SlowSqlResponse")) {
            assertRequired(schemas, responseSchema, "success", "code", "message", "data");
        }

        assertRequired(schemas, "CreateOrderRequest", "userId", "items");
        assertTypeAndFormat(assertProperty(schemas, "CreateOrderRequest", "userId"), "integer", "int64");
        assertMinimum(schemas, "CreateOrderRequest", "userId", "1");
        assertMinimum(schemas, "CreateOrderRequest", "couponId", "1");
        assertNullableTypeAndFormat(assertProperty(schemas, "CreateOrderRequest", "couponId"), "integer", "int64");
        assertThat(assertProperty(schemas, "CreateOrderRequest", "items").path("minItems").asInt())
                .isEqualTo(1);
        assertRequired(schemas, "CreateOrderItemRequest", "productId", "quantity");
        assertTypeAndFormat(assertProperty(schemas, "CreateOrderItemRequest", "productId"), "integer", "int64");
        assertThat(assertProperty(schemas, "CreateOrderItemRequest", "quantity").path("type").asText())
                .isEqualTo("integer");
        assertMinimum(schemas, "CreateOrderItemRequest", "productId", "1");
        assertMinimum(schemas, "CreateOrderItemRequest", "quantity", "1");

        assertRequired(schemas, "CreateProductRequest", "productNo", "productName", "price");
        assertThat(assertProperty(schemas, "CreateProductRequest", "productNo").path("maxLength").asInt())
                .isEqualTo(64);
        assertThat(assertProperty(schemas, "CreateProductRequest", "productName").path("maxLength").asInt())
                .isEqualTo(128);
        assertThat(assertProperty(schemas, "CreateProductRequest", "price").path("format").asText())
                .isEqualTo("double");
        assertThat(assertProperty(schemas, "CreateProductRequest", "price").path("type").asText())
                .isEqualTo("number");
        assertThat(assertProperty(schemas, "CreateProductRequest", "price").path("minimum").asText())
                .isEqualTo("0.01");
        assertThat(enumValues(assertProperty(schemas, "CreateProductRequest", "status")))
                .containsExactlyInAnyOrder("ON_SALE", "OFF_SALE");

        assertRequired(schemas, "CreateUserRequest", "userNo", "userName");
        assertThat(assertProperty(schemas, "CreateUserRequest", "userNo").path("maxLength").asInt())
                .isEqualTo(64);
        assertThat(assertProperty(schemas, "CreateUserRequest", "userName").path("maxLength").asInt())
                .isEqualTo(128);

        assertThat(enumValues(assertProperty(schemas, "OrderDetailVO", "status")))
                .containsExactlyInAnyOrder("PENDING_PAYMENT", "PAID", "CANCELLED");
        assertRequired(schemas, "OrderDetailVO", "id", "orderNo", "userId", "originalAmount",
                "discountAmount", "payableAmount", "status", "createdAt", "updatedAt");
        assertTypeAndFormat(assertProperty(schemas, "OrderDetailVO", "id"), "integer", "int64");
        assertThat(assertProperty(schemas, "OrderDetailVO", "payableAmount").path("type").asText())
                .isEqualTo("number");
        assertThat(assertProperty(schemas, "OrderDetailVO", "createdAt").path("format").asText())
                .isEqualTo("date-time");
        assertThat(assertProperty(schemas, "OrderDetailVO", "items").path("minItems").asInt())
                .isEqualTo(1);
        assertThat(enumValues(assertProperty(schemas, "ProductVO", "status")))
                .containsExactlyInAnyOrder("ON_SALE", "OFF_SALE");
        assertThat(assertProperty(schemas, "ProductVO", "price").path("type").asText())
                .isEqualTo("number");
        assertThat(assertProperty(schemas, "ProductPageVO", "records").path("type").asText())
                .isEqualTo("array");
        assertThat(enumValues(assertProperty(schemas, "UserVO", "status")))
                .containsExactlyInAnyOrder("ENABLED", "DISABLED");
        assertThat(assertProperty(schemas, "UserVO", "createdAt").path("format").asText())
                .isEqualTo("date-time");
        assertThat(enumValues(assertProperty(schemas, "CouponVO", "status")))
                .containsExactlyInAnyOrder("ACTIVE", "INACTIVE");
        assertThat(enumValues(assertProperty(schemas, "UserCouponVO", "status")))
                .containsExactlyInAnyOrder("AVAILABLE", "USED", "EXPIRED");
        assertThat(assertProperty(schemas, "UserCouponVO", "coupon").path("$ref").asText())
                .isEqualTo("#/components/schemas/CouponVO");

        JsonNode callbackRequest = schemas.path("PaymentCallbackRequest");
        assertThat(stringValues(callbackRequest.path("required")))
                .contains("callbackId", "paymentId", "orderId", "paymentAmount", "result");
        assertTypeAndFormat(callbackRequest.path("properties").path("paymentId"), "integer", "int64");
        assertTypeAndFormat(callbackRequest.path("properties").path("orderId"), "integer", "int64");
        assertThat(callbackRequest.path("properties").path("paymentAmount").path("minimum").asText())
                .isEqualTo("0");
        assertThat(callbackRequest.path("properties").path("paymentAmount").path("type").asText())
                .isEqualTo("number");
        assertThat(callbackRequest.path("properties").path("paymentAmount").path("format").asText())
                .isEqualTo("double");
        assertThat(callbackRequest.path("properties").path("callbackTime").path("format").asText())
                .isEqualTo("date-time");
        assertThat(enumValues(callbackRequest.path("properties").path("result")))
                .containsExactly("SUCCESS");
        assertThat(enumValues(schemas.path("PaymentCallbackResultVO").path("properties").path("outcome")))
                .containsExactlyInAnyOrder("FIRST_SUCCESS", "IDEMPOTENT_REPLAY");
        assertThat(assertProperty(schemas, "CouponVO", "thresholdAmount").path("type").asText())
                .isEqualTo("number");
        assertThat(assertProperty(schemas, "SlowSqlData", "requestedDelayMs").path("minimum").asInt())
                .isEqualTo(100);
        assertThat(assertProperty(schemas, "SlowSqlData", "requestedDelayMs").path("maximum").asInt())
                .isEqualTo(2000);
        assertThat(assertProperty(schemas, "SlowSqlData", "elapsedMs").path("format").asText())
                .isEqualTo("int64");

        JsonNode userCouponStatus = parameter(
                operation(document, expected("listUserCoupons")), "status").path("schema");
        assertThat(enumValues(userCouponStatus))
                .containsExactlyInAnyOrder("AVAILABLE", "USED", "EXPIRED");
        JsonNode productPage = operation(document, expected("listProducts"));
        assertThat(parameter(productPage, "pageNo").path("schema").path("minimum").asText())
                .isEqualTo("1");
        assertThat(parameter(productPage, "pageSize").path("schema").path("minimum").asText())
                .isEqualTo("1");
        assertThat(parameter(productPage, "pageSize").path("schema").path("maximum").asText())
                .isEqualTo("100");
        assertThat(parameter(productPage, "productNo").path("schema").path("maxLength").asInt())
                .isEqualTo(64);
        assertThat(parameter(productPage, "productName").path("schema").path("maxLength").asInt())
                .isEqualTo(128);
        assertThat(parameter(productPage, "status").path("schema").path("maxLength").asInt())
                .isEqualTo(32);

        JsonNode delayMs = parameter(operation(document, expected("simulateSlowSqlFault")), "delayMs").path("schema");
        assertTypeAndFormat(delayMs, "integer", "int32");
        assertThat(delayMs.path("minimum").asText()).isEqualTo("100");
        assertThat(delayMs.path("maximum").asText()).isEqualTo("2000");
        assertThat(delayMs.path("default").asText()).isEqualTo("500");

        assertPositivePathParameter(operation(document, expected("getOrderDetail")), "orderId");
        assertPositivePathParameter(operation(document, expected("cancelOrder")), "orderId");
        assertPathParameter(operation(document, expected("getProduct")), "id", null);
        assertPathParameter(operation(document, expected("offShelfProduct")), "id", null);
        assertPathParameter(operation(document, expected("getCoupon")), "couponId", "1");
        assertPathParameter(operation(document, expected("claimCoupon")), "userId", "1");
        assertPathParameter(operation(document, expected("claimCoupon")), "couponId", "1");
        assertPathParameter(operation(document, expected("listUserCoupons")), "userId", "1");
        assertPathParameter(operation(document, expected("getUser")), "id", null);
        assertPathParameter(operation(document, expected("disableUser")), "id", null);

        JsonNode couponId = schemas.path("CreateOrderRequest").path("properties").path("couponId");
        assertThat(couponId.path("description").asText()).containsIgnoringCase("coupon template");
        assertThat(schemas.toString()).doesNotContain("OrderEntity", "ProductEntity", "CouponEntity", "UserEntity");
    }

    @Test
    void securitySchemeExistsWithoutFakeGlobalOrOperationSecurity() throws Exception {
        JsonNode document = openApiDocument();
        JsonNode bearerAuth = document.path("components").path("securitySchemes").path("bearerAuth");
        assertThat(bearerAuth.isObject()).isTrue();
        assertThat(bearerAuth.path("type").asText()).isEqualTo("http");
        assertThat(bearerAuth.path("scheme").asText()).isEqualTo("bearer");
        assertThat(bearerAuth.path("bearerFormat").asText()).isEqualTo("JWT");
        assertThat(document.path("security").isMissingNode()).isTrue();

        for (ExpectedOperation expected : EXPECTED_OPERATIONS) {
            JsonNode security = operation(document, expected).path("security");
            assertThat(security.isMissingNode() || (security.isArray() && security.isEmpty()))
                    .as("public operation must not require bearerAuth: %s %s", expected.method(), expected.path())
                    .isTrue();
        }
    }

    @Test
    void knife4jUiAndMachineDocumentAreReachable() throws Exception {
        mockMvc.perform(get("/v3/api-docs"))
                .andExpect(status().isOk())
                .andExpect(result -> assertThat(result.getResponse().getContentType())
                        .isEqualTo(MediaType.APPLICATION_JSON_VALUE));
        mockMvc.perform(get("/doc.html"))
                .andExpect(status().isOk())
                .andExpect(result -> assertThat(result.getResponse().getContentType())
                        .startsWith(MediaType.TEXT_HTML_VALUE))
                .andExpect(result -> assertThat(result.getResponse().getContentAsString())
                        .isNotBlank());
    }

    private JsonNode openApiDocument() throws Exception {
        String responseBody = mockMvc.perform(get("/v3/api-docs"))
                .andExpect(status().isOk())
                .andReturn()
                .getResponse()
                .getContentAsString();
        JsonNode document = objectMapper.readTree(responseBody);
        List<String> actualPaths = new ArrayList<>();
        document.path("paths").fieldNames().forEachRemaining(actualPaths::add);
        assertThat(actualPaths).containsExactlyInAnyOrderElementsOf(
                EXPECTED_OPERATIONS.stream().map(ExpectedOperation::path).distinct().toList());
        List<String> actualOperationKeys = actualOperations(document).stream()
                .map(ActualOperation::key)
                .toList();
        assertThat(actualOperationKeys)
                .containsExactlyInAnyOrderElementsOf(EXPECTED_OPERATIONS.stream()
                        .map(ExpectedOperation::key)
                        .toList());
        return document;
    }

    private static JsonNode operation(JsonNode document, ExpectedOperation expected) {
        return document.path("paths").path(expected.path()).path(expected.method());
    }

    private static JsonNode requiredResponseContent(
            JsonNode operation,
            String responseCode,
            ExpectedOperation expectedOperation
    ) {
        JsonNode response = operation.path("responses").path(responseCode);
        assertThat(response.isObject())
                .as("response %s for %s %s exists", responseCode,
                        expectedOperation.method(), expectedOperation.path())
                .isTrue();
        JsonNode content = response.path("content").path(MediaType.APPLICATION_JSON_VALUE);
        assertThat(content.isObject())
                .as("JSON content for response %s of %s %s", responseCode,
                        expectedOperation.method(), expectedOperation.path())
                .isTrue();
        return content;
    }

    private static void assertSchemaReference(
            JsonNode content,
            String schemaName,
            ExpectedOperation expectedOperation,
            String responseCode
    ) {
        assertThat(content.path("schema").path("$ref").asText())
                .as("schema reference for %s response of %s %s", responseCode,
                        expectedOperation.method(), expectedOperation.path())
                .isEqualTo("#/components/schemas/" + schemaName);
    }

    private JsonNode exampleValue(JsonNode content, String exampleName, String description) throws Exception {
        JsonNode example = content.path("examples").path(exampleName);
        assertThat(example.isObject()).as("%s exists", description).isTrue();
        JsonNode value = example.path("value");
        assertThat(value.isMissingNode()).as("%s has a value", description).isFalse();
        return value.isTextual() ? objectMapper.readTree(value.asText()) : value;
    }

    private static List<ActualOperation> actualOperations(JsonNode document) {
        List<ActualOperation> operations = new ArrayList<>();
        document.path("paths").fields().forEachRemaining(pathEntry ->
                pathEntry.getValue().fields().forEachRemaining(methodEntry -> {
                    if (HTTP_METHODS.contains(methodEntry.getKey())) {
                        operations.add(new ActualOperation(
                                pathEntry.getKey(), methodEntry.getKey(), methodEntry.getValue()));
                    }
                }));
        return operations;
    }

    private static Set<String> fieldNames(JsonNode object) {
        Set<String> names = new LinkedHashSet<>();
        object.fieldNames().forEachRemaining(names::add);
        return names;
    }

    private static ExpectedOperation expected(String operationId) {
        return EXPECTED_OPERATIONS.stream()
                .filter(candidate -> candidate.operationId().equals(operationId))
                .findFirst()
                .orElseThrow();
    }

    private static void assertPathParameter(JsonNode operation, String name, String minimum) {
        JsonNode parameter = parameter(operation, name);
        assertThat(parameter.path("in").asText()).isEqualTo("path");
        assertThat(parameter.path("required").asBoolean()).isTrue();
        assertTypeAndFormat(parameter.path("schema"), "integer", "int64");
        if (minimum != null) {
            assertThat(parameter.path("schema").path("minimum").asText()).isEqualTo(minimum);
        }
    }

    private static void assertPositivePathParameter(JsonNode operation, String name) {
        JsonNode schema = parameter(operation, name).path("schema");
        assertPathParameter(operation, name, null);
        assertThat(schema.path("minimum").asText()).isEqualTo("0");
        assertThat(schema.path("exclusiveMinimum").asBoolean()).isTrue();
    }

    private static JsonNode parameter(JsonNode operation, String name) {
        for (JsonNode parameter : operation.path("parameters")) {
            if (name.equals(parameter.path("name").asText())) {
                return parameter;
            }
        }
        throw new AssertionError("parameter not found: " + name);
    }

    private static void assertRequired(JsonNode schemas, String schemaName, String... fields) {
        JsonNode required = schemas.path(schemaName).path("required");
        assertThat(stringValues(required)).contains(fields);
    }

    private static void assertMinimum(JsonNode schemas, String schemaName, String field, String minimum) {
        assertThat(assertProperty(schemas, schemaName, field).path("minimum").asText())
                .as("minimum for %s.%s", schemaName, field)
                .isEqualTo(minimum);
    }

    private static void assertTypeAndFormat(JsonNode schema, String type, String format) {
        assertThat(schema.path("type").asText()).isEqualTo(type);
        assertThat(schema.path("format").asText()).isEqualTo(format);
    }

    private static void assertNullableTypeAndFormat(JsonNode schema, String type, String format) {
        JsonNode typeNode = schema.path("type");
        if (typeNode.isArray()) {
            assertThat(stringValues(typeNode)).contains(type);
        } else {
            assertThat(typeNode.asText()).isEqualTo(type);
        }
        assertThat(schema.path("format").asText()).isEqualTo(format);
    }

    private static JsonNode assertProperty(JsonNode schemas, String schemaName, String propertyName) {
        JsonNode property = schemas.path(schemaName).path("properties").path(propertyName);
        assertThat(property.isObject()).as("schema property %s.%s exists", schemaName, propertyName).isTrue();
        return property;
    }

    private static List<String> enumValues(JsonNode schema) {
        List<String> values = new ArrayList<>();
        schema.path("enum").forEach(value -> values.add(value.asText()));
        return values;
    }

    private static List<String> stringValues(JsonNode array) {
        List<String> values = new ArrayList<>();
        array.forEach(value -> values.add(value.asText()));
        return values;
    }

    private static ExpectedOperation operation(
            String path,
            String method,
            String operationId,
            String tag,
            String successResponse,
            String successSchema,
            String successExample,
            String requestSchema,
            String requestExample,
            ExpectedError... errors
    ) {
        return new ExpectedOperation(path, method, operationId, tag, successResponse,
                successSchema, successExample, requestSchema, requestExample, List.of(errors));
    }

    private static ExpectedError error(String responseCode, String exampleName, String businessCode) {
        return new ExpectedError(responseCode, exampleName, businessCode);
    }

    private record ExpectedOperation(
            String path,
            String method,
            String operationId,
            String tag,
            String successResponse,
            String successSchema,
            String successExample,
            String requestSchema,
            String requestExample,
            List<ExpectedError> errors
    ) {
        private String key() {
            return method + " " + path;
        }
    }

    private record ExpectedError(
            String responseCode,
            String exampleName,
            String businessCode
    ) {
    }

    private record ActualOperation(
            String path,
            String method,
            JsonNode operation
    ) {
        private String key() {
            return method + " " + path;
        }
    }
}
