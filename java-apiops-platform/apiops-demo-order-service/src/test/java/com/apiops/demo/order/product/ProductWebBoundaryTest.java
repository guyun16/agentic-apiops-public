package com.apiops.demo.order.product;

import com.apiops.demo.order.common.web.GlobalExceptionHandler;
import com.apiops.demo.order.product.application.ProductApplicationService;
import com.apiops.demo.order.product.controller.ProductController;
import com.apiops.demo.order.product.vo.ProductPageVO;
import com.apiops.demo.order.product.vo.ProductVO;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.WebMvcTest;
import org.springframework.boot.test.context.TestConfiguration;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Import;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;

import java.math.BigDecimal;
import java.util.List;

import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.put;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

@WebMvcTest(controllers = ProductController.class)
@Import({GlobalExceptionHandler.class, ProductWebBoundaryTest.StubConfig.class})
class ProductWebBoundaryTest {

    @TestConfiguration
    static class StubConfig {
        @Bean
        ProductApplicationService productApplicationService() {
            return new ProductApplicationService(null) {
                @Override
                public ProductVO createProduct(String productNo, String productName,
                                                BigDecimal price, String status) {
                    ProductVO vo = product(1L, productNo, productName, price, status);
                    return vo;
                }

                @Override
                public ProductVO queryById(Long id) {
                    return product(id, "prd_test", "Test Product", BigDecimal.ONE, "ON_SALE");
                }

                @Override
                public ProductPageVO page(com.apiops.demo.order.product.dto.ProductPageQuery query) {
                    ProductPageVO page = new ProductPageVO();
                    page.setTotal(1);
                    page.setPageNo(query.getPageNo());
                    page.setPageSize(query.getPageSize());
                    page.setRecords(List.of(product(1L, "prd_test", "Test Product", BigDecimal.ONE, "ON_SALE")));
                    return page;
                }

                @Override
                public ProductVO offShelf(Long id) {
                    return product(id, "prd_test", "Test Product", BigDecimal.ONE, "OFF_SALE");
                }

                private ProductVO product(Long id, String no, String name, BigDecimal price, String status) {
                    ProductVO vo = new ProductVO();
                    vo.setId(id);
                    vo.setProductNo(no);
                    vo.setProductName(name);
                    vo.setPrice(price);
                    vo.setStatus(status);
                    return vo;
                }
            };
        }
    }

    @Autowired
    private MockMvc mockMvc;

    @Test
    void productEndpointsReturnVOAndPageData() throws Exception {
        mockMvc.perform(post("/products")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"productNo\":\"prd_test\",\"productName\":\"Test Product\",\"price\":1.00}"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.success").value(true))
                .andExpect(jsonPath("$.data.productNo").value("prd_test"))
                .andExpect(jsonPath("$.data.price").value(1.0))
                .andExpect(jsonPath("$.data.deleted").doesNotExist())
                .andExpect(jsonPath("$.data.version").doesNotExist());

        mockMvc.perform(get("/products/1"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.productName").value("Test Product"));
        mockMvc.perform(get("/products?pageNo=1&pageSize=2&productName=Test&status=ON_SALE"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.total").value(1))
                .andExpect(jsonPath("$.data.pageNo").value(1))
                .andExpect(jsonPath("$.data.pageSize").value(2))
                .andExpect(jsonPath("$.data.records[0].productNo").value("prd_test"));
        mockMvc.perform(put("/products/1/off-shelf"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.status").value("OFF_SALE"));
    }

    @Test
    void invalidProductRequestAndPageParametersAreRejected() throws Exception {
        mockMvc.perform(post("/products")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"productNo\":\"\",\"productName\":\"x\",\"price\":0}"))
                .andExpect(status().isBadRequest());
        mockMvc.perform(post("/products")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"productNo\":\"prd_invalid_status\",\"productName\":\"x\",\"price\":1,\"status\":\"INVALID\"}"))
                .andExpect(status().isBadRequest());
        mockMvc.perform(get("/products?pageNo=0&pageSize=101"))
                .andExpect(status().isBadRequest());
    }
}
