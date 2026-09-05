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
        String key = ref.length() > 512 ? ref.length() + ":" + ref.substring(0, 256).hashCode()
                                        + ":" + ref.substring(ref.length() - 256).hashCode() : ref;
        Loaded hit = cache.get(key);
        if (hit != null) {
            return hit;
        }
        try {
            // If the source is already a compressed image the player can decode, embed its bytes
            // verbatim -- re-encoding a JPEG as PNG threw away the whole point of a lossy layer
            // (a 2.2 KB JPEG became a 20 KB document).
            byte[] raw = rawBytes(ref);
            if (raw != null) {
                BufferedImage probe = ImageIO.read(new java.io.ByteArrayInputStream(raw));
                if (probe != null && Math.max(probe.getWidth(), probe.getHeight()) <= MAX_DIM) {
                    Loaded direct = new Loaded();
                    direct.png = raw;
                    direct.width = probe.getWidth();
                    direct.height = probe.getHeight();
                    cache.put(key, direct);
                    return direct;
                }
            }
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
            cache.put(key, loaded);
            return loaded;
        } catch (IOException e) {
            throw new RuntimeException("image load failed for '" + ref + "': " + e.getMessage(), e);
        }
    }

    /** Raw bytes of an already-compressed source (PNG or JPEG), or null if it is neither. */
    private static byte[] rawBytes(String ref) throws IOException {
        byte[] b;
        if (ref.startsWith("data:")) {
            int comma = ref.indexOf(',');
            if (comma < 0) return null;
            b = java.util.Base64.getMimeDecoder().decode(ref.substring(comma + 1));
        } else if (ref.contains("://")) {
            return null;
        } else {
            File f = new File(ref);
            if (!f.isFile()) return null;
            b = java.nio.file.Files.readAllBytes(f.toPath());
        }
        if (b.length > 8 && (b[0] & 0xFF) == 0x89 && b[1] == 'P' && b[2] == 'N' && b[3] == 'G') return b;
        if (b.length > 3 && (b[0] & 0xFF) == 0xFF && (b[1] & 0xFF) == 0xD8) return b;   // JPEG SOI
        return null;
    }

    private static BufferedImage read(String ref) throws IOException {
        // data:<mime>;base64,<payload> (or a bare base64 blob) lets a document carry its own
        // pixels without depending on a file next to it.
        if (ref.startsWith("data:")) {
            int comma = ref.indexOf(',');
            if (comma < 0) throw new IOException("malformed data URI");
            return decodeBase64(ref.substring(comma + 1));
        }
        if (ref.length() > 256 && ref.matches("[A-Za-z0-9+/=\\s]+")) {
            return decodeBase64(ref);
        }
        if (ref.contains("://")) {
            return ImageIO.read(URI.create(ref).toURL());
        }
        return ImageIO.read(new File(ref));
    }

    private static BufferedImage decodeBase64(String payload) throws IOException {
        byte[] raw = java.util.Base64.getMimeDecoder().decode(payload);
        return ImageIO.read(new java.io.ByteArrayInputStream(raw));
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
        // getPath() returns RemotePathBase's raw growable buffer (padded to 1024 floats), and the
        // json PathParser is not a RemotePathBase at all -- it only implements RcPathArrayCreator,
        // so named string paths used to serialize as an empty path. createFloatArray() returns the
        // trimmed data for both.
        if (path instanceof RcPlatformServices.RcPathArrayCreator) {
            return ((RcPlatformServices.RcPathArrayCreator) path).createFloatArray();
        }
        return (path instanceof RemotePathBase) ? ((RemotePathBase) path).getPath() : new float[0];
    }

    @Override
    public Object parsePath(String pathData) {
        return new RemotePathBase(pathData);
    }

    @Override
    public void log(LogCategory category, String message) {}
}
