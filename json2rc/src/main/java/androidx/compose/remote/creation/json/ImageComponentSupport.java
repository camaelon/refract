/*
 * Copyright 2026 refract
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *      http://www.apache.org/licenses/LICENSE-2.0
 */
package androidx.compose.remote.creation.json;

/**
 * Registers an {@code "image"} component on a {@link RemoteComposeJsonParser}:
 *
 * <pre>{ "type": "image", "src": "/path/or/uri", "contentScale": "fit", "alpha": 1.0,
 *        "modifiers": ["fillMaxWidth"] }</pre>
 *
 * <p>This lives in the {@code ...creation.json} package (but in refract's own source tree,
 * not the mirrored androidx checkout) because {@code JsonComponentParser} is package-private.
 * The {@code src} value is handed to {@code addBitmap}, which routes through the platform's
 * {@code imageToByteArray} to embed the decoded pixels inline in the document.
 */
public final class ImageComponentSupport {

    public static void register(RemoteComposeJsonParser parser) {
        parser.registerComponentParser("image", (component, modifier, writer, p) -> {
            int imageId = writer.addBitmap(component.get("src"));
            int scaleType = scaleType(component.optString("contentScale", "fit"));
            float alpha = (float) component.optDouble("alpha", 1.0);
            writer.image(modifier, imageId, scaleType, alpha);
        });
    }

    /** Maps a friendly content-scale name to the core ImageScaling constant. */
    private static int scaleType(String name) {
        switch (name.toLowerCase()) {
            case "none": return 0;
            case "inside": return 1;
            case "fillwidth": return 2;
            case "fillheight": return 3;
            case "fit": return 4;
            case "crop": return 5;
            case "fill":
            case "fillbounds": return 6;
            default: return 4;
        }
    }

    private ImageComponentSupport() {}
}
