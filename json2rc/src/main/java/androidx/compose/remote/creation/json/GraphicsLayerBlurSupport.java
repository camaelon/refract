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

import androidx.compose.remote.creation.modifiers.GraphicsLayerModifier;

import org.json.JSONObject;

import java.util.Iterator;

/**
 * Re-registers the {@code "graphicslayer"} modifier parser with support for the blur
 * render effect (Android {@code RenderEffect.createBlurEffect}), which the stock parser
 * doesn't expose:
 *
 * <pre>{ "graphicsLayer": { "blur": 12 } }        // radius, both axes
 *        { "graphicsLayer": { "blurX": 8, "blurY": 4 } }</pre>
 *
 * <p>Lives in the {@code ...creation.json} package so it can call the package-private
 * {@code parseFloat} (which resolves {@code $var} expressions). Register it after the
 * defaults; {@code registerModifierParser} overwrites by key, so this wins.
 */
public final class GraphicsLayerBlurSupport {

    public static void register(RemoteComposeJsonParser parser) {
        parser.registerModifierParser("graphicslayer", (mod, key, recordingModifier, p) -> {
            JSONObject gObj = mod.getJSONObject(key);
            GraphicsLayerModifier gMod = new GraphicsLayerModifier();
            Iterator<String> keys = gObj.keys();
            while (keys.hasNext()) {
                String k = keys.next();
                int attrId = -1;
                switch (k.toLowerCase()) {
                    case "scalex": attrId = 0; break;
                    case "scaley": attrId = 1; break;
                    case "rotationz": attrId = 4; break;
                    case "translationx": attrId = 7; break;
                    case "translationy": attrId = 8; break;
                    case "alpha": attrId = 11; break;
                    case "blurx": attrId = 17; break;
                    case "blury": attrId = 18; break;
                    case "blur": {                       // radius on both axes
                        float rad = p.parseFloat(gObj.get(k));
                        gMod.setFloatAttribute(17, rad);
                        gMod.setFloatAttribute(18, rad);
                        break;
                    }
                    default: break;
                }
                if (attrId != -1) {
                    gMod.setFloatAttribute(attrId, p.parseFloat(gObj.get(k)));
                }
            }
            recordingModifier.then(gMod);
        });
    }

    private GraphicsLayerBlurSupport() {}
}
