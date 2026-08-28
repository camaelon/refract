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

import androidx.compose.remote.core.RcPlatformServices;
import androidx.compose.remote.creation.RemoteComposeWriter;
import androidx.compose.remote.creation.json.ImageComponentSupport;
import androidx.compose.remote.creation.json.RemoteComposeJsonParser;

import org.json.JSONArray;
import org.json.JSONObject;

import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Arrays;
import java.util.LinkedHashSet;
import java.util.Set;

/**
 * Minimal command-line converter: reads RemoteCompose JSON documents and writes the
 * binary {@code .rc} form using the real androidx {@code RemoteComposeJsonParser}.
 *
 * <p>On top of the stock parser it registers an {@code "image"} component that loads an
 * image from a path/URI and embeds it inline in the document (see {@link JvmImagePlatform}).
 *
 * <p>Usage: {@code json2rc in1.json out1.rc [in2.json out2.rc ...]}
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
                byte[] bytes = convert(Files.readString(in));
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

    /** Convert one RemoteCompose JSON document to binary .rc bytes. */
    static byte[] convert(String json) throws Exception {
        RcPlatformServices platform = new JvmImagePlatform();

        // Mirrors RemoteComposeJsonParser.parse(json, platform), but on a writer/parser we
        // own so we can register the extra "image" component before parsing.
        JSONObject header = new JSONObject(json).optJSONObject("header");
        int apiLevel = header != null ? header.optInt("apiLevel", 7) : 7;
        RemoteComposeWriter.HTag[] tags = RemoteComposeJsonParser.parseHeaderOnly(json);
        Arrays.sort(tags, (a, b) -> Short.compare(a.getTag(), b.getTag()));

        RemoteComposeWriter writer = new RemoteComposeWriter(platform, apiLevel, tags);
        RemoteComposeJsonParser parser = new RemoteComposeJsonParser(writer);
        ImageComponentSupport.register(parser);

        // Make image files available to the parser:
        //  - "image" components (src) are hoisted before root so DATA_BITMAP precedes
        //    the layout that references it.
        //  - canvas "addbitmap" commands reference a bitmap by name; register each
        //    name so the platform loads it from that path.
        Set<String> imageSrcs = new LinkedHashSet<>();
        Set<String> bitmapNames = new LinkedHashSet<>();
        collect(new JSONObject(json), imageSrcs, bitmapNames);
        for (String name : bitmapNames) {
            parser.defineBitmap(name, name);
        }
        for (String src : imageSrcs) {
            writer.addBitmap(src);
        }

        parser.parse(json);
        return writer.encodeToByteArray();
    }

    /** Depth-first scan for {@code "image"} component srcs and {@code addbitmap} names. */
    private static void collect(Object node, Set<String> imageSrcs, Set<String> bitmapNames) {
        if (node instanceof JSONObject) {
            JSONObject obj = (JSONObject) node;
            String type = obj.optString("type");
            if ("image".equalsIgnoreCase(type) && obj.has("src")) {
                imageSrcs.add(obj.optString("src"));
            } else if ("addbitmap".equalsIgnoreCase(type) && obj.has("image")) {
                bitmapNames.add(obj.optString("image"));
            }
            for (String key : obj.keySet()) {
                collect(obj.get(key), imageSrcs, bitmapNames);
            }
        } else if (node instanceof JSONArray) {
            JSONArray arr = (JSONArray) node;
            for (int i = 0; i < arr.length(); i++) {
                collect(arr.get(i), imageSrcs, bitmapNames);
            }
        }
    }

    private Main() {}
}
