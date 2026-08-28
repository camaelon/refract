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
import androidx.compose.remote.core.RemotePathBase;

import java.awt.Graphics2D;
import java.awt.RenderingHints;
import java.awt.image.BufferedImage;
import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.IOException;
import java.net.URI;
import java.util.HashMap;
import java.util.Map;

import javax.imageio.ImageIO;

/**
 * Platform services for the desktop converter. The only interesting part is image
 * loading: the RemoteCompose "image" object we pass in is a path or URI string; this
 * loads it, re-encodes it as PNG, and hands the bytes to the writer so they get
 * embedded inline in the .rc document (the C++ viewer only renders inline images).
 */
final class JvmImagePlatform implements RcPlatformServices {

    /** Cap the embedded image dimension: keeps .rc size sane and avoids short overflow. */
    private static final int MAX_DIM = 2048;

    private static final class Loaded {
        byte[] png;
        int width;
        int height;
    }

    private final Map<String, Loaded> cache = new HashMap<>();

    private Loaded load(Object image) {
        String ref = String.valueOf(image);
        Loaded hit = cache.get(ref);
        if (hit != null) {
            return hit;
        }
        try {
            BufferedImage src = read(ref);
            if (src == null) {
                throw new IOException("unsupported or missing image");
            }
            BufferedImage img = downscale(src);
            ByteArrayOutputStream out = new ByteArrayOutputStream();
            ImageIO.write(img, "png", out);
            Loaded loaded = new Loaded();
            loaded.png = out.toByteArray();
            loaded.width = img.getWidth();
            loaded.height = img.getHeight();
            cache.put(ref, loaded);
            return loaded;
        } catch (IOException e) {
            throw new RuntimeException("image load failed for '" + ref + "': " + e.getMessage(), e);
        }
    }

    private static BufferedImage read(String ref) throws IOException {
        if (ref.contains("://")) {
            return ImageIO.read(URI.create(ref).toURL());
        }
        return ImageIO.read(new File(ref));
    }

    private static BufferedImage downscale(BufferedImage src) {
        int w = src.getWidth();
        int h = src.getHeight();
        int max = Math.max(w, h);
        if (max <= MAX_DIM) {
            return src;
        }
        double scale = (double) MAX_DIM / max;
        int nw = Math.max(1, (int) Math.round(w * scale));
        int nh = Math.max(1, (int) Math.round(h * scale));
        BufferedImage dst = new BufferedImage(nw, nh, BufferedImage.TYPE_INT_ARGB);
        Graphics2D g = dst.createGraphics();
        g.setRenderingHint(RenderingHints.KEY_INTERPOLATION,
                RenderingHints.VALUE_INTERPOLATION_BILINEAR);
        g.drawImage(src, 0, 0, nw, nh, null);
        g.dispose();
        return dst;
    }

    @Override
    public byte[] imageToByteArray(Object image) {
        return load(image).png;
    }

    @Override
    public int getImageWidth(Object image) {
        return load(image).width;
    }

    @Override
    public int getImageHeight(Object image) {
        return load(image).height;
    }

    @Override
    public boolean isAlpha8Image(Object image) {
        return false;
    }

    @Override
    public float[] pathToFloatArray(Object path) {
        return (path instanceof RemotePathBase) ? ((RemotePathBase) path).getPath() : new float[0];
    }

    @Override
    public Object parsePath(String pathData) {
        return new RemotePathBase(pathData);
    }

    @Override
    public void log(LogCategory category, String message) {}
}
