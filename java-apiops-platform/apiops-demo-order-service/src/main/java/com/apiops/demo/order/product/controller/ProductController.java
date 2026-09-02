package com.apiops.demo.order.product.controller;

import com.apiops.demo.order.common.web.ApiResponse;
import com.apiops.demo.order.product.application.ProductApplicationService;
import com.apiops.demo.order.product.dto.CreateProductRequest;
import com.apiops.demo.order.product.dto.ProductPageQuery;
import com.apiops.demo.order.product.vo.ProductPageVO;
import com.apiops.demo.order.product.vo.ProductVO;
import com.apiops.demo.order.openapi.OpenApiSuccessResponses;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.Parameter;
import io.swagger.v3.oas.annotations.media.Content;
import io.swagger.v3.oas.annotations.media.ExampleObject;
import io.swagger.v3.oas.annotations.media.Schema;
import io.swagger.v3.oas.annotations.responses.ApiResponses;
import jakarta.validation.Valid;
import org.springframework.validation.annotation.Validated;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.ModelAttribute;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@Validated
@RestController
@RequestMapping("/products")
public class ProductController {

    private final ProductApplicationService productApplicationService;

    public ProductController(ProductApplicationService productApplicationService) {
        this.productApplicationService = productApplicationService;
    }

    @Operation(
            operationId = "createProduct",
            summary = "Create a product",
            description = "Creates a catalog product. When status is omitted, the service stores ON_SALE.",
            tags = {"Products"})
    @ApiResponses({
            @io.swagger.v3.oas.annotations.responses.ApiResponse(
                    responseCode = "200", description = "Product created.",
                    content = @Content(mediaType = "application/json",
                            schema = @Schema(implementation = OpenApiSuccessResponses.ProductResponse.class),
                            examples = @ExampleObject(name = "createdProduct", value = """
                                    {
                                      "success": true,
                                      "code": "ORDER_SUCCESS",
                                      "message": "success",
                                      "data": {
                                        "id": 1,
                                        "productNo": "prd_test",
                                        "productName": "Test Product",
                                        "price": 1.00,
                                        "status": "ON_SALE",
                                        "createdAt": "2025-01-01T00:00:00",
                                        "updatedAt": "2025-01-01T00:00:00"
                                      }
                                    }
                                    """))),
            @io.swagger.v3.oas.annotations.responses.ApiResponse(
                    responseCode = "400", description = "Request body validation failed.",
                    content = @Content(mediaType = "application/json",
                            schema = @Schema(implementation = ApiResponse.class),
                            examples = @ExampleObject(name = "invalidParameter", value = """
                                    {"success":false,"code":"ORDER_PARAM_INVALID","message":"request parameter invalid","data":null}
                                    """))),
            @io.swagger.v3.oas.annotations.responses.ApiResponse(
                    responseCode = "409", description = "The product number already exists.",
                    content = @Content(mediaType = "application/json",
                            schema = @Schema(implementation = ApiResponse.class),
                            examples = @ExampleObject(name = "duplicateProductNumber", value = """
                                    {"success":false,"code":"ORDER_BUSINESS_CONFLICT","message":"product with productNo prd_001 already exists","data":null}
                                    """))),
            @io.swagger.v3.oas.annotations.responses.ApiResponse(
                    responseCode = "500", description = "Unexpected server failure.",
                    content = @Content(mediaType = "application/json",
                            schema = @Schema(implementation = ApiResponse.class),
                            examples = @ExampleObject(name = "systemError", value = """
                                    {"success":false,"code":"ORDER_SYSTEM_ERROR","message":"internal server error","data":null}
                                    """)))
    })
    @PostMapping
    ApiResponse<ProductVO> createProduct(
            @io.swagger.v3.oas.annotations.parameters.RequestBody(
                    description = "Product business number, name, price, and optional initial status.",
                    required = true,
                    content = @Content(mediaType = "application/json",
                            examples = @ExampleObject(name = "createProductRequest", value = """
                                    {"productNo":"prd_test","productName":"Test Product","price":1.00,"status":"ON_SALE"}
                                    """)))
            @Valid @RequestBody CreateProductRequest request) {
        return ApiResponse.success(productApplicationService.createProduct(
                request.getProductNo(), request.getProductName(), request.getPrice(), request.getStatus()));
    }

    @Operation(
            operationId = "getProduct",
            summary = "Get a product",
            description = "Returns one product catalog view by primary key.",
            tags = {"Products"})
    @ApiResponses({
            @io.swagger.v3.oas.annotations.responses.ApiResponse(
                    responseCode = "200", description = "Product returned.",
                    content = @Content(mediaType = "application/json",
                            schema = @Schema(implementation = OpenApiSuccessResponses.ProductResponse.class),
                            examples = @ExampleObject(name = "product", value = """
                                    {
                                      "success": true,
                                      "code": "ORDER_SUCCESS",
                                      "message": "success",
                                      "data": {
                                        "id": 1,
                                        "productNo": "prd_001",
                                        "productName": "Demo Product 001",
                                        "price": 100.00,
                                        "status": "ON_SALE",
                                        "createdAt": "2025-01-01T00:00:00",
                                        "updatedAt": "2025-01-01T00:00:00"
                                      }
                                    }
                                    """))),
            @io.swagger.v3.oas.annotations.responses.ApiResponse(
                    responseCode = "404", description = "Product does not exist.",
                    content = @Content(mediaType = "application/json",
                            schema = @Schema(implementation = ApiResponse.class),
                            examples = @ExampleObject(name = "missingProduct", value = """
                                    {"success":false,"code":"ORDER_RESOURCE_NOT_FOUND","message":"product id 999 not found","data":null}
                                    """))),
            @io.swagger.v3.oas.annotations.responses.ApiResponse(
                    responseCode = "500", description = "Unexpected server failure.",
                    content = @Content(mediaType = "application/json",
                            schema = @Schema(implementation = ApiResponse.class),
                            examples = @ExampleObject(name = "systemError", value = """
                                    {"success":false,"code":"ORDER_SYSTEM_ERROR","message":"internal server error","data":null}
                                    """)))
    })
    @GetMapping("/{id}")
    ApiResponse<ProductVO> queryProduct(
            @Parameter(description = "Product primary key.", example = "1",
                    schema = @Schema(type = "integer", format = "int64"))
            @PathVariable Long id) {
        return ApiResponse.success(productApplicationService.queryById(id));
    }

    @Operation(
            operationId = "listProducts",
            summary = "List products",
            description = "Returns a page of products using the optional exact/contains filters.",
            tags = {"Products"})
    @ApiResponses({
            @io.swagger.v3.oas.annotations.responses.ApiResponse(
                    responseCode = "200", description = "Product page returned.",
                    content = @Content(mediaType = "application/json",
                            schema = @Schema(implementation = OpenApiSuccessResponses.ProductPageResponse.class),
                            examples = @ExampleObject(name = "productPage", value = """
                                    {
                                      "success": true,
                                      "code": "ORDER_SUCCESS",
                                      "message": "success",
                                      "data": {
                                        "total": 1,
                                        "pageNo": 1,
                                        "pageSize": 20,
                                        "records": [
                                          {
                                            "id": 1,
                                            "productNo": "prd_001",
                                            "productName": "Demo Product 001",
                                            "price": 100.00,
                                            "status": "ON_SALE",
                                            "createdAt": "2025-01-01T00:00:00",
                                            "updatedAt": "2025-01-01T00:00:00"
                                          }
                                        ]
                                      }
                                    }
                                    """))),
            @io.swagger.v3.oas.annotations.responses.ApiResponse(
                    responseCode = "400", description = "Page or filter parameter validation failed.",
                    content = @Content(mediaType = "application/json",
                            schema = @Schema(implementation = ApiResponse.class),
                            examples = @ExampleObject(name = "invalidPage", value = """
                                    {"success":false,"code":"ORDER_PARAM_INVALID","message":"request parameter invalid","data":null}
                                    """))),
            @io.swagger.v3.oas.annotations.responses.ApiResponse(
                    responseCode = "500", description = "Unexpected server failure.",
                    content = @Content(mediaType = "application/json",
                            schema = @Schema(implementation = ApiResponse.class),
                            examples = @ExampleObject(name = "systemError", value = """
                                    {"success":false,"code":"ORDER_SYSTEM_ERROR","message":"internal server error","data":null}
                                    """)))
    })
    @GetMapping
    ApiResponse<ProductPageVO> pageProducts(@Valid @ModelAttribute ProductPageQuery query) {
        return ApiResponse.success(productApplicationService.page(query));
    }

    @Operation(
            operationId = "offShelfProduct",
            summary = "Take a product off sale",
            description = "Transitions an ON_SALE product to OFF_SALE. Repeating the request for an already off-sale product is idempotent.",
            tags = {"Products"})
    @ApiResponses({
            @io.swagger.v3.oas.annotations.responses.ApiResponse(
                    responseCode = "200", description = "Product is off sale.",
                    content = @Content(mediaType = "application/json",
                            schema = @Schema(implementation = OpenApiSuccessResponses.ProductResponse.class),
                            examples = @ExampleObject(name = "offShelfProduct", value = """
                                    {
                                      "success": true,
                                      "code": "ORDER_SUCCESS",
                                      "message": "success",
                                      "data": {
                                        "id": 1,
                                        "productNo": "prd_001",
                                        "productName": "Demo Product 001",
                                        "price": 100.00,
                                        "status": "OFF_SALE",
                                        "createdAt": "2025-01-01T00:00:00",
                                        "updatedAt": "2025-01-01T00:00:00"
                                      }
                                    }
                                    """))),
            @io.swagger.v3.oas.annotations.responses.ApiResponse(
                    responseCode = "404", description = "Product does not exist.",
                    content = @Content(mediaType = "application/json",
                            schema = @Schema(implementation = ApiResponse.class),
                            examples = @ExampleObject(name = "missingProduct", value = """
                                    {"success":false,"code":"ORDER_RESOURCE_NOT_FOUND","message":"product id 999 not found","data":null}
                                    """))),
            @io.swagger.v3.oas.annotations.responses.ApiResponse(
                    responseCode = "409", description = "Product status cannot be transitioned to OFF_SALE.",
                    content = @Content(mediaType = "application/json",
                            schema = @Schema(implementation = ApiResponse.class),
                            examples = @ExampleObject(name = "productStatusConflict", value = """
                                    {"success":false,"code":"ORDER_BUSINESS_CONFLICT","message":"product id 1 is in unexpected status, off-shelf failed","data":null}
                                    """))),
            @io.swagger.v3.oas.annotations.responses.ApiResponse(
                    responseCode = "500", description = "Unexpected server failure.",
                    content = @Content(mediaType = "application/json",
                            schema = @Schema(implementation = ApiResponse.class),
                            examples = @ExampleObject(name = "systemError", value = """
                                    {"success":false,"code":"ORDER_SYSTEM_ERROR","message":"internal server error","data":null}
                                    """)))
    })
    @PutMapping("/{id}/off-shelf")
    ApiResponse<ProductVO> offShelf(
            @Parameter(description = "Product primary key.", example = "1",
                    schema = @Schema(type = "integer", format = "int64"))
            @PathVariable Long id) {
        return ApiResponse.success(productApplicationService.offShelf(id));
    }
}
