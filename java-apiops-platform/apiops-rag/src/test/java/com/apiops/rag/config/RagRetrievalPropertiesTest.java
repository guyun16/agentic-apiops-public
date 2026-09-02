package com.apiops.rag.config;

import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertThrows;

class RagRetrievalPropertiesTest {

    @Test
    void defaultIsBackwardCompatibleWithNoFilter() {
        assertNull(new RagRetrievalProperties().getMinRelevanceScore());
    }

    @Test
    void acceptsInclusiveCosineThresholdRange() {
        RagRetrievalProperties properties = new RagRetrievalProperties();

        properties.setMinRelevanceScore(0.0);
        assertEquals(0.0, properties.getMinRelevanceScore());
        properties.setMinRelevanceScore(1.0);
        assertEquals(1.0, properties.getMinRelevanceScore());
    }

    @Test
    void rejectsInvalidThreshold() {
        RagRetrievalProperties properties = new RagRetrievalProperties();

        assertThrows(IllegalArgumentException.class,
                () -> properties.setMinRelevanceScore(-0.01));
        assertThrows(IllegalArgumentException.class,
                () -> properties.setMinRelevanceScore(1.01));
        assertThrows(IllegalArgumentException.class,
                () -> properties.setMinRelevanceScore(Double.NaN));
    }
}
