package com.apiops.rag.parser;

import org.junit.jupiter.api.Test;

import java.nio.charset.StandardCharsets;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;

class PlainTextDocumentParserTest {

    private final PlainTextDocumentParser parser = new PlainTextDocumentParser();

    @Test
    void parsesUtf8MarkdownAndNormalizesLineEndings() {
        String result = parser.parse(
                "runbook.md", "text/markdown; charset=UTF-8",
                "# Orders\r\n\r\nRetry safely.\r\n".getBytes(StandardCharsets.UTF_8));

        assertEquals("# Orders\n\nRetry safely.", result);
    }

    @Test
    void rejectsEmptyAndWhitespaceOnlyDocuments() {
        assertEquals(DocumentParseError.EMPTY_DOCUMENT,
                assertThrows(DocumentParseException.class,
                        () -> parser.parse("empty.txt", "text/plain", new byte[0]))
                        .error());
        assertEquals(DocumentParseError.EMPTY_DOCUMENT,
                assertThrows(DocumentParseException.class,
                        () -> parser.parse(
                                "blank.md", "text/markdown",
                                " \n\t".getBytes(StandardCharsets.UTF_8)))
                        .error());
    }

    @Test
    void rejectsUnsupportedMediaTypeAndInvalidUtf8() {
        assertEquals(DocumentParseError.UNSUPPORTED_MEDIA_TYPE,
                assertThrows(DocumentParseException.class,
                        () -> parser.parse("guide.pdf", "application/pdf", new byte[]{1}))
                        .error());
        assertEquals(DocumentParseError.INVALID_ENCODING,
                assertThrows(DocumentParseException.class,
                        () -> parser.parse(
                                "broken.txt", "text/plain",
                                new byte[]{(byte) 0xC3, (byte) 0x28}))
                        .error());
    }
}
