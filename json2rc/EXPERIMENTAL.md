# Experimental JSON operations

Three EXPERIMENTAL additions, compiled by this json2rc and rendered by the rcX C++ player
(`remotecompose-experiments/players/cpp/docs/EXPERIMENTAL_OPS.md` has the wire formats). Their
names carry an `x` prefix; other players ignore them. Origin: `Emoji/CONVERT.md` §18–20.

## Compact path resources — `"encoding": "xcompact"`

```json
{"resources": {"paths": [
  {"outline": {"value": [{"type": "moveTo", "x": 10, "y": 10},
                         {"type": "cubicTo", "x1": 30, "y1": 0, "x2": 60, "y2": 20, "x3": 80, "y3": 10},
                         {"type": "close"}],
               "encoding": "xcompact", "quantum": 0.0625, "winding": "evenOdd"}}]}}
```

Add `"delta": true` (best with `"quantum": 0.125`) for the v2 form: int8 deltas from the previous
point with an int16 escape, another third off the coordinates on blob-like paths.

Same path, a third of the bytes: one byte per verb, no repeated current point, 16-bit
fixed-point coordinates at `quantum` pixels per unit (default 1/16 px; the writer falls back to
float coordinates when a coordinate does not fit in 16 bits, and to a standard path when the
path holds conics or variable coordinates). Everything that takes a path (`drawPath`,
`clipPath`, `xDrawPathStrip`, ...) accepts it.

## Paint blur — `"xBlur"`

```json
{"paint": {"ops": [{"style": "fill"}, {"color": "#C08040"}, {"xBlur": 1.5}]}}
```

A Gaussian blur of the drawn mask, sigma in pixels, on this paint only; `{"xBlur": 0}` clears
it. Use it for edges that are soft in the source (a shadow, a surface turning away from the
light) while the rest of the drawing stays crisp.

## Compact gradients — `"xcompact": true` on a gradient op

```json
{"radialGradient": {"centerX": 108, "centerY": 106, "radius": 96, "colors": [...], "stops": [...], "xcompact": true}}
```

The same gradient (radial, linear or sweep) in half the bytes: stop positions in 1/255, colours
as RGB with the alphas packed separately only when any stop is translucent, geometry in 1/16 px.
Falls back to the standard form when a colour is a variable, there are more than 255 stops or a
coordinate is beyond ±2047 px.

## Variable-width strokes — `"xDrawPathStrip"`

```json
{"xDrawPathStrip": {"path": "@paths.rib", "diameters": [1.0, 3.5, 3.0, 1.2]}}
```

Fills the ribbon along the path with the current paint, the diameter interpolated along the
arc length: one value per anchor point of the path (moveTo plus one per segment), or one value
for all, or any count resampled uniformly. `"widths"` is accepted as a synonym, `"diameter"` for
a single value. The compiler encodes the list compactly — one byte per anchor at most, and only
the anchors that differ from the line's default width (or the keyframes of a taper) within
0.25 px — so a flat line costs 8 bytes and a typical fitted profile 10–14; see the player's
`docs/EXPERIMENTAL_OPS.md` for the wire form.
