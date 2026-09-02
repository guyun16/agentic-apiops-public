package com.apiops.rag.parser;

/** Converts a supported source document into deterministic normalized text. */
public interface DocumentParser {

    String parse(String fileName, String mediaType, byte[] content);
}
