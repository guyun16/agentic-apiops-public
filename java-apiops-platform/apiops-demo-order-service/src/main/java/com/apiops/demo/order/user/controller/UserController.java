package com.apiops.demo.order.user.controller;

import com.apiops.demo.order.common.web.ApiResponse;
import com.apiops.demo.order.user.application.UserApplicationService;
import com.apiops.demo.order.user.dto.CreateUserRequest;
import com.apiops.demo.order.user.vo.UserVO;
import com.apiops.demo.order.openapi.OpenApiSuccessResponses;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.Parameter;
import io.swagger.v3.oas.annotations.media.Content;
import io.swagger.v3.oas.annotations.media.ExampleObject;
import io.swagger.v3.oas.annotations.media.Schema;
import io.swagger.v3.oas.annotations.responses.ApiResponses;
import jakarta.validation.Valid;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/users")
public class UserController {

    private final UserApplicationService userApplicationService;

    public UserController(UserApplicationService userApplicationService) {
        this.userApplicationService = userApplicationService;
    }

    @Operation(
            operationId = "createUser",
            summary = "Create a user",
            description = "Creates an enabled user from a stable user business number and display name.",
            tags = {"Users"})
    @ApiResponses({
            @io.swagger.v3.oas.annotations.responses.ApiResponse(
                    responseCode = "200", description = "User created.",
                    content = @Content(mediaType = "application/json",
                            schema = @Schema(implementation = OpenApiSuccessResponses.UserResponse.class),
                            examples = @ExampleObject(name = "createdUser", value = """
                                    {
                                      "success": true,
                                      "code": "ORDER_SUCCESS",
                                      "message": "success",
                                      "data": {
                                        "id": 100,
                                        "userNo": "usr_test",
                                        "userName": "Test User",
                                        "status": "ENABLED",
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
                    responseCode = "409", description = "The user business number already exists.",
                    content = @Content(mediaType = "application/json",
                            schema = @Schema(implementation = ApiResponse.class),
                            examples = @ExampleObject(name = "duplicateUserNumber", value = """
                                    {"success":false,"code":"ORDER_BUSINESS_CONFLICT","message":"user with userNo usr_001 already exists","data":null}
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
    ApiResponse<UserVO> createUser(
            @io.swagger.v3.oas.annotations.parameters.RequestBody(
                    description = "Stable user number and display name.",
                    required = true,
                    content = @Content(mediaType = "application/json",
                            examples = @ExampleObject(name = "createUserRequest", value = """
                                    {"userNo":"usr_test","userName":"Test User"}
                                    """)))
            @Valid @RequestBody CreateUserRequest request) {
        UserVO vo = userApplicationService.createUser(
                request.getUserNo(), request.getUserName());
        return ApiResponse.success(vo);
    }

    @Operation(
            operationId = "getUser",
            summary = "Get a user",
            description = "Returns one user view by primary key.",
            tags = {"Users"})
    @ApiResponses({
            @io.swagger.v3.oas.annotations.responses.ApiResponse(
                    responseCode = "200", description = "User returned.",
                    content = @Content(mediaType = "application/json",
                            schema = @Schema(implementation = OpenApiSuccessResponses.UserResponse.class),
                            examples = @ExampleObject(name = "user", value = """
                                    {
                                      "success": true,
                                      "code": "ORDER_SUCCESS",
                                      "message": "success",
                                      "data": {
                                        "id": 1,
                                        "userNo": "usr_001",
                                        "userName": "Demo User 001",
                                        "status": "ENABLED",
                                        "createdAt": "2025-01-01T00:00:00",
                                        "updatedAt": "2025-01-01T00:00:00"
                                      }
                                    }
                                    """))),
            @io.swagger.v3.oas.annotations.responses.ApiResponse(
                    responseCode = "404", description = "User does not exist.",
                    content = @Content(mediaType = "application/json",
                            schema = @Schema(implementation = ApiResponse.class),
                            examples = @ExampleObject(name = "missingUser", value = """
                                    {"success":false,"code":"ORDER_RESOURCE_NOT_FOUND","message":"user id 999 not found","data":null}
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
    ApiResponse<UserVO> queryUser(
            @Parameter(description = "User primary key.", example = "1",
                    schema = @Schema(type = "integer", format = "int64"))
            @PathVariable Long id) {
        UserVO vo = userApplicationService.queryById(id);
        return ApiResponse.success(vo);
    }

    @Operation(
            operationId = "disableUser",
            summary = "Disable a user",
            description = "Transitions an enabled user to DISABLED. Repeating the request for an already disabled user is idempotent.",
            tags = {"Users"})
    @ApiResponses({
            @io.swagger.v3.oas.annotations.responses.ApiResponse(
                    responseCode = "200", description = "User is disabled.",
                    content = @Content(mediaType = "application/json",
                            schema = @Schema(implementation = OpenApiSuccessResponses.UserResponse.class),
                            examples = @ExampleObject(name = "disabledUser", value = """
                                    {
                                      "success": true,
                                      "code": "ORDER_SUCCESS",
                                      "message": "success",
                                      "data": {
                                        "id": 1,
                                        "userNo": "usr_001",
                                        "userName": "Demo User 001",
                                        "status": "DISABLED",
                                        "createdAt": "2025-01-01T00:00:00",
                                        "updatedAt": "2025-01-01T00:00:00"
                                      }
                                    }
                                    """))),
            @io.swagger.v3.oas.annotations.responses.ApiResponse(
                    responseCode = "404", description = "User does not exist.",
                    content = @Content(mediaType = "application/json",
                            schema = @Schema(implementation = ApiResponse.class),
                            examples = @ExampleObject(name = "missingUser", value = """
                                    {"success":false,"code":"ORDER_RESOURCE_NOT_FOUND","message":"user id 999 not found","data":null}
                                    """))),
            @io.swagger.v3.oas.annotations.responses.ApiResponse(
                    responseCode = "409", description = "User is in an unexpected state for disabling.",
                    content = @Content(mediaType = "application/json",
                            schema = @Schema(implementation = ApiResponse.class),
                            examples = @ExampleObject(name = "userStatusConflict", value = """
                                    {"success":false,"code":"ORDER_BUSINESS_CONFLICT","message":"user id 1 is in unexpected status, disable failed","data":null}
                                    """))),
            @io.swagger.v3.oas.annotations.responses.ApiResponse(
                    responseCode = "500", description = "Unexpected server failure.",
                    content = @Content(mediaType = "application/json",
                            schema = @Schema(implementation = ApiResponse.class),
                            examples = @ExampleObject(name = "systemError", value = """
                                    {"success":false,"code":"ORDER_SYSTEM_ERROR","message":"internal server error","data":null}
                                    """)))
    })
    @PutMapping("/{id}/disable")
    ApiResponse<UserVO> disableUser(
            @Parameter(description = "User primary key.", example = "1",
                    schema = @Schema(type = "integer", format = "int64"))
            @PathVariable Long id) {
        UserVO vo = userApplicationService.disableUser(id);
        return ApiResponse.success(vo);
    }
}
