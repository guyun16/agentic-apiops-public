package com.apiops.rag.parser;

import java.nio.ByteBuffer;
import java.nio.charset.CharacterCodingException;
import java.nio.charset.CodingErrorAction;
import java.nio.charset.StandardCharsets;
import java.util.Locale;
import java.util.Set;

/** Strict UTF-8 parser for the currently approved text and Markdown path. */
public final class PlainTextDocumentParser implements DocumentParser {

    private static final Set<String> SUPPORTED_MEDIA_TYPES = Set.of(
            "text/plain", "text/markdown");

    @Override
    public String parse(String fileName, String mediaType, byte[] content) {
        if (!SUPPORTED_MEDIA_TYPES.contains(normalizeMediaType(mediaType))) {
            throw new DocumentParseException(
                    DocumentParseError.UNSUPPORTED_MEDIA_TYPE,
                    "Unsupported document media type");
        }
        if (content == null || content.length == 0) {
            throw new DocumentParseException(
                    DocumentParseError.EMPTY_DOCUMENT, "Document is empty");
        }

        String text;
        try {
            text = StandardCharsets.UTF_8.newDecoder()
                    .onMalformedInput(CodingErrorAction.REPORT)
                    .onUnmappableCharacter(CodingErrorAction.REPORT)
                    .decode(ByteBuffer.wrap(content))
                    .toString();
        } catch (CharacterCodingException exception) {
            throw new DocumentParseException(
                    DocumentParseError.INVALID_ENCODING,
                    "Document is not valid UTF-8", exception);
        }

        if (text.startsWith("\uFEFF")) {
            text = text.substring(1);
        }
        String normalized = text.replace("\r\n", "\n").replace('\r', '\n').strip();
        if (normalized.isEmpty()) {
            throw new DocumentParseException(
                    DocumentParseError.EMPTY_DOCUMENT, "Document contains no text");
        }
        return normalized;
    }

    private String normalizeMediaType(String mediaType) {
        if (mediaType == null) {
            return "";
        }
        int parameters = mediaType.indexOf(';');
        String value = parameters < 0 ? mediaType : mediaType.substring(0, parameters);
        return value.trim().toLowerCase(Locale.ROOT);
    }
}
