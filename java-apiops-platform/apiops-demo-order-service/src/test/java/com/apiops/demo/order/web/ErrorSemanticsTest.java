package com.apiops.demo.order.web;

import com.apiops.demo.order.common.exception.DemoOrderBusinessException;
import com.apiops.demo.order.common.exception.DemoOrderErrorCode;
import com.apiops.demo.order.common.web.ApiResponse;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.EnumSource;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatIllegalArgumentException;
import static org.assertj.core.api.Assertions.assertThatNullPointerException;

class ErrorSemanticsTest {

    @Test
    void failureResponseRejectsNullAndSuccessErrorCodes() {
        assertThatNullPointerException()
                .isThrownBy(() -> ApiResponse.fail(null));
        assertThatNullPointerException()
                .isThrownBy(() -> ApiResponse.fail(null, "safe message"));
        assertThatIllegalArgumentException()
                .isThrownBy(() -> ApiResponse.fail(DemoOrderErrorCode.SUCCESS));
        assertThatIllegalArgumentException()
                .isThrownBy(() -> ApiResponse.fail(
                        DemoOrderErrorCode.SUCCESS,
                        "safe message"
                ));
    }

    @Test
    void businessConflictCanConstructBusinessException() {
        DemoOrderBusinessException exception = new DemoOrderBusinessException(
                DemoOrderErrorCode.BUSINESS_CONFLICT
        );

        assertThat(exception.getErrorCode()).isEqualTo(DemoOrderErrorCode.BUSINESS_CONFLICT);
        assertThat(exception.getMessage()).isEqualTo("business conflict");
    }

    @ParameterizedTest
    @EnumSource(
            value = DemoOrderErrorCode.class,
            names = "BUSINESS_CONFLICT",
            mode = EnumSource.Mode.EXCLUDE
    )
    void otherErrorCodesCannotConstructBusinessException(DemoOrderErrorCode errorCode) {
        assertThatIllegalArgumentException()
                .isThrownBy(() -> new DemoOrderBusinessException(errorCode));
        assertThatIllegalArgumentException()
                .isThrownBy(() -> new DemoOrderBusinessException(errorCode, "safe message"));
    }
}
