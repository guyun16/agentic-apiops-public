package com.apiops.rag.splitter;

import org.junit.jupiter.api.Test;

import java.util.List;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;

class FixedSizeTextSplitterTest {

    @Test
    void keepsSmallTextAsOneChunk() {
        TextSplitter splitter = splitter(10, 2);

        assertEquals(List.of("small"), splitter.split("small"));
    }

    @Test
    void splitsLargeTextWithStableOrderAndOverlap() {
        TextSplitter splitter = splitter(4, 1);

        List<String> first = splitter.split("abcdefghij");
        List<String> second = splitter.split("abcdefghij");

        assertEquals(List.of("abcd", "defg", "ghij"), first);
        assertEquals(first, second);
        assertEquals("d", first.get(0).substring(3));
        assertEquals("d", first.get(1).substring(0, 1));
    }

    @Test
    void emptyInputProducesNoMeaninglessChunk() {
        TextSplitter splitter = splitter(4, 0);

        assertEquals(List.of(), splitter.split(null));
        assertEquals(List.of(), splitter.split(" \n\t"));
    }

    @Test
    void rejectsInvalidSizeAndOverlapBoundaries() {
        assertThrows(IllegalArgumentException.class, () -> new TextSplitterConfig(0, 0));
        assertThrows(IllegalArgumentException.class, () -> new TextSplitterConfig(4, -1));
        assertThrows(IllegalArgumentException.class, () -> new TextSplitterConfig(4, 4));
        assertThrows(IllegalArgumentException.class, () -> new TextSplitterConfig(4, 5));
    }

    private TextSplitter splitter(int size, int overlap) {
        return new FixedSizeTextSplitter(new TextSplitterConfig(size, overlap));
    }
}
