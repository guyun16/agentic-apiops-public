package com.apiops.tool.gateway;

import java.io.BufferedReader;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Instant;
import java.time.format.DateTimeParseException;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Objects;

/** Controlled-root file implementation behind logical service mappings. */
public final class FileLogSource implements LogSource {
    private final Path root;
    private final Map<String, Path> files;

    public FileLogSource(Path root, Map<String, Path> serviceFiles) throws IOException {
        this.root = Objects.requireNonNull(root).toAbsolutePath().normalize().toRealPath();
        Objects.requireNonNull(serviceFiles);
        Map<String, Path> normalized = new LinkedHashMap<>();
        for (Map.Entry<String, Path> entry : serviceFiles.entrySet()) {
            String service = entry.getKey().trim().toLowerCase(Locale.ROOT);
            Path candidate = this.root.resolve(Objects.requireNonNull(entry.getValue()))
                    .toAbsolutePath().normalize();
            if (service.isBlank() || !candidate.startsWith(this.root)) {
                throw new IllegalArgumentException("log mapping escapes the controlled root");
            }
            normalized.put(service, candidate);
        }
        this.files = Map.copyOf(normalized);
    }

    @Override
    public List<String> search(String logicalService, String query, Instant from, Instant to,
                               int maxLines) throws IOException {
        Path configured = files.get(logicalService.toLowerCase(Locale.ROOT));
        if (configured == null) throw new IllegalArgumentException("unknown logical service");
        Path realFile = configured.toRealPath();
        if (!realFile.startsWith(root) || !Files.isRegularFile(realFile)) {
            throw new SecurityException("log file escapes the controlled root");
        }
        String needle = query.toLowerCase(Locale.ROOT);
        List<String> lines = new ArrayList<>();
        try (BufferedReader reader = Files.newBufferedReader(realFile, StandardCharsets.UTF_8)) {
            String line;
            while (lines.size() < maxLines && (line = reader.readLine()) != null) {
                if (Thread.currentThread().isInterrupted()) {
                    throw new IOException("log search interrupted");
                }
                if (line.toLowerCase(Locale.ROOT).contains(needle) && within(line, from, to)) {
                    lines.add(line);
                }
            }
        }
        return List.copyOf(lines);
    }

    private static boolean within(String line, Instant from, Instant to) {
        int separator = line.indexOf(' ');
        if (separator <= 0) return true;
        try {
            Instant timestamp = Instant.parse(line.substring(0, separator));
            return !timestamp.isBefore(from) && !timestamp.isAfter(to);
        } catch (DateTimeParseException exception) {
            return true;
        }
    }
}
