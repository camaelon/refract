/*
 * Copyright 2026 refract
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *      http://www.apache.org/licenses/LICENSE-2.0
 */
package refract.json2rc;

import androidx.compose.remote.creation.json.RemoteComposeJsonParser;

import java.nio.ByteBuffer;
import java.nio.file.Files;
import java.nio.file.Path;

/**
 * Minimal command-line converter: reads RemoteCompose JSON documents and writes
 * the binary {@code .rc} form using the real androidx {@code RemoteComposeJsonParser}.
 *
 * <p>Usage: {@code json2rc in1.json out1.rc [in2.json out2.rc ...]}
 *
 * <p>Multiple pairs are accepted so a whole deck converts in one JVM launch.
 */
public final class Main {

    public static void main(String[] args) throws Exception {
        if (args.length < 2 || args.length % 2 != 0) {
            System.err.println("Usage: json2rc <in.json> <out.rc> [<in.json> <out.rc> ...]");
            System.exit(2);
            return;
        }

        int failures = 0;
        for (int i = 0; i < args.length; i += 2) {
            Path in = Path.of(args[i]);
            Path out = Path.of(args[i + 1]);
            try {
                String json = Files.readString(in);
                ByteBuffer buffer = RemoteComposeJsonParser.parseToByteBuffer(json);
                byte[] bytes = new byte[buffer.remaining()];
                buffer.get(bytes);
                Files.write(out, bytes);
                System.err.println("wrote " + out + " (" + bytes.length + " bytes)");
            } catch (Exception e) {
                failures++;
                System.err.println("FAILED " + in + ": " + e.getMessage());
            }
        }
        if (failures > 0) {
            System.exit(1);
        }
    }

    private Main() {}
}
