"""RemoteComposeJsonParser — byte-identical port (layout + text).

Mirrors remote-creation-core/.../json/RemoteComposeJsonParser.java +
DefaultComponentParsers + DefaultModifierParsers.

Implemented: header, root, column/row/box containers, text (CoreText path),
modifiers fillMaxSize/fillMaxWidth/fillMaxHeight/width/height/size/background/padding.
Not yet: canvas/draw ops, expressions, paths, macros, resources/variables.
"""

from __future__ import annotations

import math as _math
import struct as _struct
import re as _re

import math

from . import header as _header
from . import writer as W
from .expr import ExpressionError, ExpressionParser
from .writer import RemoteComposeWriter

_F32_MAX = 3.4028234663852886e38  # Float.MAX_VALUE

# DimensionModifierOperation.Type ordinals: EXACT=0, FILL=1, WRAP=2, WEIGHT=3, ...
TYPE_EXACT = 0
TYPE_FILL = 1
TYPE_WRAP = 2
TYPE_WEIGHT = 3

_INT_MAX = 2147483647


class NotImplementedComponent(Exception):
    """Raised for a JSON construct the converter does not yet emit."""


def _to_int32(v: int) -> int:
    v &= 0xFFFFFFFF
    return v - 0x100000000 if v >= 0x80000000 else v


def _is_nan_bits(bits: int) -> bool:
    b = bits & 0xFFFFFFFF
    return (b & 0x7F800000) == 0x7F800000 and (b & 0x7FFFFF) != 0


def _int_bits_to_float(bits: int) -> float:
    import struct
    return struct.unpack(">f", struct.pack(">I", bits & 0xFFFFFFFF))[0]


# ── value parsing (mirror RemoteComposeJsonParser) ───────────────────────────

def _is_float_nan_bits(bits: int) -> bool:
    """True if float32 `bits` encode a NaN (exponent all ones, mantissa nonzero) —
    which is exactly how remote expression/reference ids are encoded. Used to mirror
    the official parser's `!Float.isNaN(...)` guard on textFromFloat values."""
    return (bits & 0x7F800000) == 0x7F800000 and (bits & 0x007FFFFF) != 0


def parse_float(value) -> float:
    if value is None:
        return float("nan")
    if isinstance(value, bool):
        return float(int(value))
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        if value == "NaN":
            return float("nan")
        if value == "Infinity":
            return float("inf")
        if value == "-Infinity":
            return float("-inf")
        if value == "max":
            return 3.4028234663852886e38  # Float.MAX_VALUE
        raise NotImplementedComponent(f"parse_float: unsupported string {value!r} (variables/exprs TBD)")
    raise NotImplementedComponent(f"parse_float: unsupported {type(value)}")


def parse_color(value) -> int:
    if value is None:
        return 0
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        return _to_int32(int(value))
    if isinstance(value, str):
        if value.startswith("$colors.") or value.startswith("@colors.") or value.startswith("$") or value.startswith("@"):
            raise NotImplementedComponent(f"color reference {value!r} (resources/variables TBD)")
        hexs = value[1:] if value.startswith("#") else value
        v = int(hexs, 16)
        if len(value) <= 7:
            v |= 0xFF000000
        return _to_int32(v)
    raise NotImplementedComponent(f"parse_color: unsupported {type(value)}")


def parse_h_align(align: str) -> int:
    return {"start": 1, "center": 2, "end": 3, "spacebetween": 6,
            "spaceevenly": 7, "spacearound": 8}.get(align.lower(), 1)


def parse_v_align(align: str) -> int:
    return {"start": 1, "top": 4, "center": 2, "bottom": 5, "spacebetween": 6,
            "spaceevenly": 7, "spacearound": 8}.get(align.lower(), 4)


def parse_text_align(align: str) -> int:
    return {"left": 1, "1": 1, "right": 2, "2": 2, "center": 3, "3": 3,
            "justify": 4, "4": 4, "start": 5, "5": 5}.get(align.lower(), 5)


def _h_align(component: dict, default: str) -> int:
    return parse_h_align(str(component.get("horizontalAlignment", default)))


def _v_align(component: dict, default: str) -> int:
    return parse_v_align(str(component.get("verticalAlignment", default)))


_STYLE = {"fill": 0, "stroke": 1, "fillandstroke": 2}
_CAP = {"round": 1, "square": 2}    # else -> butt(0)
_JOIN = {"round": 1, "bevel": 2}    # else -> miter(0)

# Direct-key paint setters, in the FIXED source order of parseCommand's `else` branch.
# Order is load-bearing: it is the order the PaintBundle ints come out in.
# NOTE `linearGradient`, `pathEffect` and `alpha` are deliberately absent — the current
# parser only honours those inside the `ops` array, and silently ignores them as direct
# keys. Mirroring that (rather than "fixing" it) is what keeps us byte-identical.
_PAINT_KEYS_ORDER = ["shader", "color", "strokeJoin", "strokeCap", "style", "width",
                     "textSize", "sweepGradient"]

# Keys accepted as direct paint properties but ignored by the current parser. Tracked so
# a document using them fails loudly here instead of silently losing the property.
_PAINT_KEYS_IGNORED = ("linearGradient", "pathEffect", "alpha")


def _normalize_command(command: dict) -> dict:
    if "type" not in command and len(command) == 1:
        key = next(iter(command))
        val = command[key]
        out: dict = {"type": key}
        if isinstance(val, list):
            out["commands"] = val
        elif isinstance(val, dict):
            out.update(val)
        elif key.lower() in ("drawpath", "pathappendclose"):
            out["path"] = val
        else:
            out["value"] = val
        return out
    return command


def _paint_setter(p, key: str, src: dict, ints: list[int]) -> None:
    """Append the PaintBundle ints for one paint property `key`, value at src[key]."""
    if key == "shader":
        ints += [W.PB_SHADER, int(src[key])]
    elif key == "color":
        c = src["color"]
        if isinstance(c, str) and (c.startswith("$colors.") or c.startswith("@colors.")):
            ints += [W.PB_COLOR_ID, p._color(c)]
        else:
            ints += [W.PB_COLOR, _to_int32(p._color(c))]   # literal hex or $var colorId
    elif key == "style":
        s = _STYLE.get(str(src["style"]).lower())
        if s is None:
            raise NotImplementedComponent(f"paint style {src['style']!r}")
        ints.append(W.PB_STYLE | (s << 16))
    elif key == "linearGradient":
        _gradient(p, src["linearGradient"], ints, sweep=False)
    elif key == "sweepGradient":
        _gradient(p, src["sweepGradient"], ints, sweep=True)
    elif key == "pathEffect":
        pe = src.get("pathEffect")
        if pe is None:
            ints.append(W.PB_PATH_EFFECT)
        else:
            # The payload is a *typed* PaintPathEffects record, not a bare interval
            # list: [DASH, phase, count, intervals...]. The player decodes it with
            # PaintPathEffects.parse(), which rejects anything untyped.
            phase = 0.0
            if isinstance(pe, dict):
                phase = float(pe.get("phase", 0.0))
                pe = pe["intervals"]
            data = [W.PPE_DASH, W.float_to_raw_int_bits(phase), len(pe)]
            data += [W.float_to_raw_int_bits(parse_float(x)) for x in pe]
            ints.append(W.PB_PATH_EFFECT | (len(data) << 16))
            ints += data
    elif key == "alpha":
        # p._fbits, not parse_float: upstream routes these through parser.parseFloat, so
        # an expression or a variable reference is legal wherever a number is.
        ints += [W.PB_ALPHA, p._fbits(src["alpha"])]
    elif key == "width":
        # `strokeWidth` is the preferred spelling and wins when both are present.
        v = src["strokeWidth"] if "strokeWidth" in src else src["width"]
        ints += [W.PB_STROKE_WIDTH, p._fbits(v)]
    elif key == "strokeCap":
        cap = _CAP.get(str(src["strokeCap"]).lower(), 0)
        ints.append(W.PB_STROKE_CAP | (cap << 16))
    elif key == "strokeJoin":
        join = _JOIN.get(str(src["strokeJoin"]).lower(), 0)
        ints.append(W.PB_STROKE_JOIN | (join << 16))
    elif key == "textSize":
        ints += [W.PB_TEXT_SIZE, p._fbits(src["textSize"])]
    elif key == "fontType":
        # Canvas text font family: "default"|"sans-serif"|"serif"|"monospace".
        # Encodes as TYPEFACE(tag=16, upper=weight|italic — 0 → default weight 400)
        # followed by the fontType int (PaintBundle reads it as arr[i++]).
        ft = {"default": W.FONT_TYPE_DEFAULT, "sans-serif": W.FONT_TYPE_SANS_SERIF,
              "sans": W.FONT_TYPE_SANS_SERIF, "serif": W.FONT_TYPE_SERIF,
              "monospace": W.FONT_TYPE_MONOSPACE, "mono": W.FONT_TYPE_MONOSPACE}
        v = ft.get(str(src["fontType"]).lower())
        if v is None:
            raise NotImplementedComponent(f"fontType {src['fontType']!r}")
        ints += [W.PB_TYPEFACE, v]
    else:
        raise NotImplementedComponent(f"paint key {key!r}")


def _gradient(p, g: dict, ints: list[int], sweep: bool) -> None:
    colors_arr = g["colors"]
    colors: list[int] = []
    id_mask = 0
    for i, c in enumerate(colors_arr):
        if isinstance(c, str) and (c.startswith("$colors.") or c.startswith("@colors.")):
            id_mask |= (1 << i)
        colors.append(_to_int32(p._color(c)) if isinstance(c, str) else _to_int32(parse_color(c)))
    stops = g.get("stops")
    n = len(colors)
    if sweep:
        ints.append(W.PB_GRADIENT | (W.GRAD_SWEEP << 16))
    else:
        ints.append(W.PB_GRADIENT | (W.GRAD_LINEAR << 16))
    ints.append(((id_mask << 16) | n) & 0xFFFFFFFF)
    ints += colors
    ints.append(len(stops) if stops else 0)
    if stops:
        ints += [W.float_to_raw_int_bits(float(s)) for s in stops]
    # Coordinates go through parseFloat on the Java side, so they accept expressions and
    # variable refs; `_fbits` both resolves them and emits any expression op, at the same
    # point in the stream as the reference does.
    if sweep:
        ints += [p._fbits(g["centerX"]), p._fbits(g["centerY"])]
    else:
        ints += [p._fbits(g.get("x1", 0.0)), p._fbits(g.get("y1", 0.0)),
                 p._fbits(g.get("x2", 0.0)), p._fbits(g.get("y2", 0.0)),
                 int(g.get("tileMode", 0)) if isinstance(g.get("tileMode", 0), int) else 0]


# Direct paint keys the parser recognises, mapped to their canonical setter name.
_PAINT_KEY_ALIASES = {"strokewidth": "width", "runtimeshader": "shader"}


def _build_paint_bundle(p, command: dict) -> list[int]:
    """PaintBundle ints for a `paint` command: `ops` array form, or direct keys in fixed order."""
    ints: list[int] = []
    if "ops" in command:
        # In `ops` form every key is honoured, in the order written. Aliases apply here
        # too — `strokeWidth` is the spelling documents actually use, and only the
        # direct-key form was resolving it.
        for op in command["ops"]:
            for key in op:
                _paint_setter(p, _PAINT_KEY_ALIASES.get(key.lower(), key), op, ints)
        return ints

    for key in _PAINT_KEYS_IGNORED:
        if key in command:
            raise NotImplementedComponent(
                f"paint key {key!r} is ignored as a direct key by the current parser — "
                f"move it into an \"ops\" array")
    present = {_PAINT_KEY_ALIASES.get(k.lower(), k) for k in command}
    for key in _PAINT_KEYS_ORDER:
        if key in present:
            _paint_setter(p, key, command, ints)
    return ints


def normalize_component(component: dict) -> dict:
    if "type" not in component and len(component) == 1:
        key = next(iter(component))
        val = component[key]
        out: dict = {"type": key}
        if isinstance(val, list):
            out["children"] = val
        elif isinstance(val, dict):
            out.update(val)
        return out
    return component


# ── header (exact) ───────────────────────────────────────────────────────────

# ---- 3D command tables -----------------------------------------------------------------------

# Primitive type names. Spelled out rather than left as raw ints because the params are
# positional and type-dependent — a wrong number here produces a plausible-looking but wrong
# shape, which is much harder to spot than an error.
_PRIMITIVE = {
    "sphere": 0, "cylinder": 1, "cone": 2, "cube": 3, "roundedcube": 4,
    "sphericalsector": 5, "sphericaldome": 6, "tube": 7, "captube": 8, "profiletube": 9,
    "torus": 10, "plane": 11,
    "extrudecircle": 12, "extrudesector": 13, "extrudesegment": 14, "extrudearc": 15,
    "extruderoundedrect": 16, "extrudesquircle": 17, "extrudepath": 18,
    "lathe": 19, "sweep": 20, "helix": 21, "icosphere": 22,
}

# Named parameter order per primitive, so a document can say {"radius": 1, "center": [..]}
# instead of counting positions. Types absent from this table take a positional "params" list.
# `center` expands to three values wherever it appears.
_PRIMITIVE_PARAMS = {
    "sphere": ["radius", "center"],
    "cylinder": ["radius", "from", "to"],
    "cone": ["radius", "height", "center"],
    "cube": ["dimX", "dimY", "dimZ", "center"],
    "roundedcube": ["dimX", "dimY", "dimZ", "center", "cornerRadius"],
    "sphericalsector": ["radius", "angle", "center"],
    "sphericaldome": ["radius", "angle", "center"],
    "torus": ["majorRadius", "minorRadius", "center"],
    "plane": ["width", "height", "center"],
    "extrudecircle": ["radius", "depth", "center"],
    "extrudesector": ["radius", "startAngle", "sweepAngle", "depth", "center"],
    "extrudesegment": ["radius", "startAngle", "sweepAngle", "depth", "center"],
    "extrudearc": ["innerRadius", "outerRadius", "startAngle", "sweepAngle", "depth", "center"],
    "extruderoundedrect": ["width", "height", "cornerRadius", "depth", "center"],
    "extrudesquircle": ["radius", "exponent", "depth", "center"],
    "icosphere": ["radius", "center"],
    "lathe": ["center"],
    "helix": ["coilRadius", "tubeRadius", "pitch", "turns", "center"],
}

# Primitive flag bits (Primitive3D.FLAG_*).
_FLAG_SPLINE = 0x1
_FLAG_TUBE_LEGACY = 0x2
_FLAG_TUBE_PATH_DENSITY = 0x4
_FLAG_TUBE_CAP = 0x8


def _points(command, key, dim):
    """Flatten a list of dim-component points, rejecting a wrong arity loudly."""
    pts = command.get(key)
    if not pts:
        raise NotImplementedComponent(f"meshPrimitive3D: missing {key!r}")
    out = []
    for pt in pts:
        if len(pt) != dim:
            raise NotImplementedComponent(
                f"meshPrimitive3D: {key} entries need {dim} components, got {len(pt)}")
        out += list(pt)
    return out

# UV generation mode lives in flags bits 4-5.
_UV_MODE = {"none": 0, "uv": 1, "uv2": 2, "uv3": 3}


# MeshExpression surface families and the parameter each one needs.
# Vector-only opcodes, injected into the expression compiler for a vectorExpression and nowhere
# else — the scalar evaluator does not implement OFFSET+100.., so a `dot()` in an ordinary
# expression should fail at build time rather than produce a runtime "op not implemented".
_VECTOR_FUNCTIONS = {
    "vec2": 100, "vec3": 101, "vec4": 102,
    "dot": 103, "cross": 104, "length": 105, "lengthSq": 106, "normalize": 107,
}

_VECTOR_COMPONENTS = ("x", "y", "z", "w")

def _id_from_nan_bits(bits: int) -> int:
    """Inverse of as_nan_bits: recover the id a NaN-encoded float carries."""
    return bits & 0x007FFFFF


def _resolve_id(p, value) -> int:
    """Mirror RemoteComposeJsonParser.resolveTextId.

    An **integer is already an id** and is passed through untouched — `{"visibility": 2}`
    means the INVISIBLE constant, not a reference to variable 2. A float becomes a float
    constant and yields that constant's id. Anything else resolves as a reference.

    Treating the integer case as a reference produced a document that compiled and was
    wrong: the id was read out of the raw float bits of 2.0.
    """
    if isinstance(value, bool):
        raise NotImplementedComponent(f"expected an id, got boolean {value!r}")
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return _id_from_nan_bits(p.writer.add_float_constant(value))
    return _id_from_nan_bits(p._fbits(value))


_SURFACE = {"general": 0, "heightfield": 1, "sphere": 2, "cylinder": 3}

# TouchExpression stop modes. The numbers are the wire values; the names mirror
# TouchExpression.STOP_* so a document reads the way the engine source does.
_WAVEFORM = {"sine": 0, "square": 1, "sawtooth": 2, "triangle": 3}

_TOUCH_STOP = {
    "gently": 0, "instantly": 1, "ends": 2, "notcheseven": 3, "notchespercents": 4,
    "notchesabsolute": 5, "absolutepos": 6, "notchessingleeven": 7,
}

# VAR1/VAR2 are how the player feeds the grid coordinates into an expression. Binding them to
# the names `u` and `v` only while a mesh expression is being compiled keeps them out of every
# other expression's namespace, where they would shadow a document's own variables.
_VAR1_BITS = 0xFF800000 | (0x310000 + 70)
_VAR2_BITS = 0xFF800000 | (0x310000 + 71)


_PROJECTION = {"perspective": 0, "ortho": 1, "orthographic": 1}

_MATRIX_SUB = {"identity": 0, "translate": 1, "scale": 2, "rotate": 3, "multiply": 4}

_LIGHT_TYPE = {"directional": 0, "dir": 0, "point": 1}

# Render modes are (backend << 1) | smoothBit. The names are spelled out rather than left as
# bare integers because a document that asks for the wrong backend still draws — it silently
# falls back to software — so a typo would be invisible at author time.
_MESH_MODE = {
    "software-flat": 0, "software-smooth": 1,
    "canvas-flat": 2, "canvas-smooth": 3,
    "drawmesh-flat": 4, "drawmesh-smooth": 5,
    "gl-flat": 6, "gl-smooth": 7,
    "drawmesh-zbuf-flat": 8, "drawmesh-zbuf-smooth": 9,
    "canvas-zbuf-flat": 10, "canvas-zbuf-smooth": 11,
    # convenience aliases
    "flat": 0, "smooth": 1,
}

_MODE_WIREFRAME = 0x100
_WIRE_EDGE = (0x200, 0x400, 0x800)

# Paint3DState sub-commands.
_P3_CLEAR_DEPTH, _P3_MATERIAL, _P3_DEPTH_BIAS = 0, 1, 2


def _mesh_mode(command: dict) -> int:
    """Resolve `mode` plus the wireframe flags into the packed mode word."""
    raw = command.get("mode", "software-flat")
    if isinstance(raw, (int, float)) and not isinstance(raw, bool):
        mode = int(raw)
    else:
        key = str(raw).lower()
        if key not in _MESH_MODE:
            raise NotImplementedComponent(
                f"drawMesh3D mode {raw!r} (expected one of {sorted(_MESH_MODE)})")
        mode = _MESH_MODE[key]
    if command.get("wireframe"):
        mode |= _MODE_WIREFRAME
        for e in command.get("edges", []):
            if not 0 <= int(e) <= 2:
                raise NotImplementedComponent(f"drawMesh3D edge {e!r} (expected 0, 1 or 2)")
            mode |= _WIRE_EDGE[int(e)]
    return mode


def parse_api_level(doc: dict) -> int:
    h = doc.get("header")
    return int(h.get("apiLevel", 7)) if isinstance(h, dict) else 7


def parse_header_only(doc: dict) -> list[tuple[int, object]]:
    h = doc.get("header")
    if not isinstance(h, dict):
        return []
    tags: list[tuple[int, object]] = []
    for key, value in h.items():
        if key in ("apiLevel", "orderedResources"):
            continue
        if key not in _header.HEADER_KEY_TO_TAG:
            raise NotImplementedComponent(f"Unknown header tag: {key}")
        tags.append((_header.HEADER_KEY_TO_TAG[key], value))
    return tags


# ── modifiers ────────────────────────────────────────────────────────────────


def _parse_actions(p, raw) -> list:
    """Actions for a click modifier, as emit-thunks. Mirrors DefaultModifierParsers.parseActions:
    a single object is accepted as well as an array."""
    if raw is None:
        return []
    items = raw if isinstance(raw, list) else [raw]
    actions = []
    for a in items:
        if not isinstance(a, dict):
            raise NotImplementedComponent(f"action {a!r} (expected an object)")
        t = str(a.get("type", "")).lower()
        if t in ("hostnamedaction", "hostmetadataaction"):
            if "name" not in a:
                raise NotImplementedComponent(f"{t} without a name is not supported yet")
            name = str(a["name"])
            value = str(a["value"]) if "value" in a else None
            # HostAction(name) leaves both mType and mValueId at -1; STRING_TYPE is only
            # the default for actionType on the branch that carries a value.
            type_ = int(a.get("actionType", W.HOST_ACTION_STRING_TYPE)) if value is not None else -1

            # The text ids are allocated when the action is *written*, not when it is
            # parsed — HostAction.write() calls writer.addText() itself. Resolving them
            # here instead emits DATA_TEXT before the container op rather than after it,
            # which shifts every following id and changes the bytes.
            def emit(w, name=name, value=value, type_=type_):
                text_id = w.add_text(name)
                value_id = w.add_text(value) if value is not None else -1
                W.host_named_action(text_id, type_, value_id)(w)
            actions.append(emit)
        elif t == "valuefloatexpressionchange":
            target = a.get("targetId", a.get("target"))
            if target is None:
                raise NotImplementedComponent(
                    "valueFloatExpressionChange needs a \"target\"")
            target_id = _resolve_id(p, target)
            raw_value = a["value"] if "value" in a else a.get("expression")
            if raw_value is None:
                raise NotImplementedComponent(
                    "valueFloatExpressionChange needs a \"value\" or \"expression\"")
            # Compiled now, not inside the emit thunk: upstream calls parseFloat while
            # parsing the action, so the expression op lands *before* the click modifier.
            # Deferring it would put it after and shift every id that follows.
            value_id = _id_from_nan_bits(p._fbits(raw_value))
            actions.append(W.value_float_expression_change(target_id, value_id))
        elif t == "valuefloatchange":
            # The constant sibling: no expression op is emitted, the value is inline.
            target = a.get("targetId", a.get("target"))
            if target is None:
                raise NotImplementedComponent("valueFloatChange needs a \"target\"")
            actions.append(W.value_float_change(_resolve_id(p, target),
                                                p._fbits(a["value"])))
        elif t == "valueintegerchange":
            target = a.get("targetId", a.get("target"))
            if target is None:
                raise NotImplementedComponent("valueIntegerChange needs a \"target\"")
            actions.append(W.value_integer_change(_resolve_id(p, target), int(a["value"])))
        elif t == "valuestringchange":
            target = a.get("targetId", a.get("target"))
            if target is None:
                raise NotImplementedComponent("valueStringChange needs a \"target\"")
            target_id = _resolve_id(p, target)
            value = a["value"]
            if isinstance(value, str) and not (value.startswith("@") or value.startswith("$")):
                # A literal string: ValueStringChange.write() calls addText itself, so the
                # DATA_TEXT lands *after* the container op. Resolving it here would put it
                # before and shift every id that follows — the same trap as host actions.
                def emit(w, target_id=target_id, value=value):
                    W.value_string_change(target_id, w.add_text(value))(w)
                actions.append(emit)
            else:
                actions.append(W.value_string_change(target_id, _resolve_id(p, value)))
        elif t == "valueintegerexpressionchange":
            # Literal ids only. The reference resolves the target through an integer
            # variable table and the value through an integer *expression* parser; rcj has
            # neither, and guessing would emit a document no reference run could confirm.
            target = a.get("targetId", a.get("target"))
            value = a["value"] if "value" in a else a.get("expression")
            if not isinstance(target, (int, float)) or not isinstance(value, (int, float)):
                raise NotImplementedComponent(
                    "valueIntegerExpressionChange with a named target or an expression "
                    "string needs integer-variable support, which rcj does not have; "
                    "only literal ids are accepted")
            actions.append(W.value_integer_expression_change(int(target), int(value)))
        else:
            raise NotImplementedComponent(f"click action type {t!r}")
    return actions

def parse_modifiers(p, modifiers) -> list:
    """Return a list of emit-thunks f(writer), in mList order. `p` is the parser (for _fbits).

    Dimension values (parseFloat in Java) are resolved to float32 BITS via p._fbits so they
    can be expressions; this also EMITS any expression ops here (before the layout op),
    matching the Java order (parseModifiers runs before the container start).
    """
    out: list = []
    if not modifiers:
        return out
    for item in modifiers:
        if isinstance(item, str):
            key, mod = item, {item: "NaN"}
        elif isinstance(item, dict):
            key = next(iter(item))
            mod = item
        else:
            raise NotImplementedComponent(f"modifier item {item!r}")
        _apply_modifier(p, out, key.lower(), key, mod)
    return out


def _num_bits(value) -> int:
    """getDouble path: numeric-only -> float32 bits (no expression)."""
    return W.float_to_raw_int_bits(float(value))


def _apply_modifier(p, out: list, key_lc: str, key: str, mod: dict) -> None:
    fb = p._fbits
    if key_lc == "fillmaxsize":
        v = fb(mod.get(key))
        out.append(W.mod_width(TYPE_FILL, v))
        out.append(W.mod_height(TYPE_FILL, v))
    elif key_lc == "fillmaxwidth":
        out.append(W.mod_width(TYPE_FILL, fb(mod.get(key))))
    elif key_lc == "fillmaxheight":
        out.append(W.mod_height(TYPE_FILL, fb(mod.get(key))))
    elif key_lc == "width":
        out.append(W.mod_width(TYPE_EXACT, fb(mod.get(key))))
    elif key_lc == "height":
        out.append(W.mod_height(TYPE_EXACT, fb(mod.get(key))))
    elif key_lc == "size":
        v = fb(mod.get(key))
        out.append(W.mod_width(TYPE_EXACT, v))
        out.append(W.mod_height(TYPE_EXACT, v))
    elif key_lc in ("weight", "horizontalweight"):
        out.append(W.mod_width(TYPE_WEIGHT, _num_bits(mod.get(key))))
    elif key_lc == "verticalweight":
        out.append(W.mod_height(TYPE_WEIGHT, _num_bits(mod.get(key))))
    elif key_lc in ("verticalscroll", "horizontalscroll"):
        # verticalScroll emits *two* modifiers: a clip to the component's bounds, then the
        # scroll itself. The clip is what stops the scrolled content drawing outside its
        # container, and the reference adds it as part of the same call.
        direction = 0 if key_lc == "verticalscroll" else 1
        spec = mod[key]
        if isinstance(spec, dict):
            if int(spec.get("notches", 0)) > 0:
                raise NotImplementedComponent("scroll notches TBD")
            position = spec.get("position", 0)
        else:
            position = spec
        out.append(W.mod_clip_rect())
        out.append(W.mod_scroll(direction, p._fbits(position)))
    elif key_lc == "visibility":
        # A variable id, not a boolean: the document flips the variable and everything bound
        # to it appears or disappears. See writer.mod_visibility.
        out.append(W.mod_visibility(_resolve_id(p, mod[key])))
    elif key_lc == "background":
        bg = mod[key]
        if not isinstance(bg, str):
            raise NotImplementedComponent("background non-string")
        if bg.startswith("$colors.") or bg.startswith("@colors.") or bg.startswith("$") or bg.startswith("@"):
            out.append(W.mod_background_id(p._color(bg)))     # backgroundId (any ref)
        else:
            out.append(W.mod_background(parse_color(bg)))
    elif key_lc == "border":
        b = mod[key]
        out.append(W.mod_border(float(b["width"]), float(b["cornerRadius"]),
                                p._color(b["color"]), int(b.get("shape", 0))))
    elif key_lc == "widthin":
        wi = mod[key]
        out.append(W.mod_width_in(fb(wi[0]), fb(wi[1])))
    elif key_lc == "heightin":
        hi = mod[key]
        out.append(W.mod_height_in(fb(hi[0]), fb(hi[1])))
    elif key_lc == "clip":
        shape = mod[key]
        st = str(shape.get("type", "")).lower()
        if st in ("roundrect", "roundedrect"):
            if "radius" in shape:
                r = float(shape["radius"])
                out.append(W.mod_clip_rounded_rect(r, r, r, r))
            else:
                out.append(W.mod_clip_rounded_rect(
                    float(shape.get("topStart", 0)), float(shape.get("topEnd", 0)),
                    float(shape.get("bottomStart", 0)), float(shape.get("bottomEnd", 0))))
        else:
            raise NotImplementedComponent(f"clip shape {st!r} (circle/rect TBD)")
    elif key_lc == "padding":
        pv = mod.get(key)
        if isinstance(pv, dict):
            out.append(W.mod_padding(_num_bits(pv.get("start", 0)), _num_bits(pv.get("top", 0)),
                                     _num_bits(pv.get("end", 0)), _num_bits(pv.get("bottom", 0))))
        elif isinstance(pv, list):
            out.append(W.mod_padding(_num_bits(pv[0]), _num_bits(pv[1]),
                                     _num_bits(pv[2]), _num_bits(pv[3])))
        else:
            v = fb(pv)
            out.append(W.mod_padding(v, v, v, v))
    elif key_lc in ("onclick", "multiclick"):
        raw = mod.get(key)
        if key_lc == "multiclick":
            click_type = int(raw.get("clickType", 0))
            raw = raw.get("actions")
        else:
            click_type = 0
        out.append(W.mod_click(_parse_actions(p, raw), click_type))
    elif key_lc == "semantics":
        sem = mod.get(key) or {}
        def _tid(field):
            return p.writer.add_text(str(sem[field])) if field in sem else 0
        out.append(W.mod_semantics(
            _tid("contentDescription"),
            -1,                                  # role: no JSON key for it upstream either
            _tid("text"),
            _tid("stateDescription"),
            W.SEMANTICS_MODE_SET,
            bool(sem.get("enabled", True)),
            bool(sem.get("clickable", False))))
    elif key_lc == "offset":
        ov = mod.get(key)
        if isinstance(ov, dict):
            out.append(W.mod_offset(fb(ov.get("x", 0)), fb(ov.get("y", 0))))
        elif isinstance(ov, list):
            out.append(W.mod_offset(fb(ov[0]), fb(ov[1])))
        else:
            raise NotImplementedComponent(f"offset modifier value {type(ov)}")
    else:
        raise NotImplementedComponent(f"modifier {key!r}")


# ── components ───────────────────────────────────────────────────────────────

# ── SVG path strings ─────────────────────────────────────────────────────────
#
# Mirrors AndroidxRcPlatformServices.parsePath, which is the implementation the demos
# actually run through (RemoteComposeJsonParser -> writer.addPathString ->
# platform.parsePath). Its quirks are deliberate and reproduced here, because matching
# a "more correct" SVG parser would produce different geometry from the device:
#
#   * commands are split on a lookahead over [MmZzLlHhVvCcSsQqTtAa], but only the
#     uppercase M L H V C Q S Z are implemented — every other letter, including all the
#     relative forms and 'A', raises, exactly as upstream does;
#   * 'M' consumes only the first coordinate pair, so extra pairs are dropped rather
#     than becoming implicit line-tos;
#   * 'H' draws to the *previously recorded* y (cords[1]) and does not update it;
#   * 'S' reflects through cords[0..3], which are only refreshed by C and S.
#
# Verbs are NaN-tagged ids and each segment carries its start point, matching
# pathToFloatArray.

_PATH_MOVE, _PATH_LINE, _PATH_QUAD, _PATH_CUBIC, _PATH_CLOSE = 10, 11, 12, 14, 15

_SVG_SPLIT = _re.compile(r"(?=[MmZzLlHhVvCcSsQqTtAa])")
_SVG_SEP = _re.compile(r"[,\s]+")



def _f32(v: float) -> float:
    """Narrow a double to float32, as the Java does at each (float) cast."""
    return _struct.unpack(">f", _struct.pack(">f", v))[0]


def _arc_to_cubics(x0: float, y0: float, rx: float, ry: float, angle: float,
                   large_arc: bool, sweep: bool, x1: float, y1: float) -> list:
    """Decompose an elliptical arc into cubic segments — a port of PathParser.arcTo.

    The player has no arc primitive and never will, so arcs are lowered here at authoring
    time. Kept in double throughout and narrowed to float only at the emitted control
    points, matching the Java, because rounding earlier moves the control points.

    Returns a list of (cp1x, cp1y, cp2x, cp2y, xend, yend) tuples.
    """
    if rx == 0 or ry == 0:
        return []                                  # caller emits a line instead

    alpha = _math.radians(angle)
    cos_a = _math.cos(alpha)
    sin_a = _math.sin(alpha)

    dx = (x0 - x1) / 2.0
    dy = (y0 - y1) / 2.0
    x1p = cos_a * dx + sin_a * dy
    y1p = -sin_a * dx + cos_a * dy

    rxp = abs(rx)
    ryp = abs(ry)
    check = (x1p * x1p) / (rxp * rxp) + (y1p * y1p) / (ryp * ryp)
    if check > 1.0:
        sc = _math.sqrt(check)
        rxp *= sc
        ryp *= sc

    sign = -1.0 if large_arc == sweep else 1.0
    numerator = (rxp * rxp * ryp * ryp) - (rxp * rxp * y1p * y1p) - (ryp * ryp * x1p * x1p)
    denominator = (rxp * rxp * y1p * y1p) + (ryp * ryp * x1p * x1p)
    root = _math.sqrt(max(0.0, numerator / denominator))
    cxp = sign * root * rxp * y1p / ryp
    cyp = -sign * root * ryp * x1p / rxp

    cx = cos_a * cxp - sin_a * cyp + (x0 + x1) / 2.0
    cy = sin_a * cxp + cos_a * cyp + (y0 + y1) / 2.0

    theta1 = _math.atan2((y1p - cyp) / ryp, (x1p - cxp) / rxp)
    d_theta = _math.atan2((-y1p - cyp) / ryp, (-x1p - cxp) / rxp) - theta1
    if sweep and d_theta < 0:
        d_theta += 2 * _math.pi
    elif not sweep and d_theta > 0:
        d_theta -= 2 * _math.pi

    segments = int(_math.ceil(abs(d_theta) / (_math.pi / 2.0))) or 1

    out = []
    for i in range(segments):
        s1 = theta1 + i * d_theta / segments
        s2 = theta1 + (i + 1) * d_theta / segments
        t = 4.0 / 3.0 * _math.tan((s2 - s1) / 4.0)

        xstart = cos_a * rxp * _math.cos(s1) - sin_a * ryp * _math.sin(s1) + cx
        ystart = sin_a * rxp * _math.cos(s1) + cos_a * ryp * _math.sin(s1) + cy
        xend = cos_a * rxp * _math.cos(s2) - sin_a * ryp * _math.sin(s2) + cx
        yend = sin_a * rxp * _math.cos(s2) + cos_a * ryp * _math.sin(s2) + cy

        cp1x = xstart + t * (-cos_a * rxp * _math.sin(s1) - sin_a * ryp * _math.cos(s1))
        cp1y = ystart + t * (-sin_a * rxp * _math.sin(s1) + cos_a * ryp * _math.cos(s1))
        cp2x = xend - t * (-cos_a * rxp * _math.sin(s2) - sin_a * ryp * _math.cos(s2))
        cp2y = yend - t * (-sin_a * rxp * _math.sin(s2) + cos_a * ryp * _math.cos(s2))

        out.append((_f32(cp1x), _f32(cp1y), _f32(cp2x), _f32(cp2y), _f32(xend), _f32(yend)))
    return out

def parse_svg_path(path_data: str) -> list:
    """SVG path string -> RC path float array (verb tags as raw NaN bits)."""
    out: list = []
    cords = [0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
    cx = cy = 0.0          # current point, needed because segments carry their start
    sx = sy = 0.0          # subpath start, for close

    def verb(tag: int) -> None:
        out.append(W.as_nan_bits(tag))

    for command in _SVG_SPLIT.split(path_data):
        if not command or not command[0].isalpha():
            continue
        cmd = command[0]
        rest = command[1:].strip()
        values = [float(v) for v in _SVG_SEP.split(rest) if v] if rest else []
        if cmd == "M":
            if len(values) < 2:
                raise NotImplementedComponent(f"SVG 'M' needs 2 values in {path_data!r}")
            verb(_PATH_MOVE); out += [values[0], values[1]]
            cx, cy = values[0], values[1]
            sx, sy = cx, cy
        elif cmd == "L":
            for i in range(0, len(values) - 1, 2):
                verb(_PATH_LINE); out += [cx, cy, values[i], values[i + 1]]
                cx, cy = values[i], values[i + 1]
        elif cmd == "H":
            for v in values:
                verb(_PATH_LINE); out += [cx, cy, v, cords[1]]
                cx, cy = v, cords[1]
        elif cmd == "V":
            for v in values:
                verb(_PATH_LINE); out += [cx, cy, cords[0], v]
                cx, cy = cords[0], v
        elif cmd == "C":
            for i in range(0, len(values) - 5, 6):
                verb(_PATH_CUBIC)
                out += [cx, cy, values[i], values[i + 1], values[i + 2], values[i + 3],
                        values[i + 4], values[i + 5]]
                cx, cy = values[i + 4], values[i + 5]
        elif cmd == "Q":
            for i in range(0, len(values) - 3, 4):
                verb(_PATH_QUAD)
                out += [cx, cy, values[i], values[i + 1], values[i + 2], values[i + 3]]
                cx, cy = values[i + 2], values[i + 3]
        elif cmd == "S":
            for i in range(0, len(values) - 3, 4):
                verb(_PATH_CUBIC)
                out += [cx, cy, 2 * cords[0] - cords[2], 2 * cords[1] - cords[3],
                        values[i], values[i + 1], values[i + 2], values[i + 3]]
                cx, cy = values[i + 2], values[i + 3]
        elif cmd in ("A", "a"):
            for i in range(0, len(values) - 6, 7):
                rx, ry, ang = values[i], values[i + 1], values[i + 2]
                large_arc = values[i + 3] != 0.0
                swp = values[i + 4] != 0.0
                ex, ey = values[i + 5], values[i + 6]
                if cmd == "a":                       # only the endpoint is relative
                    ex += cx
                    ey += cy
                segs = _arc_to_cubics(cx, cy, rx, ry, ang, large_arc, swp, ex, ey)
                if not segs:                          # zero radius degenerates to a line
                    verb(_PATH_LINE); out += [cx, cy, ex, ey]
                    cx, cy = ex, ey
                    continue
                for c1x, c1y, c2x, c2y, xe, ye in segs:
                    verb(_PATH_CUBIC)
                    out += [cx, cy, c1x, c1y, c2x, c2y, xe, ye]
                    cx, cy = xe, ye
        elif cmd == "Z":
            verb(_PATH_CLOSE)
            cx, cy = sx, sy
        else:
            raise NotImplementedComponent(
                f"SVG path command {cmd!r} is not supported by the platform parser "
                f"(only M L H V C Q S Z) in {path_data!r}")

        # cords tracking, copied from upstream including which commands skip it
        if cmd not in ("Z", "H") and len(values) >= 2:
            cords[0] = values[-2]
            cords[1] = values[-1]
            if cmd in ("C", "S") and len(values) >= 4:
                cords[2] = values[-4]
                cords[3] = values[-3]
    return out


class _VariableMap(dict):
    """name -> NaN-id bits, with lazy materialisation of deferred declarations.

    A float variable declared outside the first pass and without commit/flush is
    *deferred* by RemoteComposeJsonParser: nothing is written where it appears, and its
    ops are emitted at the point of first use instead (mDeferredVariables /
    resolveDeferredVariable). That placement is not cosmetic — a definition emitted
    inside a canvas lands in the draw stream, so hoisting or sinking it changes what the
    document draws.

    This is a dict subclass rather than an explicit check at each call site because the
    expression parser holds the same object, so every read has to go through one place.
    """

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.deferred: dict[str, dict] = {}
        self.resolver = None                 # set by the parser that owns this map

    def defer(self, name: str, command: dict) -> None:
        self.deferred[name] = command

    def is_materialised(self, name: str) -> bool:
        """True only for variables already written. Mirrors mVariables.containsKey,
        which does not see deferred entries — that is what lets a later declaration of
        the same name replace a pending one."""
        return dict.__contains__(self, name)

    def __contains__(self, key) -> bool:
        return dict.__contains__(self, key) or key in self.deferred

    def __missing__(self, key):
        if key in self.deferred and self.resolver is not None:
            return self.resolver(key)
        raise KeyError(key)

    def get(self, key, default=None):
        if dict.__contains__(self, key):
            return dict.__getitem__(self, key)
        if key in self.deferred and self.resolver is not None:
            return self.resolver(key)
        return default


class RemoteComposeJsonParser:
    def __init__(self, writer: RemoteComposeWriter,
                 base_dir: str | None = None) -> None:
        self.writer = writer
        self.variables = _VariableMap()          # name -> NaN-id bits
        self.variables.resolver = self._resolve_deferred
        self.colors: dict[str, int] = {}         # $colors.name -> color id
        self.paths: dict[str, int] = {}          # path name -> path id
        self.in_first_pass = False
        self.global_nesting = 0
        self.profiles = 0                        # header DOC_PROFILES bitmask
        self.expr = ExpressionParser(writer, self.variables)
        #: name -> image id, from resources.bitmaps
        self.bitmaps: dict[str, int] = {}
        #: resolves relative bitmap paths; None means absolute-or-base64 only
        self._base_dir = base_dir or "." 

    def _color(self, value):
        """Resolve a color value: literal hex/number, $colors. ref, or a $var color ref."""
        if isinstance(value, str) and (value.startswith("$colors.") or value.startswith("@colors.")):
            name = value[8:]
            if name not in self.colors:
                raise NotImplementedComponent(f"Color not found: {name}")
            return self.colors[name]
        if isinstance(value, str) and (value.startswith("$") or value.startswith("@")):
            from .expr import variable_name_from_ref
            name = variable_name_from_ref(value)
            if name in self.variables:
                bits = self.variables[name]
                if _is_nan_bits(bits):           # NaN-encoded var -> idFromNan
                    return bits & 0x3FFFFF
                return int(_int_bits_to_float(bits))   # plain (float)colorId
            raise NotImplementedComponent(f"color variable {name!r} not found")
        return parse_color(value)

    def _fbits(self, value) -> int:
        """Resolve a canvas float field to its float32 BITS (literal, ref, or expression).

        Mirrors parseFloat but returns raw bits so NaN-encoded expression ids survive.
        """
        if value is None:
            return W.NAN_BITS
        if isinstance(value, bool):
            return W.float_to_raw_int_bits(float(int(value)))
        if isinstance(value, (int, float)):
            return W.float_to_raw_int_bits(float(value))
        if isinstance(value, dict):              # animated expression {value, anim}
            try:
                return self.expr.parse_expression(value)
            except ExpressionError as e:
                raise NotImplementedComponent(str(e)) from e
        if isinstance(value, str):
            special = {"NaN": 0x7FC00000, "Infinity": 0x7F800000, "-Infinity": 0xFF800000}
            if value in special:
                return special[value]
            if value == "max":
                return W.float_to_raw_int_bits(_F32_MAX)
            try:
                if self.expr.is_variable(value):
                    return self.expr.variable_nan_bits(value)
                return self.expr.parse_expression(value)
            except ExpressionError as e:
                raise NotImplementedComponent(str(e)) from e
        raise NotImplementedComponent(f"float field type {type(value)}")

    # Component types handled in the first (resource) pass rather than as layout.
    _FIRST_PASS_TYPES = {"resources", "variable", "global", "definepattern",
                         "referencedoperations"}

    def parse(self, doc: dict) -> None:
        header = doc.get("header") or {}
        self.profiles = int(header.get("profiles", 0) or 0)
        if "resources" in doc:
            self._parse_resources(doc["resources"])
        root = doc.get("root")
        if root is None:
            return

        items = root if isinstance(root, list) else [root]
        items = [normalize_component(i) for i in items]

        # Pass 1: resources / variables / global blocks, emitted before the root op so
        # their ids are allocated first (mirrors RemoteComposeJsonParser.parse).
        self.in_first_pass = True
        for item in items:
            if str(item.get("type", "")).lower() in self._FIRST_PASS_TYPES:
                self._parse_component(item)
        self.in_first_pass = False

        # Pass 2: layout.
        self.writer.root_start()
        for item in items:
            t = str(item.get("type", "")).lower()
            if t not in ("resources", "variable", "definepattern", "referencedoperations"):
                self._parse_component(item)
        while self.global_nesting > 0:
            self.end_global()
        self.writer.container_end()  # end root

    # ── global blocks ────────────────────────────────────────────────────────

    def begin_global(self) -> None:
        if self.global_nesting == 0:
            self.writer.begin_global()
        self.global_nesting += 1

    def end_global(self) -> None:
        if self.global_nesting > 0:
            self.global_nesting -= 1
            if self.global_nesting == 0:
                self.writer.end_global()

    # ── resources ────────────────────────────────────────────────────────────

    _RESOURCE_DEFAULT_ORDER = ["v_dims", "colors", "paths", "floatArrays", "variables",
                               "integers", "matrices", "bitmaps", "sounds"]


    @staticmethod
    def _png_size(data: bytes):
        """Width and height from a PNG's IHDR.

        Read rather than declared: the wire format needs the real dimensions, and an author
        who has to restate them will eventually restate them wrongly — the image would then
        sample against the wrong grid with nothing to indicate why.
        """
        if len(data) < 24 or data[:8] != b"\x89PNG\r\n\x1a\n" or data[12:16] != b"IHDR":
            raise NotImplementedComponent(
                "bitmap: only PNG is supported, and this does not start with a PNG header")
        return (int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big"))

    def _parse_bitmaps(self, section) -> None:
        """Declare named images.

        Upstream sources bitmaps from a host-supplied map keyed by name, which a file-based
        converter has no equivalent of, so the JSON names a file instead and `rcj` reads it.
        `base64` is accepted for a self-contained document.
        """
        import base64 as _b64
        import os as _os
        for _cfg, name, value in self._each_resource(section):
            if isinstance(value, str):
                value = {"file": value}
            if "base64" in value:
                data = _b64.b64decode(value["base64"])
            elif "file" in value:
                path = value["file"]
                if not _os.path.isabs(path):
                    path = _os.path.join(self._base_dir, path)
                try:
                    data = open(path, "rb").read()
                except OSError as e:
                    raise NotImplementedComponent(f"bitmap {name!r}: {e}")
            else:
                raise NotImplementedComponent(
                    f"bitmap {name!r} needs 'file' or 'base64'")
            width, height = self._png_size(data)
            image_id = self.writer.alloc_data_id()
            self.writer.add_bitmap(image_id, width, height, data)
            self.bitmaps[name] = image_id

    def _parse_sounds(self, section) -> None:
        """Declare named sounds, embedding the audio.

        Same three sources as a bitmap — `base64`, `url`, `file`, or a bare string taken as
        a file — and the same rule: whatever the source, the bytes end up in the document.
        Unlike a bitmap there is no header to read; the engine takes the audio as it is.
        """
        for _cfg, name, value in self._each_resource(section):
            data = self._read_binary("sound", name, value)
            sound_id = self.writer.alloc_data_id()
            self.writer.add_sound(sound_id, data)
            self.variables[name] = W.as_nan_bits(sound_id)

    def _read_binary(self, what, name, value) -> bytes:
        """Bytes behind a binary resource declaration (a bitmap or a sound)."""
        import base64 as _b64, os as _os, urllib.request as _url
        if isinstance(value, str):
            value = {"file": value}
        if not isinstance(value, dict):
            raise NotImplementedComponent(f"{what} {name!r}: expected an object")
        if "base64" in value:
            try:
                return _b64.b64decode(value["base64"])
            except Exception as e:
                raise NotImplementedComponent(f"{what} {name!r}: bad base64: {e}")
        if "url" in value:
            # Fetched now, not referenced: a document that still needs the network to
            # render is not self-contained.
            try:
                with _url.urlopen(value["url"]) as fh:
                    return fh.read()
            except Exception as e:
                raise NotImplementedComponent(
                    f"{what} {name!r}: cannot fetch {value['url']}: {e}")
        if "file" in value:
            path = value["file"]
            if not _os.path.isabs(path):
                path = _os.path.join(self._base_dir, path)
            try:
                return open(path, "rb").read()
            except OSError as e:
                raise NotImplementedComponent(f"{what} {name!r}: {e}")
        raise NotImplementedComponent(
            f"{what} {name!r} needs 'base64', 'url' or 'file'")

    def _bitmap_id(self, value) -> int:
        """Resolve a bitmap reference: a numeric id, or `@name` / `$name` from resources."""
        if isinstance(value, str):
            from .expr import variable_name_from_ref
            name = variable_name_from_ref(value) if value[:1] in "@$" else value
            if name in self.bitmaps:
                return self.bitmaps[name]
            known = ", ".join(sorted(self.bitmaps)) or "none declared"
            raise NotImplementedComponent(
                f"bitmap {value!r} not found (declared: {known})")
        return int(value)

    def _parse_resources(self, resources: dict) -> None:
        order = resources.get("order") or [k for k in self._RESOURCE_DEFAULT_ORDER if k in resources]
        for key in order:
            if key not in resources:
                continue
            if key == "colors":
                self._parse_colors(resources[key])
            elif key == "floatArrays":
                self._parse_float_arrays(resources[key])
            elif key == "variables":
                self._parse_variables_resource(resources[key])
            elif key == "bitmaps":
                self._parse_bitmaps(resources[key])
            elif key == "sounds":
                self._parse_sounds(resources[key])
            else:
                raise NotImplementedComponent(
                    f"resource type {key!r} (colors/floatArrays/variables/bitmaps only)")

    @staticmethod
    def _each_resource(section):
        """Yield (config, name, value) for the three accepted resource shapes:
        tag-key array `[{name: value}]`, verbose array `[{"name":n,"value":v}]`, and
        map `{name: value}` (mirrors ResourceParser.parseOrderedResource)."""
        if isinstance(section, list):
            for entry in section:
                if "name" not in entry and len(entry) == 1:
                    name = next(iter(entry))
                    value = entry[name]
                    yield (value if isinstance(value, dict) else None), name, value
                else:
                    yield entry, entry["name"], entry["value"]
        elif isinstance(section, dict):
            for name, value in section.items():
                yield (value if isinstance(value, dict) else None), name, value

    def _parse_variables_resource(self, section) -> None:
        """`resources.variables` — float constants and expressions.

        Unlike the inline `variable` command these default to `export: false`, i.e. an
        anonymous float constant rather than a named variable.
        """
        for config, name, value in self._each_resource(section):
            named = bool(config.get("export", False)) if config else False
            val = value
            if isinstance(value, dict):
                vtype = str(value.get("type", "")).lower()
                if vtype in ("integer", "int", "textfromfloat"):
                    raise NotImplementedComponent(f"resources.variables type {vtype!r} TBD")
                if "value" in value and "anim" not in value:
                    val = value["value"]
            if isinstance(val, str) and val in ("width", "height", "fontSize"):
                raise NotImplementedComponent(f"resources.variables dimension {val!r} TBD")
            if isinstance(val, bool):
                raise NotImplementedComponent("boolean variable value")
            if isinstance(val, (int, float)):
                # `export: true` makes this a *named* variable the host can read and write
                # at runtime — which is how a document exposes state, and how the DroidKaigi
                # timetable's filter chips drive the visibility of every talk.
                self.variables[name] = (self.writer.add_named_float(name, float(val))
                                        if named
                                        else self.writer.add_float_constant(float(val)))
            else:
                # Expression / ref: parseFloat yields a NaN-encoded id, stored as-is. There
                # is nothing to create, so exporting only attaches a name to the existing id.
                bits = self._fbits(val)
                self.variables[name] = bits
                if named:
                    self.writer.set_float_name(_id_from_nan_bits(bits), name)

    def _parse_float_arrays(self, arrays) -> None:
        def define(name, value, config):
            data = value["value"] if isinstance(value, dict) else value
            data = [float(x) for x in data]
            named = config is None or config.get("export", True)
            aid = (self.writer.add_named_float_array(name, data) if named
                   else self.writer.add_float_array(data))
            self.variables[name] = W.as_nan_bits(aid)

        if isinstance(arrays, list):
            for entry in arrays:
                if "name" not in entry and len(entry) == 1:
                    name = next(iter(entry)); v = entry[name]
                    define(name, v, v if isinstance(v, dict) else None)
                else:
                    define(entry["name"], entry["value"], entry)
        elif isinstance(arrays, dict):
            for name, value in arrays.items():
                define(name, value, value if isinstance(value, dict) else None)

    def _parse_colors(self, colors) -> None:
        """colors: array of single-key objects [{name: value}] or an object {name: value}."""
        def define(name, value):
            if isinstance(value, dict):
                raise NotImplementedComponent("themed (light/dark) color TBD")
            self.colors[name] = self.writer.add_named_color(name, parse_color(value))

        if isinstance(colors, list):
            for entry in colors:
                if "name" not in entry and len(entry) == 1:
                    name = next(iter(entry))
                    define(name, entry[name])
                else:
                    define(entry["name"], entry["value"])
        elif isinstance(colors, dict):
            for name, value in colors.items():
                define(name, value)

    def _parse_children(self, children) -> None:
        if not children:
            return
        for child in children:
            self._parse_component(normalize_component(child))

    def _parse_component(self, component: dict) -> None:
        ctype = str(component["type"]).lower()

        # Resource-pass components: no layout, no modifiers.
        if ctype == "resources":
            # `{"resources": {...}}` normalizes to `{"type":"resources", <sections...>}`,
            # so the sections sit at the top level of `component`.
            if self.in_first_pass:
                self._parse_resources(component)
            return
        if ctype == "rem":
            # `rem` is both a command and a component upstream, so it can annotate a
            # component tree as well as a command list.
            self.writer.rem(str(component.get("text",
                                component.get("value",
                                component.get("message",
                                component.get("comment", ""))))))
            return
        if ctype == "variable":
            name = component.get("name")
            # is_materialised, not `in`: a pending deferred declaration is invisible to
            # mVariables.containsKey upstream, so a later declaration replaces it.
            if self.in_first_pass or not self.variables.is_materialised(name):
                self._parse_variable(component)
            return
        if ctype == "global":
            children = component.get("children") or []
            if self.in_first_pass:
                self.begin_global()
                for child in children:
                    child = normalize_component(child)
                    if str(child.get("type", "")).lower() in self._FIRST_PASS_TYPES:
                        self._parse_component(child)
                self.end_global()
            else:
                self._parse_children(children)
            return

        if "resources" in component and self.in_first_pass:
            self._parse_resources(component["resources"])

        mods = parse_modifiers(self, component.get("modifiers"))
        w = self.writer

        if ctype == "column":
            w.start_column(_h_align(component, "start"), _v_align(component, "top"), mods)
            self._parse_children(component.get("children"))
            w.end_column()
        elif ctype == "row":
            w.start_row(_h_align(component, "start"), _v_align(component, "top"), mods)
            self._parse_children(component.get("children"))
            w.end_row()
        elif ctype == "box":
            children = component.get("children")
            if not children:
                # A childless box takes the leaf form, and note the different alignment
                # defaults: centre/centre here, start/top for the container form below.
                w.box_leaf(_h_align(component, "center"), _v_align(component, "center"), mods)
                return
            w.start_box(_h_align(component, "start"), _v_align(component, "top"), mods)
            self._parse_children(children)
            w.end_box()
        elif ctype == "text":
            self._parse_text(component, mods)
        elif ctype == "canvas":
            self._parse_canvas(component, mods)
        elif ctype == "spacer":
            if not mods:
                mods = [W.mod_width(TYPE_WEIGHT, W.float_to_raw_int_bits(1.0))]
            w.start_box(0, 0, mods)
            w.end_box()
        elif ctype == "flow":
            w.start_flow(_h_align(component, "start"), _v_align(component, "top"), mods,
                         int(component.get("maxColumns", 2147483647)))
            self._parse_children(component.get("children"))
            w.end_flow()
        elif ctype == "collapsiblecolumn":
            w.start_collapsible_column(_h_align(component, "center"), _v_align(component, "center"), mods)
            self._parse_children(component.get("children"))
            w.end_collapsible_column()
        elif ctype == "collapsiblerow":
            w.start_collapsible_row(_h_align(component, "center"), _v_align(component, "center"), mods)
            self._parse_children(component.get("children"))
            w.end_collapsible_row()
        elif ctype == "fitbox":
            w.start_fit_box(_h_align(component, "center"), _v_align(component, "center"), mods)
            self._parse_children(component.get("children"))
            w.end_fit_box()
        else:
            raise NotImplementedComponent(f"component type {component['type']!r}")

    # ── canvas ───────────────────────────────────────────────────────────────

    def _parse_canvas(self, component: dict, mods: list) -> None:
        self.writer.start_canvas(mods)
        for cmd in component.get("commands") or []:
            self._parse_command(cmd)
        self.writer.end_canvas()

    def _parse_command(self, command: dict) -> None:
        command = _normalize_command(command)
        ctype = str(command["type"]).lower()
        w = self.writer
        fb = self._fbits
        if ctype == "paint":
            w.paint_values(_build_paint_bundle(self, command))
        elif ctype == "setcolor":
            w.paint_values([W.PB_COLOR, _to_int32(parse_color(command["color"]))])
        elif ctype == "setstyle":
            s = _STYLE.get(str(command["style"]).lower())
            if s is None:
                raise NotImplementedComponent(f"setStyle {command['style']!r}")
            w.paint_values([W.PB_STYLE | (s << 16)])
        elif ctype == "setstrokewidth":
            w.paint_values([W.PB_STROKE_WIDTH, W.float_to_raw_int_bits(parse_float(command["width"]))])
        elif ctype == "drawcircle":
            w.draw_circle(fb(command["cx"]), fb(command["cy"]), fb(command["radius"]))
        elif ctype == "drawline":
            w.draw_line(fb(command["x1"]), fb(command["y1"]), fb(command["x2"]), fb(command["y2"]))
        elif ctype == "drawrect":
            w.draw_rect(fb(command["left"]), fb(command["top"]),
                        fb(command["right"]), fb(command["bottom"]))
        elif ctype == "drawoval":
            w.draw_oval(fb(command["left"]), fb(command["top"]),
                        fb(command["right"]), fb(command["bottom"]))
        elif ctype == "drawtextanchored":
            text_obj = command["text"]
            if isinstance(text_obj, str) and (text_obj.startswith("$") or text_obj.startswith("@")):
                raise NotImplementedComponent(f"drawTextAnchored text ref {text_obj!r}")
            tid = w.add_text(str(text_obj))
            w.draw_text_anchored(tid, fb(command["x"]), fb(command["y"]),
                                 fb(command["panX"]), fb(command["panY"]),
                                 int(command.get("flags", 0)))
        elif ctype == "drawtextrun":
            # Draw a whole string at (x, baseline=y). start/end are UTF-16 char indices
            # into the string (the player converts them to UTF-8 byte offsets).
            s = str(command["text"])
            n = len(s.encode("utf-16-le")) // 2   # UTF-16 code-unit length
            tid = w.add_text(s)
            w.draw_text_run(tid, 0, n, 0, n, fb(command["x"]), fb(command["y"]),
                            bool(command.get("rtl", False)))
        elif ctype == "drawroundrect":
            w.draw_round_rect(fb(command["left"]), fb(command["top"]), fb(command["right"]),
                              fb(command["bottom"]), fb(command["rx"]), fb(command["ry"]))
        elif ctype == "drawarc":
            w.draw_arc(fb(command["left"]), fb(command["top"]), fb(command["right"]),
                       fb(command["bottom"]), fb(command["startAngle"]), fb(command["sweepAngle"]))
        elif ctype == "impulse":
            w.impulse_start(fb(command["duration"]), fb(command["start"]))
            for c in command.get("commands", []):
                self._parse_command(c)
            w.container_end()
        elif ctype == "impulseprocess":
            w.impulse_process_start()
            for c in command.get("commands", []):
                self._parse_command(c)
            w.container_end()
        elif ctype == "drawsector":
            w.draw_sector(fb(command["left"]), fb(command["top"]), fb(command["right"]),
                          fb(command["bottom"]), fb(command["startAngle"]),
                          fb(command["sweepAngle"]))
        elif ctype == "save":
            w.matrix_save()
            if "commands" in command:
                for c in command["commands"]:
                    self._parse_command(c)
                w.matrix_restore()
        elif ctype == "restore":
            w.matrix_restore()
        elif ctype == "translate":
            w.translate(fb(command["dx"]), fb(command["dy"]))
        elif ctype == "rotate":
            angle = fb(command["angle"])
            if "pivotX" in command or "centerX" in command:
                px = fb(command["pivotX"] if "pivotX" in command else command["centerX"])
                py = fb(command["pivotY"] if "pivotY" in command else command["centerY"])
                w.rotate(angle, px, py)
            else:
                w.rotate(angle)
        elif ctype == "scale":
            w.scale(fb(command["sx"]), fb(command["sy"]))
        elif ctype == "cliprect":
            w.clip_rect(fb(command["left"]), fb(command["top"]),
                        fb(command["right"]), fb(command["bottom"]))
        elif ctype == "variable":
            self._parse_variable(command)
        elif ctype == "pathcreate":
            pid = w.path_create(fb(command["x"]), fb(command["y"]))
            if command.get("id") is not None:
                self.paths[str(command["id"])] = pid
        elif ctype == "createparticles":
            # `variables` names the per-particle slots; `initialValues` gives one expression
            # each, evaluated once per particle when the system is seeded. Both the system
            # id and the variable names become ordinary float variables afterwards, which is
            # how the loop body and any drawing command refer to them.
            names = [str(v) for v in command["variables"]]
            inits = [self.expr.infix_to_rpn(str(v)) for v in command["initialValues"]]
            if len(inits) != len(names):
                raise NotImplementedComponent(
                    f"createParticles: {len(names)} variables but {len(inits)} initialValues")
            system_id, var_ids = w.create_particles(inits, int(command["count"]))
            self.variables[str(command["id"])] = W.as_nan_bits(system_id)
            for name, vid in zip(names, var_ids):
                self.variables[name] = W.as_nan_bits(vid)
        elif ctype == "particlescomparison":
            def _eqs(key):
                raw = command.get(key)
                return ([self.expr.infix_to_rpn(str(e)) for e in raw]
                        if raw is not None else None)
            cond = (self.expr.infix_to_rpn(str(command["condition"]))
                    if "condition" in command else None)
            # `then2` falls back to `then`, matching the reference's spelling of the same
            # field; `then1` has no such alias.
            then2 = _eqs("then2") if "then2" in command else _eqs("then")
            w.particles_compare_start(fb(command["systemId"]) & 0x007FFFFF,
                                      int(command.get("flags", 0)),
                                      fb(command["min"]), fb(command["max"]),
                                      cond, _eqs("then1"), then2)
            for c in command.get("commands", []):
                self._parse_command(c)
            w.container_end()
        elif ctype == "soundexpression":
            stype = str(command.get("synthesis", "tone")).lower()
            if stype == "tone":
                type_const = 10                       # SoundExpression.TYPE_TONE
            elif isinstance(command.get("synthesis"), (int, float)):
                type_const = int(command["synthesis"])
            else:
                raise NotImplementedComponent(
                    f"soundExpression synthesis {command.get('synthesis')!r} "
                    "(expected 'tone' or a numeric type constant)")
            wave = str(command.get("waveform", "sine")).lower()
            if wave not in _WAVEFORM:
                raise NotImplementedComponent(
                    f"soundExpression waveform {wave!r} "
                    f"(expected one of {sorted(_WAVEFORM)})")
            # TYPE_TONE is the only type with named parameters; anything else carries just
            # its own tag, matching buildSoundParams upstream.
            if type_const == 10:
                params = [W.as_nan_bits(10),
                          fb(command.get("frequency", 440)),
                          fb(command.get("duration", 1)),
                          fb(float(_WAVEFORM[wave]))]
            else:
                params = [W.as_nan_bits(type_const)]
            sound_id = w.alloc_data_id()
            w.sound_expression(sound_id,
                               fb(command.get("leftVolume", 1.0)),
                               fb(command.get("rightVolume", 1.0)),
                               fb(command.get("rate", 1.0)), params)
            if command.get("id") is not None:
                self.variables[str(command["id"])] = W.as_nan_bits(sound_id)
        elif ctype == "rem":
            # A remark carried in the document. Four spellings, in the reference's own
            # order of preference, and an absent one is an empty remark rather than an
            # error — a comment is not worth failing a build over.
            w.rem(str(command.get("text",
                      command.get("value",
                      command.get("message",
                      command.get("comment", ""))))))
        elif ctype == "playsound":
            w.play_sound(_resolve_id(self, command["id"]))
        elif ctype == "particlesloop":
            # One equation per variable slot, run for every particle every frame, then the
            # body draws that particle. `restart` re-seeds a particle when it evaluates
            # true — that is what makes an emitter loop rather than run once.
            system_bits = fb(command["system"])
            restart = (self.expr.infix_to_rpn(str(command["restart"]))
                       if "restart" in command else None)
            eqs = [self.expr.infix_to_rpn(str(e)) for e in command["equations"]]
            w.particles_loop_start(system_bits & 0x007FFFFF, restart, eqs)
            for c in command.get("commands", []):
                self._parse_command(c)
            w.container_end()
        elif ctype == "pathexpression":
            # start/end/count name the sweep of the parameter that the expressions see as
            # a[0]; the reference calls them min/max on the wire.
            #
            # expressionY and count are required, though the *op* allows a null Y (written
            # as a zero-length array). That is deliberate: the reference JSON parser throws
            # without them, so accepting them here would produce bytes no reference run
            # could be compared against.
            x_ops = self.expr.infix_to_rpn(str(command["expressionX"]))
            y_ops = self.expr.infix_to_rpn(str(command["expressionY"]))
            pid = w.path_expression(int(command.get("flags", 0)),
                                    fb(command["start"]), fb(command["end"]),
                                    fb(command["count"]), x_ops, y_ops)
            if command.get("id") is not None:
                self.paths[str(command["id"])] = pid
        elif ctype == "pathappendlineto":
            w.path_append_line_to(self._parse_path(command["path"]),
                                  fb(command["x"]), fb(command["y"]))
        elif ctype == "pathappendclose":
            w.path_append_close(self._parse_path(command["path"]))
        elif ctype == "drawpath":
            w.draw_path(self._parse_path(command["path"]))
        elif ctype == "loop":
            from_b = fb(command["from"])
            step_b = fb(command["step"]) if "step" in command else W.float_to_raw_int_bits(1.0)
            until_b = fb(command["until"])
            index = str(command.get("index", "i"))
            if command.get("noIndexText", False):
                index_id = w.alloc_data_id()           # createID(0)
            else:
                index_id = w.add_text(index)            # textCreateId
            w.start_loop(index_id, from_b, step_b, until_b)
            had = index in self.variables
            prev = self.variables.get(index)
            self.variables[index] = W.as_nan_bits(index_id)
            for c in command.get("commands", []):
                self._parse_command(c)
            if had:
                self.variables[index] = prev
            else:
                self.variables.pop(index, None)
            w.end_loop()
        elif ctype == "conditionaloperations":
            cond = {"gt": 4, "ge": 5, "lt": 2, "le": 3, "eq": 0}.get(str(command["condition"]).lower(), 0)
            w.conditional_operations(cond, fb(command["v1"]), fb(command["v2"]))
            for c in command.get("commands", []):
                self._parse_command(c)
            w.end_conditional()
        elif ctype == "definemesh3d":
            verts = [fb(v) for v in command["verts"]]
            normals = [fb(v) for v in command.get("normals", [])] or None
            uv = [fb(v) for v in command.get("uv", [])] or None
            idx = [int(i) for i in command["indices"]]
            if len(idx) % 3:
                raise NotImplementedComponent(
                    f"defineMesh3D indices length {len(idx)} is not a multiple of 3")
            if len(verts) % 3:
                raise NotImplementedComponent(
                    f"defineMesh3D verts length {len(verts)} is not a multiple of 3")
            if normals is not None and len(normals) != len(verts):
                raise NotImplementedComponent(
                    f"defineMesh3D normals {len(normals)} != verts {len(verts)}")
            if uv is not None and len(uv) != (len(verts) // 3) * 2:
                raise NotImplementedComponent(
                    f"defineMesh3D uv {len(uv)} != 2 per vertex ({(len(verts)//3)*2})")
            w.define_mesh_3d(int(command["id"]), idx, verts, normals, uv)
        elif ctype == "touchexpression":
            # The accumulating touch value. `expression` maps the raw touch to this value's
            # rate of change, so it is nearly always a bare `touchX()`/`touchY()` scaled by a
            # per-pixel factor; the integration, clamping and release behaviour are the op's.
            mode = command.get("stopMode", command.get("touchMode", 0))
            if isinstance(mode, str):
                key = mode.lower().replace("_", "")
                if key not in _TOUCH_STOP:
                    raise NotImplementedComponent(
                        f"touchExpression stopMode {mode!r} "
                        f"(expected one of {sorted(_TOUCH_STOP)})")
                mode = _TOUCH_STOP[key]
            # `min` absent means wrap around `max`, which is a different behaviour from
            # min=0 — so it defaults to NaN rather than to a number, matching upstream.
            min_b = fb(command["min"]) if "min" in command else W.NAN_BITS
            vel_b = fb(command["velocityId"]) if "velocityId" in command else W.NAN_BITS
            # Upstream's `expression` is a raw float array run element-wise through
            # parseFloat, so it can name a system variable but has no operators. Accepting
            # an infix string as well is an rcj extension — every other expression in this
            # dialect is infix, and `touchX() * 0.012` is the shape these actually take.
            # The array form stays byte-identical to the Java converter.
            raw = command.get("expression", "touchX()")
            if isinstance(raw, list):
                ops = [fb(v) for v in raw]
            else:
                ops = self.expr.infix_to_rpn(str(raw))
            bits = w.touch_expression(
                fb(command.get("defaultValue", 0.0)), min_b, fb(command.get("max", 1.0)),
                int(mode), vel_b, int(command.get("touchEffects", 0)), ops,
                [float(v) for v in command["touchSpec"]] if "touchSpec" in command else None,
                [float(v) for v in command["easingSpec"]] if "easingSpec" in command else None)
            name = command.get("name")
            if name:
                self.variables[name] = bits
        elif ctype == "vectorexpression":
            dim = int(command.get("dimension", 3))
            if dim not in (2, 3, 4):
                raise NotImplementedComponent(
                    f"vectorExpression dimension {dim} (expected 2, 3 or 4)")
            ops = self.expr.infix_to_rpn(str(command["expression"]),
                                         extra_functions=_VECTOR_FUNCTIONS)
            base = w.vector_expression(dim, int(command.get("flags", 0)), ops)
            name = command.get("name")
            if name:
                # Bind name.x/.y/.z/.w to the component ids so later expressions can read them
                # as ordinary scalars. That is the whole point of the op: nothing downstream
                # needs to know a vector was involved.
                for k in range(dim):
                    self.variables[f"{name}.{_VECTOR_COMPONENTS[k]}"] = W.as_nan_bits(base + k)
        elif ctype == "meshexpression3d":
            surface = str(command.get("surface", "general")).lower().replace("_", "")
            if surface not in _SURFACE:
                raise NotImplementedComponent(
                    f"meshExpression3D surface {command.get('surface')!r} "
                    f"(expected one of {sorted(_SURFACE)})")
            stype = _SURFACE[surface]

            def rpn(expr):
                """Compile one infix expression with `u`/`v` bound to VAR1/VAR2."""
                saved = {k: self.variables.get(k) for k in ("u", "v")}
                self.variables["u"] = _VAR1_BITS
                self.variables["v"] = _VAR2_BITS
                try:
                    return self.expr.infix_to_rpn(str(expr))
                finally:
                    for k, old in saved.items():
                        if old is None:
                            self.variables.pop(k, None)
                        else:
                            self.variables[k] = old

            def need(key):
                if key not in command:
                    raise NotImplementedComponent(
                        f"meshExpression3D {surface}: missing {key!r}")
                return command[key]

            def rng(key, default=None):
                r = command.get(key, default)
                if r is None or len(r) != 2:
                    raise NotImplementedComponent(
                        f"meshExpression3D {surface}: {key!r} must be [min, max]")
                return [fb(r[0]), fb(r[1])]

            if surface == "heightfield":
                params = (rng("xRange") + [fb(need("uCount"))]
                          + rng("zRange") + [fb(need("vCount"))]
                          + rng("yRange", [-1e6, 1e6]))
                pos = [rpn(need("height"))]
            elif surface == "sphere":
                params = [fb(need("radius")), fb(need("uCount")), fb(need("vCount"))]
                pos = [rpn(command.get("displacement", 0))]
            elif surface == "cylinder":
                params = [fb(need("radius")), fb(need("height")),
                          fb(need("uCount")), fb(need("vCount"))]
                pos = [rpn(command.get("displacement", 0))]
            else:
                params = (rng("uRange") + [fb(need("uCount"))]
                          + rng("vRange") + [fb(need("vCount"))])
                pos = [rpn(need("x")), rpn(need("y")), rpn(need("z"))]

            normal = [rpn(e) for e in command.get("normal", [])]
            if normal and len(normal) != 3:
                raise NotImplementedComponent(
                    "meshExpression3D: 'normal' needs three expressions (nx, ny, nz); "
                    "omit it for finite-difference normals")
            uvg = [rpn(e) for e in command.get("uv", [])]
            if uvg and len(uvg) != 2:
                raise NotImplementedComponent(
                    "meshExpression3D: 'uv' needs two expressions (u, v)")
            flags = int(command.get("flags", 0))
            if command.get("flipWinding"):
                flags |= 0x1
            w.mesh_expression_3d(int(command["id"]), stype, flags, params, pos, normal, uvg)
        elif ctype == "meshprimitive3d":
            kind = str(command["primitive"]).lower().replace("_", "").replace("-", "")
            if kind not in _PRIMITIVE:
                raise NotImplementedComponent(
                    f"meshPrimitive3D primitive {command['primitive']!r} "
                    f"(expected one of {sorted(_PRIMITIVE)})")
            ptype = _PRIMITIVE[kind]
            flags_extra = 0
            extra_channels: list = []
            if "params" in command:
                scalars = [fb(v) for v in command["params"]]
            elif kind in ("tube", "captube"):
                # [radius, (ringsPerSpan), x0,y0,z0, ...]
                scalars = [fb(command["radius"])]
                if "ringsPerSpan" in command:
                    flags_extra |= _FLAG_TUBE_PATH_DENSITY
                    scalars.append(fb(command["ringsPerSpan"]))
                scalars += [fb(v) for v in _points(command, "points", 3)]
                if command.get("legacy"):
                    flags_extra |= _FLAG_TUBE_LEGACY
                if command.get("spline"):
                    flags_extra |= _FLAG_SPLINE
            elif kind == "profiletube":
                # [nPoints, (ringsPerSpan), x,y,z * n, r0..rk]
                pts = _points(command, "points", 3)
                radii = command.get("radii")
                if not radii:
                    raise NotImplementedComponent("meshPrimitive3D profileTube: missing 'radii'")
                scalars = [fb(len(pts) // 3)]
                if "ringsPerSpan" in command:
                    flags_extra |= _FLAG_TUBE_PATH_DENSITY
                    scalars.append(fb(command["ringsPerSpan"]))
                scalars += [fb(v) for v in pts] + [fb(r) for r in radii]
                if command.get("capped", True):
                    flags_extra |= _FLAG_TUBE_CAP
            elif kind == "sweep":
                # scalars = [closed, capStart, capEnd, cx,cy,cz]; the section and path ride
                # channels 1 and 2, with optional per-station scale and twist after them.
                centre = command.get("center", [0, 0, 0])
                if len(centre) != 3:
                    raise NotImplementedComponent("meshPrimitive3D sweep: center needs 3 values")
                scalars = [fb(1 if command.get("closed", True) else 0),
                           fb(1 if command.get("capStart", True) else 0),
                           fb(1 if command.get("capEnd", True) else 0)] + [fb(v) for v in centre]
                extra_channels.append([fb(v) for v in _points(command, "section", 2)])
                extra_channels.append([fb(v) for v in _points(command, "path", 3)])
                if "scales" in command:
                    extra_channels.append([fb(v) for v in command["scales"]])
                if "twists" in command:
                    if "scales" not in command:
                        # The channel order is positional: twists live in channel 4, so a
                        # document with twists but no scales must still send a scale channel.
                        raise NotImplementedComponent(
                            "meshPrimitive3D sweep: 'twists' requires 'scales' "
                            "(channel order is positional)")
                    extra_channels.append([fb(v) for v in command["twists"]])
            elif kind == "extrudepath":
                # [depth, cx,cy,cz, bevel, contourCount, (count, x,y...)*]
                centre = command.get("center", [0, 0, 0])
                if len(centre) != 3:
                    raise NotImplementedComponent(
                        "meshPrimitive3D extrudePath: center needs 3 values")
                contours = command.get("contours")
                if not contours:
                    raise NotImplementedComponent(
                        "meshPrimitive3D extrudePath: missing 'contours'")
                scalars = [fb(command.get("depth", 1.0))] + [fb(v) for v in centre] \
                    + [fb(command.get("bevel", 0.0)), fb(len(contours))]
                for ring in contours:
                    scalars.append(fb(len(ring)))
                    for pt in ring:
                        if len(pt) != 2:
                            raise NotImplementedComponent(
                                "meshPrimitive3D extrudePath: contour points are [x, y] pairs")
                        scalars += [fb(pt[0]), fb(pt[1])]
            elif kind in _PRIMITIVE_PARAMS:
                scalars = []
                for key in _PRIMITIVE_PARAMS[kind]:
                    if key in ("center", "from", "to"):
                        vec = command.get(key, [0, 0, 0])
                        if len(vec) != 3:
                            raise NotImplementedComponent(
                                f"meshPrimitive3D {kind}: {key} needs 3 components")
                        scalars += [fb(v) for v in vec]
                    else:
                        if key not in command:
                            raise NotImplementedComponent(
                                f"meshPrimitive3D {kind}: missing {key!r} "
                                f"(needs {_PRIMITIVE_PARAMS[kind]})")
                        scalars.append(fb(command[key]))
            else:
                raise NotImplementedComponent(
                    f"meshPrimitive3D {kind}: pass an explicit \"params\" list")
            flags = int(command.get("flags", 0)) | flags_extra
            uvname = str(command.get("uv", "none")).lower()
            if uvname not in _UV_MODE:
                raise NotImplementedComponent(f"meshPrimitive3D uv {uvname!r}")
            flags |= _UV_MODE[uvname] << 4
            # Channels 1+ carry geometry streams: a lathe profile, a sweep cross-section/path.
            channels = [scalars] + extra_channels
            for extra in command.get("channels", []):
                channels.append([fb(v) for v in extra])
            if kind == "lathe" and "profile" in command:
                prof = []
                for pt in command["profile"]:
                    if len(pt) != 2:
                        raise NotImplementedComponent(
                            "meshPrimitive3D lathe: profile points are [radius, y] pairs")
                    prof += [fb(pt[0]), fb(pt[1])]
                channels.append(prof)
            w.mesh_primitive_3d(int(command["id"]), ptype,
                                fb(command.get("segments", 0)), flags, channels)
        elif ctype == "camera3d":
            proj_name = str(command.get("projection", "perspective")).lower()
            if proj_name not in _PROJECTION:
                raise NotImplementedComponent(f"camera3D projection {proj_name!r}")
            proj = _PROJECTION[proj_name]
            if proj == 0:
                proj_params = [fb(command.get("fovY", 0.9)), fb(command.get("aspect", 1.0)),
                               fb(command.get("near", 0.1)), fb(command.get("far", 100.0))]
            else:
                proj_params = [fb(command["left"]), fb(command["right"]),
                               fb(command["bottom"]), fb(command["top"]),
                               fb(command.get("near", 0.1)), fb(command.get("far", 100.0))]
            eye = command.get("eye", [0, 0, 4])
            center = command.get("center", [0, 0, 0])
            up = command.get("up", [0, 1, 0])
            view = [fb(v) for v in list(eye) + list(center) + list(up)]
            if len(view) != 9:
                raise NotImplementedComponent(
                    "camera3D needs eye/center/up of 3 components each")
            w.set_camera_3d(proj, proj_params, view)
        elif ctype == "matrix3d":
            # A matrix3D with no "op" used to default to identity and ignore whatever else
            # was there, so {"translate": [x, y, z]} silently emitted identity and every
            # instance drew at the origin — which reads as a camera or a data bug, not a
            # syntax one. A bare {} is still identity; anything else has to name its op.
            if "op" not in command:
                extra = sorted(k for k in command if k not in ("type",))
                if extra:
                    raise NotImplementedComponent(
                        f"matrix3D needs an \"op\" (identity/translate/scale/rotate/multiply); "
                        f"got keys {extra}")
            sub_name = str(command.get("op", "identity")).lower()
            if sub_name not in _MATRIX_SUB:
                raise NotImplementedComponent(f"matrix3D op {sub_name!r}")
            sub = _MATRIX_SUB[sub_name]
            if sub == 0:
                args = []
            elif sub in (1, 2):
                args = [fb(command.get("x", 0)), fb(command.get("y", 0)),
                        fb(command.get("z", 0))]
            elif sub == 3:
                axis = command.get("axis", [0, 1, 0])
                args = [fb(command["angle"])] + [fb(v) for v in axis]
                if len(args) != 4:
                    raise NotImplementedComponent("matrix3D rotate axis needs 3 components")
            else:
                m = command["m"]
                if len(m) != 16:
                    raise NotImplementedComponent(
                        f"matrix3D multiply needs 16 floats, got {len(m)}")
                args = [fb(v) for v in m]
            w.matrix_3d_op(sub, args)
        elif ctype == "drawmesh3d":
            w.draw_mesh_3d(int(command["mesh"]), _mesh_mode(command))
        elif ctype == "cleardepth3d":
            w.paint_3d_state(_P3_CLEAR_DEPTH, [])
        elif ctype == "material3d":
            w.paint_3d_state(_P3_MATERIAL, [fb(command.get("specular", 0.0)),
                                            fb(command.get("shininess", 32.0))])
        elif ctype == "depthbias3d":
            w.paint_3d_state(_P3_DEPTH_BIAS, [fb(command.get("constant", 0.0)),
                                              fb(command.get("slope", 0.0))])
        elif ctype == "lights3d":
            types, colors, params = [], [], []
            for light in command.get("lights", []):
                tname = str(light.get("type", "directional")).lower()
                if tname not in _LIGHT_TYPE:
                    raise NotImplementedComponent(f"lights3D type {tname!r}")
                ltype = _LIGHT_TYPE[tname]
                types.append(ltype)
                colors.append(_to_int32(parse_color(light.get("color", "#FFFFFFFF"))))
                vec = light.get("pos") if ltype == 1 else light.get("dir")
                if vec is None or len(vec) != 3:
                    what = "pos" if ltype == 1 else "dir"
                    raise NotImplementedComponent(f"lights3D {tname} needs a 3-component {what}")
                params += [fb(v) for v in vec] + [fb(light.get("intensity", 1.0))]
            w.set_lights_3d(types, colors, params)
        elif ctype == "texture3d":
            # 0 clears the texture; a name resolves against resources.bitmaps.
            bitmap = command.get("bitmap", 0)
            w.set_texture_3d(0 if bitmap in (0, None) else self._bitmap_id(bitmap))
        else:
            raise NotImplementedComponent(f"canvas command {ctype!r}")

    def _parse_path(self, path_str: str) -> int:
        if path_str in self.paths:
            return self.paths[path_str]
        if path_str.startswith("$paths.") or path_str.startswith("@paths."):
            name = path_str[7:]
            if name not in self.paths:
                raise NotImplementedComponent(f"Path not found: {name}")
            return self.paths[name]
        # No caching by string: addPathString parses to a fresh float[] every call and
        # mState.cacheData keys on that array, so two identical path strings each get
        # their own id and their own DATA_PATH op.
        return self.writer.add_path_data(parse_svg_path(path_str))

    def _parse_variable(self, command: dict) -> None:
        """Define a named float variable (the common float case with commit/flush)."""
        name = command["name"]
        vtype = command.get("vtype", "float")
        commit = command.get("commit", False)
        flush = command.get("flush", False)
        named = command.get("export", False)
        if vtype == "color":
            if not (commit or flush):
                raise NotImplementedComponent("deferred color variable TBD")
            color_val = parse_color(command["value"])
            cid = self.writer.add_named_color(name, color_val) if named else self.writer.add_color(color_val)
            self.variables[name] = W.float_to_raw_int_bits(float(cid))   # (float)colorId
            return
        if vtype != "float":
            raise NotImplementedComponent(f"variable vtype {vtype!r} (string/path/floatArrays TBD)")
        if named:
            raise NotImplementedComponent("named/export float variable TBD")
        if not (self.in_first_pass or commit or flush):
            # Not written here — recorded and emitted at first use. See _VariableMap.
            self.variables.defer(name, command)
            return
        if flush:
            raise NotImplementedComponent("flush variable TBD")
        if self.variables.is_materialised(name):
            raise NotImplementedComponent("variable reassignment (targetId) TBD")
        dict.__setitem__(self.variables, name, self._materialise_float_var(command))

    def _materialise_float_var(self, command: dict) -> int:
        """Emit a float variable's ops and return its bits. Shared by the immediate path
        and by deferred resolution, so both produce the same encoding."""
        val = command["value"]
        if isinstance(val, bool):
            raise NotImplementedComponent("boolean variable value")
        if isinstance(val, (int, float)):
            return self.writer.add_float_constant(float(val))   # numeric → FloatConstant op
        if isinstance(val, str):
            return self._fbits(val)                             # expression / ref → FloatExpression
        if isinstance(val, dict):
            if str(val.get("type", "")) in ("textFromFloat", "textMerge"):
                raise NotImplementedComponent(f"variable value {val.get('type')!r} TBD")
            return self._fbits(val)                             # animated expression {value, anim}
        raise NotImplementedComponent(f"variable value type {type(val)}")

    def _resolve_deferred(self, name: str) -> int:
        """Materialise a deferred variable at its first use (resolveDeferredVariable).

        Removed from the deferred map before materialising, so a self-referencing
        expression fails as an unknown name rather than recursing forever.
        """
        command = self.variables.deferred.pop(name)
        bits = self._materialise_float_var(command)
        dict.__setitem__(self.variables, name, bits)
        return bits

    def _parse_text(self, component: dict, mods: list) -> None:
        # RemoteComposeBuffer picks the text op from the profile's operation map:
        # CoreText (239) when CORE_TEXT is enabled, TextLayout (208) as a backstop when
        # it is not. A document with no `profiles` header tag gets the baseline map and
        # therefore the backstop, which has a different field layout — we only emit
        # CoreText, so refuse rather than produce a plausible-looking wrong document.
        if not self.profiles:
            raise NotImplementedComponent(
                "text without a `profiles` header tag — the reference falls back to the "
                "TextLayout op (208) instead of CoreText (239), which rcj does not emit; "
                "add \"profiles\": 512 (or 513) to the header")
        w = self.writer
        value = component.get("value")
        tff = component.get("textFromFloat")
        # Mirror RemoteComposeJsonParser.parseText: a literal `value` wins; otherwise a
        # `textFromFloat` object binds the text to a live float value.
        if value is not None:
            # The official parser treats a value starting with $ or @ as a variable/
            # resource reference (resolveTextId), not literal text. Not supported yet.
            if isinstance(value, str) and (value.startswith("$") or value.startswith("@")):
                raise NotImplementedComponent(f"text variable/resource reference {value!r}")
            text_id = w.add_text(str(value))
        elif isinstance(tff, dict):
            # The current parser emits the TextFromFloat op whenever the key is present.
            # (It used to guard on `!Float.isNaN(textFromFloat)`, which silently dropped
            # every *expression* value — expression ids are themselves NaN-encoded — so
            # a document like 24_textfromfloat_expr rendered nothing. Fixed upstream.)
            value_bits = self._fbits(tff.get("value"))
            before = int(tff.get("whole", 0))
            after = int(tff.get("decimal", 0))
            flags = int(tff.get("flags", 0))
            text_id = w.add_text_from_float(value_bits, before, after, flags)
        else:
            raise NotImplementedComponent("text without value or textFromFloat")

        color = 0xFF000000
        color_id = -1
        color_obj = component.get("color")
        if isinstance(color_obj, str) and (color_obj.startswith("$colors.") or color_obj.startswith("@colors.")):
            color_id = self._color(color_obj)
        elif color_obj is not None:
            color = self._color(color_obj)   # literal hex or $var colorId

        max_lines = int(component.get("maxLines", _INT_MAX))
        overflow_str = str(component.get("overflow", "clip")).lower()
        overflow = {"clip": 1, "ellipsis": 3, "visible": 2,
                    "start_ellipsis": 4, "middle_ellipsis": 5}.get(overflow_str, 1)

        font_size_bits = (self._fbits(component["fontSize"]) if "fontSize" in component
                          else W.float_to_raw_int_bits(36.0))   # DEFAULT_FONT_SIZE
        font_weight_bits = (self._fbits(component["fontWeight"]) if "fontWeight" in component
                            else W.float_to_raw_int_bits(400.0))
        text_align = parse_text_align(str(component.get("textAlign", "start")))

        w.text_component(text_id, color=color, color_id=color_id, font_size_bits=font_size_bits,
                         font_weight_bits=font_weight_bits, text_align=text_align,
                         overflow=overflow, max_lines=max_lines, modifiers=mods)
