package com.apiops.rag.splitter;

import java.util.List;

public interface TextSplitter {

    List<String> split(String text);
}
