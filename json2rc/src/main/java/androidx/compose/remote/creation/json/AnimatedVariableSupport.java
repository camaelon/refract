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

import androidx.compose.remote.core.operations.utilities.AnimatedFloatExpression;
import androidx.compose.remote.core.operations.utilities.easing.Easing;
import androidx.compose.remote.core.operations.utilities.easing.FloatAnimation;

import org.json.JSONArray;
import org.json.JSONObject;

import java.util.List;

/**
 * An {@code "animatedVariable"} component: a float variable whose every change is animated
 * with a chosen easing — what the stock parser's {@code {"value": …, "anim": seconds}} does,
 * but with the easing, a spline, an initial value and wrap available:
 *
 * <pre>{ "type": "animatedVariable", "name": "A3", "value": "floor(continuousSec()/4)%2*40-20",
 *   "duration": 2.4, "easing": "overshoot" }
 * { …, "easing": "cubic", "spline": [0, 1, 0, 1] }          // cubic-bezier control points
 * { …, "easing": "spline", "spline": [0, 0.25, 0.5, 1] }    // a monotone spline through values</pre>
 *
 * <p>Easing names: standard, accelerate, decelerate, linear, anticipate, overshoot, bounce,
 * elastic, cubic, spline — or the {@code Easing} constant as a number.
 */
public final class AnimatedVariableSupport {

    public static void register(RemoteComposeJsonParser parser) {
        parser.registerComponentParser("animatedvariable", (component, modifier, writer, p) -> {
            String name = component.getString("name");
            if (!p.isInFirstPass() && p.mVariables.containsKey(name)) return;
            List<Object> rpn = p.getExpressionParser().infixToRpn(component.get("value").toString());
            float[] ops = new float[rpn.size()];
            for (int i = 0; i < ops.length; i++) {
                Object o = rpn.get(i);
                if (o instanceof Float) ops[i] = (Float) o;
                else if (o instanceof Integer) ops[i] = AnimatedFloatExpression.asNan((Integer) o);
            }
            float duration = (float) component.optDouble("duration", 1.0);
            int type = easing(component.opt("easing"));
            float[] spec = null;
            JSONArray s = component.optJSONArray("spline");
            if (s != null) {
                spec = new float[s.length()];
                for (int i = 0; i < spec.length; i++) spec[i] = (float) s.getDouble(i);
            }
            float initial = component.has("initial") ? (float) component.getDouble("initial") : Float.NaN;
            float wrap = component.has("wrap") ? (float) component.getDouble("wrap") : Float.NaN;
            float id = writer.floatExpression(ops,
                    FloatAnimation.packToFloatArray(duration, type, spec, initial, wrap));
            p.mVariables.put(name, id);
        });
    }

    private static int easing(Object e) {
        if (e instanceof Number) return ((Number) e).intValue();
        if (e == null) return Easing.CUBIC_STANDARD;
        switch (e.toString().toLowerCase()) {
            case "accelerate": return Easing.CUBIC_ACCELERATE;
            case "decelerate": return Easing.CUBIC_DECELERATE;
            case "linear": return Easing.CUBIC_LINEAR;
            case "anticipate": return Easing.CUBIC_ANTICIPATE;
            case "overshoot": return Easing.CUBIC_OVERSHOOT;
            case "bounce": return Easing.EASE_OUT_BOUNCE;
            case "elastic": return Easing.EASE_OUT_ELASTIC;
            case "cubic": return Easing.CUBIC_CUSTOM;
            case "spline": return Easing.SPLINE_CUSTOM;
            default: return Easing.CUBIC_STANDARD;
        }
    }
}
