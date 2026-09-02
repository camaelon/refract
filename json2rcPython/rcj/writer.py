"""RemoteComposeWriter — byte-identical port (layout + text + draw).

Mirrors remote-creation-core/.../RemoteComposeWriter.java and the remote-core Operation
encoders. The constructor emits the Header op; component/modifier/text/draw methods append
ops, each verified byte-identical against the oracle.

ID allocation (authoritative):
  - component ids: counter starts at -1, PRE-decrement -> first id is -2, then -3, ...
    shared by every container start, every content-start, and every text component.
  - data ids (text/colors/...): counter starts at 42, POST-increment -> 42, 43, ...
    text is deduped by value (identical strings reuse the id, emit no DATA_TEXT).
"""

from __future__ import annotations

import math
import struct

from . import header as _header
from .wire import WireBuffer

# Opcodes (Operations.java)
LAYOUT_ROOT = 200
LAYOUT_CONTENT = 201
LAYOUT_BOX = 202
LAYOUT_ROW = 203
LAYOUT_COLUMN = 204
LAYOUT_CANVAS = 205
LAYOUT_CANVAS_CONTENT = 207
LAYOUT_FLOW = 240
LAYOUT_COLLAPSIBLE_COLUMN = 233
LAYOUT_COLLAPSIBLE_ROW = 230
LAYOUT_FIT_BOX = 176
CONTAINER_END = 214
INT_MAX = 2147483647
DATA_BITMAP = 101
DATA_TEXT = 102
TEXT_FROM_FLOAT = 135
CORE_TEXT = 239
MODIFIER_WIDTH = 16
MODIFIER_HEIGHT = 67
MODIFIER_BACKGROUND = 55
MODIFIER_PADDING = 58
MODIFIER_OFFSET = 221
ACCESSIBILITY_SEMANTICS = 250
MODIFIER_CLICK = 59
MODIFIER_VISIBILITY = 211
MODIFIER_CLIP_RECT = 108
MODIFIER_SCROLL = 226
HOST_NAMED_ACTION = 210
VALUE_FLOAT_EXPRESSION_CHANGE_ACTION = 227
VALUE_INTEGER_CHANGE_ACTION = 212
VALUE_STRING_CHANGE_ACTION = 213
VALUE_INTEGER_EXPRESSION_CHANGE_ACTION = 218
VALUE_FLOAT_CHANGE_ACTION = 222
HOST_ACTION_STRING_TYPE = 2
SEMANTICS_MODE_SET = 0
MODIFIER_BORDER = 107
MODIFIER_WIDTH_IN = 231
MODIFIER_HEIGHT_IN = 232
MODIFIER_ROUNDED_CLIP_RECT = 54
DATA_FLOAT = 80
ANIMATED_FLOAT = 81
NAMED_VARIABLE = 137
COLOR_CONSTANT = 138
FLOAT_LIST = 147
NV_FLOAT_TYPE = 1
NV_COLOR_TYPE = 2
NV_FLOAT_ARRAY_TYPE = 6
BG_COLOR_REF = 2
START_ARRAY = (2 << 20) + 42      # NanMap.START_ARRAY — separate id counter for arrays
COMPONENT_VALUE = 150
CV_WIDTH = 0
CV_HEIGHT = 1
LOOP_START = 215
CONDITIONAL_OPERATIONS = 178
PAINT_VALUES = 40
DRAW_RECT = 42
DRAW_TEXT_RUN = 43
DRAW_CIRCLE = 46
DRAW_LINE = 47
DRAW_OVAL = 56
DRAW_ROUND_RECT = 51
DRAW_ARC = 152
DRAW_SECTOR = 52
IMPULSE_START = 164
IMPULSE_PROCESS = 165
DRAW_TEXT_ANCHOR = 133
DRAW_PATH = 124
DATA_PATH = 123
PATH_CREATE = 159
PATH_EXPRESSION = 193
PARTICLE_DEFINE = 161
PARTICLE_LOOP = 163
PARTICLE_COMPARE = 194
PLAY_SOUND = 141
DATA_SOUND = 169
SOUND_EXPRESSION = 206
REM = 185

# ---- 3D (in review as ag/4108133) -----------------------------------------------------------
# Ten ops, registered in the experimental profiles. Every float below may be a NaN-boxed
# variable id, which is what makes these reactive rather than a static mesh format.
DEFINE_MESH_3D = 110
SET_CAMERA_3D = 111
MATRIX_3D_OP = 112
DRAW_MESH_3D = 113
PAINT_3D_STATE = 114
SET_LIGHTS_3D = 115
VECTOR_EXPRESSION = 116
TOUCH_EXPRESSION = 157
MESH_EXPRESSION_3D = 117
SET_TEXTURE_3D = 118
MESH_PRIMITIVE_3D = 120
PATH_APPEND = 160
PATH_LINE = 11
PATH_CLOSE = 15
CLIP_RECT = 39
MATRIX_SCALE = 126
MATRIX_TRANSLATE = 127
MATRIX_ROTATE = 129
MATRIX_SAVE = 130
MATRIX_RESTORE = 131

# PaintBundle command constants (PaintBundle.java)
PB_TEXT_SIZE = 1
PB_COLOR = 4
PB_STROKE_WIDTH = 5
PB_STROKE_CAP = 7
PB_STYLE = 8
PB_SHADER = 9
PB_GRADIENT = 11
PB_ALPHA = 12
PB_STROKE_JOIN = 15
PB_TYPEFACE = 16
PB_COLOR_ID = 19
PB_PATH_EFFECT = 25
# PaintBundle TYPEFACE fontType values (PaintBundle.java) — canvas text font family.
FONT_TYPE_DEFAULT = 0
FONT_TYPE_SANS_SERIF = 1
FONT_TYPE_SERIF = 2
FONT_TYPE_MONOSPACE = 3
# PaintPathEffects type tags (written as raw int bits inside the effect payload).
PPE_DASH = 1
GRAD_LINEAR = 0
GRAD_SWEEP = 2


def float_to_raw_int_bits(f: float) -> int:
    return struct.unpack(">i", struct.pack(">f", f))[0]


NAN_BITS = 0x7FC00000  # canonical float32 NaN bits (writeFloat(Float.NaN))


def as_nan_bits(v: int) -> int:
    """Raw int32 bits of Utils.asNan(v) = intBitsToFloat(v | 0xFF800000)."""
    return (v | 0xFF800000) & 0xFFFFFFFF

NAN = float("nan")

# CoreText parameter ids (TextStyle / CommandParameters), in WRITE ORDER with (id, type, default).
# type: 'i' int, 'f' float, 'b' bool.
_INT_MAX = 2147483647
CORE_TEXT_PARAMS = [
    ("id", 1, "i", -1),
    ("animationId", 2, "i", -1),
    ("color", 3, "i", 0xFF000000),
    ("colorId", 4, "i", -1),
    ("fontSize", 5, "f", 36.0),   # TextStyle.DEFAULT_FONT_SIZE
    ("minFontSize", 25, "f", -1.0),
    ("maxFontSize", 26, "f", -1.0),
    ("fontStyle", 6, "i", 0),
    ("fontWeight", 7, "f", 400.0),
    ("fontFamily", 8, "i", -1),
    ("textAlign", 9, "i", 1),
    ("overflow", 10, "i", 1),
    ("maxLines", 11, "i", _INT_MAX),
    ("letterSpacing", 12, "f", 0.0),
    ("lineHeightAdd", 13, "f", 0.0),
    ("lineHeightMultiplier", 14, "f", 1.0),
    ("lineBreakStrategy", 15, "i", 0),
    ("hyphenationFrequency", 16, "i", 0),
    ("justificationMode", 17, "i", 0),
    ("underline", 18, "b", False),
    ("strikethrough", 19, "b", False),
    ("autosize", 22, "b", False),
    ("flags", 23, "i", 0),
    ("parentId", 24, "i", -1),
]


def _to_int32(v: int) -> int:
    v &= 0xFFFFFFFF
    return v - 0x100000000 if v >= 0x80000000 else v


class RemoteComposeWriter:
    def __init__(self, api_level: int, tags: list[tuple[int, object]]) -> None:
        self.api_level = api_level
        self.buffer = WireBuffer()
        self._component_id = -1          # pre-decrement; first alloc -> -2
        # RemoteComposeBuffer.mLastComponentId: 0 until a component is actually started.
        # A `resources` block hoisted into a `global` section runs *before* any component
        # exists, so `width`/`height` there resolve against component 0, not against the
        # not-yet-allocated first component.
        self._last_component_id = 0
        self._next_data_id = 42          # post-increment; first alloc -> 42
        self._next_array_id = START_ARRAY
        self._text_cache: dict[str, int] = {}
        self._tff_cache: dict[tuple[int, int, int, int], int] = {}
        self._component_value_cache: dict[tuple[int, int], int] = {}
        self._insert_point = -1          # where hoisted global sections land
        self._start_global_section = -1
        _header.apply(self.buffer, api_level, tags)

    def encode_to_byte_array(self) -> bytes:
        return self.buffer.to_bytes()

    # ── id allocation ────────────────────────────────────────────────────────

    def alloc_component_id(self) -> int:
        self._component_id -= 1
        self._last_component_id = self._component_id
        return self._component_id

    def alloc_data_id(self) -> int:
        v = self._next_data_id
        self._next_data_id += 1
        return v

    # ── containers ───────────────────────────────────────────────────────────

    # ── global sections (hoisted ahead of the root) ──────────────────────────

    def begin_global(self) -> None:
        if self._start_global_section != -1:
            raise RuntimeError("Trying to start a global section twice")
        if self._insert_point == -1:
            self._insert_point = self.buffer.index
        self._start_global_section = self.buffer.index

    def end_global(self) -> None:
        if self._start_global_section == -1:
            raise RuntimeError("Trying to end a global section without a begin")
        size = self.buffer.index - self._start_global_section
        self.buffer.move_block(self._start_global_section, self._insert_point)
        if self._insert_point != -1:
            self._insert_point += size
        self._start_global_section = -1

    def root_start(self) -> None:
        if self._insert_point == -1:
            self._insert_point = self.buffer.index
        self.buffer.start(LAYOUT_ROOT)
        self.buffer.write_int(self.alloc_component_id())

    def container_end(self) -> None:
        self.buffer.start(CONTAINER_END)

    def content_start(self) -> None:
        self.buffer.start(LAYOUT_CONTENT)
        self.buffer.write_int(self.alloc_component_id())

    def _container_with_align(self, op: int, horizontal: int, vertical: int,
                              spaced_by: float | None, modifiers: list) -> None:
        cid = self.alloc_component_id()
        self.buffer.start(op)
        self.buffer.write_int(cid)
        self.buffer.write_int(-1)            # animationId
        self.buffer.write_int(horizontal)
        self.buffer.write_int(vertical)
        if spaced_by is not None:
            self.buffer.write_float(spaced_by)
        for m in modifiers:
            m(self)
        self.content_start()

    def start_column(self, horizontal: int, vertical: int, modifiers: list,
                     spaced_by: float = 0.0) -> None:
        self._container_with_align(LAYOUT_COLUMN, horizontal, vertical, spaced_by, modifiers)

    def end_column(self) -> None:
        self.container_end()
        self.container_end()

    def start_row(self, horizontal: int, vertical: int, modifiers: list,
                  spaced_by: float = 0.0) -> None:
        self._container_with_align(LAYOUT_ROW, horizontal, vertical, spaced_by, modifiers)

    def end_row(self) -> None:
        self.container_end()
        self.container_end()

    def start_box(self, horizontal: int, vertical: int, modifiers: list) -> None:
        # Box has no spacedBy field.
        self._container_with_align(LAYOUT_BOX, horizontal, vertical, None, modifiers)

    def end_box(self) -> None:
        self.container_end()
        self.container_end()

    def box_leaf(self, horizontal: int, vertical: int, modifiers: list) -> None:
        """A childless box: BoxStart, modifiers, one ContainerEnd.

        Not startBox+endBox with nothing between — that form also writes a content-start
        and so closes twice. The leaf form has no content op at all, and upstream
        defaults its alignment to centre/centre where the container form defaults to
        start/top.
        """
        cid = self.alloc_component_id()
        self.buffer.start(LAYOUT_BOX)
        self.buffer.write_int(cid)
        self.buffer.write_int(-1)            # animationId
        self.buffer.write_int(horizontal)
        self.buffer.write_int(vertical)
        for m in modifiers:
            m(self)
        self.container_end()

    def start_collapsible_column(self, horizontal: int, vertical: int, modifiers: list,
                                 spaced_by: float = 0.0) -> None:
        self._container_with_align(LAYOUT_COLLAPSIBLE_COLUMN, horizontal, vertical, spaced_by, modifiers)

    def start_collapsible_row(self, horizontal: int, vertical: int, modifiers: list,
                              spaced_by: float = 0.0) -> None:
        self._container_with_align(LAYOUT_COLLAPSIBLE_ROW, horizontal, vertical, spaced_by, modifiers)

    def start_fit_box(self, horizontal: int, vertical: int, modifiers: list) -> None:
        self._container_with_align(LAYOUT_FIT_BOX, horizontal, vertical, None, modifiers)

    def end_collapsible_column(self) -> None:
        self.container_end(); self.container_end()

    def end_collapsible_row(self) -> None:
        self.container_end(); self.container_end()

    def end_fit_box(self) -> None:
        self.container_end(); self.container_end()

    def start_flow(self, horizontal: int, vertical: int, modifiers: list,
                   max_items: int, spaced_by: float = 0.0) -> None:
        cid = self.alloc_component_id()
        self.buffer.start(LAYOUT_FLOW)
        self.buffer.write_int(cid)
        self.buffer.write_int(-1)            # animationId
        self.buffer.write_int(horizontal)
        self.buffer.write_int(vertical)
        self.buffer.write_float(spaced_by)
        self.buffer.write_int(max_items)
        self.buffer.write_int(INT_MAX)       # maxLines
        for m in modifiers:
            m(self)
        self.content_start()

    def end_flow(self) -> None:
        self.container_end(); self.container_end()

    # ── text ─────────────────────────────────────────────────────────────────

    def add_text(self, s: str) -> int:
        """Intern a string -> data id, emitting DATA_TEXT once per unique value."""
        if s in self._text_cache:
            return self._text_cache[s]
        data_id = self.alloc_data_id()
        self.buffer.start(DATA_TEXT)
        self.buffer.write_int(data_id)
        self.buffer.write_utf8(s)
        self._text_cache[s] = data_id
        return data_id

    def add_text_from_float(self, value_bits: int, before: int, after: int,
                            flags: int) -> int:
        """Emit a TEXT_FROM_FLOAT op (a text id whose string is a live float value
        formatted with `before`/`after` digits). Port of RemoteComposeWriter.
        createTextFromFloat: a data id from the shared pool, deduped per
        (value, before, after, flags). `value_bits` are float32 bits (a literal or
        a NaN-encoded expression id), written raw so expression ids survive.
        See TextFromFloat.apply(): int(textId), float(value), int(before<<16|after),
        int(flags)."""
        key = (value_bits, before, after, flags)
        if key in self._tff_cache:
            return self._tff_cache[key]
        data_id = self.alloc_data_id()
        self.buffer.start(TEXT_FROM_FLOAT)
        self.buffer.write_int(data_id)
        self.buffer.write_int_bits_as_float(value_bits)
        self.buffer.write_int(((before & 0xFFFF) << 16) | (after & 0xFFFF))
        self.buffer.write_int(flags)
        self._tff_cache[key] = data_id
        return data_id

    def text_component(self, text_id: int, *, color: int, color_id: int, font_size_bits: int,
                       font_weight_bits: int, text_align: int, overflow: int, max_lines: int,
                       modifiers: list) -> None:
        cid = self.alloc_component_id()
        fb = float_to_raw_int_bits
        # Float params are held as raw float32 BITS so an expression result (NaN id)
        # survives; literal bits == floatToRawIntBits(literal) so output is unchanged.
        values = {
            "id": cid, "animationId": -1, "color": color, "colorId": color_id,
            "fontSize": font_size_bits, "minFontSize": fb(-1.0), "maxFontSize": fb(-1.0),
            "fontStyle": 0, "fontWeight": font_weight_bits, "fontFamily": -1,
            "textAlign": text_align, "overflow": overflow, "maxLines": max_lines,
            "letterSpacing": fb(0.0), "lineHeightAdd": fb(0.0), "lineHeightMultiplier": fb(1.0),
            "lineBreakStrategy": 0, "hyphenationFrequency": 0, "justificationMode": 0,
            "underline": False, "strikethrough": False, "autosize": False,
            "flags": 0, "parentId": -1,
        }
        emit = []
        for (name, tag, typ, default) in CORE_TEXT_PARAMS:
            v = values[name]
            if typ == "f":
                if v != fb(default):
                    emit.append((tag, "f", v))
            elif typ == "b":
                if bool(v) != bool(default):
                    emit.append((tag, "b", v))
            else:  # int
                if _to_int32(int(v)) != _to_int32(int(default)):
                    emit.append((tag, "i", v))
        self.buffer.start(CORE_TEXT)
        self.buffer.write_int(text_id)
        self.buffer.write_short(len(emit))
        for tag, typ, value in emit:
            self.buffer.write_byte(tag)
            if typ == "b":
                self.buffer.write_byte(1 if value else 0)
            else:  # "i" or "f" are both raw 32-bit values
                self.buffer.write_int(value)
        for m in modifiers:
            m(self)
        self.content_start()
        self.container_end()
        self.container_end()

    # ── canvas + draw ops ────────────────────────────────────────────────────

    def start_canvas(self, modifiers: list) -> None:
        cid = self.alloc_component_id()
        self.buffer.start(LAYOUT_CANVAS)
        self.buffer.write_int(cid)
        self.buffer.write_int(-1)            # animationId
        for m in modifiers:
            m(self)
        self.content_start()
        if self.api_level <= 7:
            cc = self.alloc_component_id()
            self.buffer.start(LAYOUT_CANVAS_CONTENT)
            self.buffer.write_int(cc)

    def end_canvas(self) -> None:
        if self.api_level <= 7:
            self.container_end()
        self.container_end()
        self.container_end()

    def paint_values(self, ints: list[int]) -> None:
        self.buffer.start(PAINT_VALUES)
        self.buffer.write_int(len(ints))      # PaintBundle.writeBundle: mPos
        for v in ints:
            self.buffer.write_int(v)

    # Canvas float fields are written as raw float32 BITS so a value that is an
    # expression result (NaN-encoded id) survives intact. For a literal coord the
    # bits == floatToRawIntBits(coord), so write_int(bits) is identical to write_float.

    def float_expression(self, ops_bits: list[int], anim_floats: list[float] | None = None) -> int:
        """Emit a FloatExpression (ANIMATED_FLOAT) op; return its asNan(id) bits.

        `anim_floats` is the packed animation array (e.g. [duration]); None/[] = no animation.
        len = exprLen | (animLen << 16); ops written as raw bits, anim floats via writeFloat.
        """
        data_id = self.alloc_data_id()
        self.buffer.start(ANIMATED_FLOAT)
        self.buffer.write_int(data_id)
        n_anim = len(anim_floats) if anim_floats else 0
        self.buffer.write_int(len(ops_bits) | (n_anim << 16))
        for b in ops_bits:
            self.buffer.write_int(b)
        if anim_floats:
            for v in anim_floats:
                self.buffer.write_float(v)
        return as_nan_bits(data_id)

    def add_float_constant(self, value: float) -> int:
        """Emit a FloatConstant (DATA_FLOAT) op; return its asNan(id) bits."""
        data_id = self.alloc_data_id()
        self.buffer.start(DATA_FLOAT)
        self.buffer.write_int(data_id)
        self.buffer.write_float(value)
        return as_nan_bits(data_id)

    def add_color(self, color: int) -> int:
        """Emit a COLOR_CONSTANT op; return the raw color id (NOT NaN-encoded)."""
        color_id = self.alloc_data_id()
        self.buffer.start(COLOR_CONSTANT)
        self.buffer.write_int(color_id)
        self.buffer.write_int(color)
        return color_id

    def add_named_color(self, name: str, color: int) -> int:
        """COLOR_CONSTANT + NAMED_VARIABLE; return the color id."""
        color_id = self.add_color(color)
        self.buffer.start(NAMED_VARIABLE)
        self.buffer.write_int(color_id)
        self.buffer.write_int(NV_COLOR_TYPE)
        self.buffer.write_utf8(name)
        return color_id

    def add_float_array(self, values: list[float]) -> int:
        """Emit a FLOAT_LIST op (array counter); return the raw array id."""
        array_id = self._next_array_id
        self._next_array_id += 1
        self.buffer.start(FLOAT_LIST)
        self.buffer.write_int(array_id)
        self.buffer.write_int(len(values))
        for v in values:
            self.buffer.write_float(v)
        return array_id

    def add_modifier_scroll(self, direction: int, position_bits: int) -> None:
        """A scroll modifier and the touch expression that drives it.

        Mirrors RemoteComposeWriter.addModifierScroll: reserve two ids for the scroll extent
        and the notch extent, write the modifier, then a TouchExpression that *writes the
        caller's position variable* from the touch position, and close the container.

        The two reserved ids are never written to by this converter — the player fills them
        in once it knows the content size. Reserving them is still required, because their
        ids are baked into the modifier and everything allocated afterwards depends on the
        count.
        """
        max_bits = as_nan_bits(self.alloc_data_id())
        notch_max_bits = as_nan_bits(self.alloc_data_id())

        self.buffer.start(MODIFIER_SCROLL)
        self.buffer.write_int(direction)
        for b in (position_bits, max_bits, notch_max_bits):
            self.buffer.write_int_bits_as_float(b)

        # VERTICAL(0) scrolls with touch Y, HORIZONTAL with touch X. The expression is
        # `touch * -1`: dragging down moves the content up.
        touch_id = 14 if direction == 0 else 13          # FLOAT_TOUCH_POS_Y / _X
        mul = as_nan_bits(0x310000 + 3)                  # AnimatedFloatExpression MUL
        exp = [as_nan_bits(touch_id), float_to_raw_int_bits(-1.0), mul]
        self.touch_expression(
            float_to_raw_int_bits(0.0),   # default
            float_to_raw_int_bits(0.0),   # min
            max_bits,                     # max: the reserved extent
            0,                            # STOP_GENTLY
            float_to_raw_int_bits(0.0),   # velocity id
            3,                            # touch effects
            exp,
            data_id=(position_bits & 0x007FFFFF),
        )
        self.buffer.start(CONTAINER_END)

    def add_named_float(self, name: str, value: float) -> int:
        """A float constant the host can read and write by name; returns asNan(id) bits.

        The NAMED_VARIABLE goes *before* the constant here, which is the opposite order from
        `add_named_float_array` below. That is not an inconsistency to tidy up: upstream's
        addNamedFloat names the id first and then writes FloatConstant, while
        addNamedFloatArray writes the array first. Swapping either changes the bytes.
        """
        data_id = self.alloc_data_id()
        self.buffer.start(NAMED_VARIABLE)
        self.buffer.write_int(data_id)
        self.buffer.write_int(NV_FLOAT_TYPE)
        self.buffer.write_utf8(name)
        self.buffer.start(DATA_FLOAT)
        self.buffer.write_int(data_id)
        self.buffer.write_float(value)
        return as_nan_bits(data_id)

    def set_float_name(self, data_id: int, name: str) -> None:
        """Attach a name to a float that already exists — an expression, or a system id."""
        self.buffer.start(NAMED_VARIABLE)
        self.buffer.write_int(data_id)
        self.buffer.write_int(NV_FLOAT_TYPE)
        self.buffer.write_utf8(name)

    def add_named_float_array(self, name: str, values: list[float]) -> int:
        array_id = self.add_float_array(values)
        self.buffer.start(NAMED_VARIABLE)
        self.buffer.write_int(array_id)
        self.buffer.write_int(NV_FLOAT_ARRAY_TYPE)
        self.buffer.write_utf8(name)
        return array_id

    def add_component_value(self, value_type: int) -> int:
        """Component WIDTH/HEIGHT of the last component (ComponentValuesCache).

        Cached per (lastComponentId, type); emits COMPONENT_VALUE once, returns asNan(id) bits.
        """
        component_id = self._last_component_id  # getLastComponentId()
        key = (component_id, value_type)
        cached = self._component_value_cache.get(key)
        if cached is not None:
            return cached
        data_id = self.alloc_data_id()      # reserveFloatVariable()
        self.buffer.start(COMPONENT_VALUE)
        self.buffer.write_int(value_type)
        self.buffer.write_int(component_id)
        self.buffer.write_int(data_id)      # idFromNan(value)
        value = as_nan_bits(data_id)
        self._component_value_cache[key] = value
        return value

    def add_component_width_value(self) -> int:
        return self.add_component_value(CV_WIDTH)

    def add_component_height_value(self) -> int:
        return self.add_component_value(CV_HEIGHT)

    # ── 3D ──────────────────────────────────────────────────────────────────
    #
    # Floats are passed in as raw 32-bit patterns (the same convention as draw_circle et al),
    # so a NaN-boxed variable id survives to the wire untouched. write_int and write_float emit
    # identical bytes for the same bit pattern, so the payload matches the reference exactly.

    def _bits_array(self, bits: list[int]) -> None:
        self.buffer.write_int(len(bits))
        for b in bits:
            self.buffer.write_int(b)

    def define_mesh_3d(self, mesh_id: int, indices: list[int], verts: list[int],
                       normals: list[int] | None, uv: list[int] | None) -> None:
        self.buffer.start(DEFINE_MESH_3D)
        self.buffer.write_int(mesh_id)
        self.buffer.write_int(len(indices))
        for i in indices:
            self.buffer.write_int(i)
        self._bits_array(verts)
        # An absent optional channel is a zero length, not a missing field.
        self._bits_array(normals or [])
        self._bits_array(uv or [])

    def set_camera_3d(self, projection: int, proj_params: list[int],
                      view_params: list[int]) -> None:
        self.buffer.start(SET_CAMERA_3D)
        self.buffer.write_int(projection)
        self._bits_array(proj_params)
        self._bits_array(view_params)

    def matrix_3d_op(self, sub: int, args: list[int]) -> None:
        self.buffer.start(MATRIX_3D_OP)
        self.buffer.write_int(sub)
        self._bits_array(args)

    def draw_mesh_3d(self, mesh_id: int, mode: int) -> None:
        self.buffer.start(DRAW_MESH_3D)
        self.buffer.write_int(mesh_id)
        self.buffer.write_int(mode)

    def paint_3d_state(self, sub: int, params: list[int]) -> None:
        self.buffer.start(PAINT_3D_STATE)
        self.buffer.write_int(sub)
        self._bits_array(params)

    def set_lights_3d(self, types: list[int], colors: list[int], params: list[int]) -> None:
        self.buffer.start(SET_LIGHTS_3D)
        self.buffer.write_int(len(types))
        for t, c in zip(types, colors):
            self.buffer.write_int(t)
            self.buffer.write_int(c)
        self._bits_array(params)

    # BitmapData.TYPE_* / ENCODING_* (BitmapData.java)
    BITMAP_TYPE_PNG = 1
    BITMAP_ENCODING_INLINE = 0

    def add_bitmap(self, image_id: int, width: int, height: int, data: bytes,
                   type_: int = BITMAP_TYPE_PNG,
                   encoding: int = BITMAP_ENCODING_INLINE) -> int:
        """Emit DATA_BITMAP, the packed form.

        Width and height each share a word with a second field — type in the high half of
        the first, encoding in the high half of the second. The reader distinguishes this
        from the plain form by the high bits being set, which is why width and height must
        stay inside 16 bits: a 70000-pixel image would silently read back as a different
        type.
        """
        if not 0 <= width <= 0xFFFF or not 0 <= height <= 0xFFFF:
            raise ValueError(
                f"bitmap {width}x{height}: each dimension must fit in 16 bits, because the "
                f"wire format packs type and encoding into the high half of those words")
        self.buffer.start(DATA_BITMAP)
        self.buffer.write_int(image_id)
        self.buffer.write_int(((type_ & 0xFFFF) << 16) | (width & 0xFFFF))
        self.buffer.write_int(((encoding & 0xFFFF) << 16) | (height & 0xFFFF))
        self.buffer.write_buffer(data)
        return image_id

    def set_texture_3d(self, bitmap_id: int) -> None:
        self.buffer.start(SET_TEXTURE_3D)
        self.buffer.write_int(bitmap_id)

    def mesh_primitive_3d(self, mesh_id: int, ptype: int, segments: int, flags: int,
                          channels: list[list[int]]) -> None:
        self.buffer.start(MESH_PRIMITIVE_3D)
        self.buffer.write_int(mesh_id)
        self.buffer.write_int(ptype)
        self.buffer.write_int(segments)      # float bits (may be a variable)
        self.buffer.write_int(flags)
        self.buffer.write_int(len(channels))
        for ch in channels:
            self._bits_array(ch)

    def mesh_expression_3d(self, mesh_id: int, mtype: int, flags: int, params: list[int],
                           pos: list[list[int]], normal: list[list[int]],
                           uv: list[list[int]]) -> None:
        """MESH_EXPRESSION_3D: RPN expressions evaluated over a (u,v) grid on the player.

        Every float is a raw 32-bit pattern, because an expression element may be an operator or
        a variable reference encoded as a NaN payload — writing it as a decimal would destroy it.
        """
        self.buffer.start(MESH_EXPRESSION_3D)
        self.buffer.write_int(mesh_id)
        self.buffer.write_int(mtype)
        self.buffer.write_int(flags)
        self._bits_array(params)
        for group in (pos, normal, uv):
            self.buffer.write_int(len(group))
            for e in group:
                self._bits_array(e)

    def touch_expression(self, default_bits: int, min_bits: int, max_bits: int,
                         touch_mode: int, velocity_bits: int, touch_effects: int,
                         exp_bits: list[int], touch_spec: list[float] | None = None,
                         easing_spec: list[float] | None = None,
                         data_id: int | None = None) -> int:
        """Emit a TOUCH_EXPRESSION op; return its asNan(id) bits.

        Unlike `float_expression`, the value this defines *accumulates*: the expression maps a
        touch to a delta, and the op integrates it across drags, clamps it to [min, max] and —
        on release — coasts to a stop under `touch_mode`. A plain expression over `touchX()`
        cannot do any of that; it tracks the finger's absolute position and snaps back to the
        rest value the moment the finger lifts.

        `min` of NaN means wrap around `max` rather than clamp; `velocity_id` is a NaN-encoded
        id when set and NaN when unused. Both are why the four leading fields are passed as
        raw bits: writing them through struct.pack('>f') would erase the id payload, and NaN
        is a legitimate *value* here rather than an error.
        """
        # `data_id` lets the caller drive a variable that already exists — a scroll
        # modifier's touch expression writes the position variable the modifier was given.
        if data_id is None:
            data_id = self.alloc_data_id()
        self.buffer.start(TOUCH_EXPRESSION)
        self.buffer.write_int(data_id)
        for b in (default_bits, min_bits, max_bits, velocity_bits):
            self.buffer.write_int_bits_as_float(b)
        self.buffer.write_int(touch_effects)
        self.buffer.write_int(len(exp_bits))
        for b in exp_bits:
            # Expression elements are NaN-encoded ids; write the bits verbatim so the payload
            # survives. struct.pack('>f', nan) would not preserve it.
            self.buffer.write_int_bits_as_float(b)
        spec = touch_spec or []
        self.buffer.write_int(((touch_mode & 0xFFFF) << 16) | (len(spec) & 0xFFFF))
        for v in spec:
            self.buffer.write_float(v)
        easing = easing_spec or []
        self.buffer.write_int(len(easing))
        for v in easing:
            self.buffer.write_float(v)
        return as_nan_bits(data_id)

    def vector_expression(self, dimension: int, flags: int, ops_bits: list[int]) -> int:
        """Emit a VECTOR_EXPRESSION; return the base data id.

        The components land in consecutive scalar ids base..base+dimension-1, so the ids after
        the base are reserved here — handing one of them to another op would silently overwrite
        a component every frame.
        """
        base = self.alloc_data_id()
        for _ in range(dimension - 1):
            self.alloc_data_id()
        self.buffer.start(VECTOR_EXPRESSION)
        self.buffer.write_int(base)
        self.buffer.write_byte(dimension)
        self.buffer.write_byte(flags)
        self.buffer.write_short(len(ops_bits))
        for b in ops_bits:
            self.buffer.write_int(b)
        return base

    def create_particles(self, init_ops: list[list[int]], particle_count: int):
        """Emit a PARTICLE_DEFINE; return (system id, one data id per variable).

        The id order is load-bearing and mirrors RemoteComposeWriter.createParticles: the
        system's own id is allocated first, then one per variable, all before the op is
        written. Allocating them in any other order still produces a readable document, and
        every particle reads the wrong variable.
        """
        system_id = self.alloc_data_id()
        var_ids = [self.alloc_data_id() for _ in init_ops]
        self.buffer.start(PARTICLE_DEFINE)
        self.buffer.write_int(system_id)
        self.buffer.write_int(particle_count)
        self.buffer.write_int(len(var_ids))
        for vid, ops in zip(var_ids, init_ops):
            self.buffer.write_int(vid)
            self.buffer.write_int(len(ops))
            for b in ops:
                self.buffer.write_int(b)
        return system_id, var_ids

    def particles_loop_start(self, system_id: int, restart_ops: list[int] | None,
                             eq_ops: list[list[int]]) -> None:
        """Open a PARTICLE_LOOP. The body follows, then container_end().

        Only scalar equations are emitted. The op can also carry vector equations, flagged
        by (1 << 16) | len plus a dimension byte, but the reference JSON parser has no
        syntax for them, so there is nothing to mirror.
        """
        self.buffer.start(PARTICLE_LOOP)
        self.buffer.write_int(system_id)
        self.buffer.write_int(len(restart_ops) if restart_ops else 0)
        for b in (restart_ops or []):
            self.buffer.write_int(b)
        self.buffer.write_int(len(eq_ops))
        for ops in eq_ops:
            self.buffer.write_int(len(ops))
            for b in ops:
                self.buffer.write_int(b)

    def particles_compare_start(self, system_id: int, flags: int, min_bits: int, max_bits: int,
                                condition: list[int] | None,
                                then1: list[list[int]] | None,
                                then2: list[list[int]] | None) -> None:
        """Open a PARTICLE_COMPARE. The body follows, then container_end().

        Every particle in [min, max) is paired with every other, `condition` is evaluated
        for the pair, and then1/then2 update the first and second particle respectively.
        That is what collisions are built from.

        Note `flags` is a *short* here — the one field in the particle ops that is not an
        int — and an absent condition or equation list is a zero count, not an omission.
        """
        self.buffer.start(PARTICLE_COMPARE)
        self.buffer.write_int(system_id)
        self.buffer.write_short(flags)
        self.buffer.write_int(min_bits)
        self.buffer.write_int(max_bits)
        self.buffer.write_int(len(condition) if condition else 0)
        for b in (condition or []):
            self.buffer.write_int(b)
        for group in (then1, then2):
            self.buffer.write_int(len(group) if group else 0)
            for eq in (group or []):
                self.buffer.write_int(len(eq))
                for b in eq:
                    self.buffer.write_int(b)

    def add_sound(self, sound_id: int, data: bytes) -> int:
        """Emit DATA_SOUND: the id, then the audio bytes length-prefixed.

        No header is parsed, unlike a bitmap — the engine takes the bytes as they are.
        """
        self.buffer.start(DATA_SOUND)
        self.buffer.write_int(sound_id)
        self.buffer.write_buffer(data)
        return sound_id

    def sound_expression(self, sound_id: int, left_bits: int, right_bits: int,
                         rate_bits: int, params: list[int]) -> int:
        """Emit SOUND_EXPRESSION: a synthesised sound rather than a recorded one.

        The volumes and rate come before the parameter array, and each may be a NaN-boxed
        variable id — which is the point, since it lets a document modulate a tone.
        """
        self.buffer.start(SOUND_EXPRESSION)
        self.buffer.write_int(sound_id)
        for b in (left_bits, right_bits, rate_bits):
            self.buffer.write_int(b)
        self.buffer.write_int(len(params))
        for b in params:
            self.buffer.write_int(b)
        return sound_id

    def rem(self, message: str) -> None:
        """Emit REM (185): a remark that travels *in* the document.

        Unlike a `"//"` key in the JSON, which the converter drops, this one is written to
        the wire — so it survives into the .rc and comes back out of a disassembler. It has
        no visual effect; every player reads it and does nothing.
        """
        self.buffer.start(REM)
        self.buffer.write_utf8(message)

    def play_sound(self, sound_id: int) -> None:
        self.buffer.start(PLAY_SOUND)
        self.buffer.write_int(sound_id)

    def path_expression(self, flags: int, min_bits: int, max_bits: int, count_bits: int,
                        x_ops: list[int], y_ops: list[int] | None) -> int:
        """Emit a PATH_EXPRESSION; return the path id.

        The path is sampled `count` times with the parameter swept from `min` to `max`, and
        `a[0]` in either expression is that parameter. A null Y expression is written as a
        zero-length array, which is how the reference marks "X only".

        min/max/count go out as float32 *bits* rather than through write_float, because each
        may be a NaN-boxed variable id — the same reason draw_circle takes bits.
        """
        pid = self.alloc_data_id()
        self.buffer.start(PATH_EXPRESSION)
        self.buffer.write_int(pid)
        self.buffer.write_int(flags)
        for b in (min_bits, max_bits, count_bits):
            self.buffer.write_int(b)
        self.buffer.write_int(len(x_ops))
        for b in x_ops:
            self.buffer.write_int(b)
        self.buffer.write_int(len(y_ops) if y_ops else 0)
        for b in (y_ops or []):
            self.buffer.write_int(b)
        return pid

    def draw_circle(self, cx: int, cy: int, radius: int) -> None:
        self.buffer.start(DRAW_CIRCLE)
        for b in (cx, cy, radius):
            self.buffer.write_int(b)

    def draw_line(self, x1: int, y1: int, x2: int, y2: int) -> None:
        self.buffer.start(DRAW_LINE)
        for b in (x1, y1, x2, y2):
            self.buffer.write_int(b)

    def draw_rect(self, left: int, top: int, right: int, bottom: int) -> None:
        self.buffer.start(DRAW_RECT)
        for b in (left, top, right, bottom):
            self.buffer.write_int(b)

    def draw_oval(self, left: int, top: int, right: int, bottom: int) -> None:
        self.buffer.start(DRAW_OVAL)
        for b in (left, top, right, bottom):
            self.buffer.write_int(b)

    def add_path_data(self, floats: list) -> int:
        """Write a whole path as one DATA_PATH op and return its id (addPathData).

        Verb tags are NaN-encoded ids; coordinates are plain floats. Unlike
        path_append_*, this emits the path in a single op, which is what a path given as
        an SVG string compiles to.
        """
        path_id = self.alloc_data_id()
        self.buffer.start(DATA_PATH)
        self.buffer.write_int(path_id)
        self.buffer.write_int(len(floats))
        for v in floats:
            if isinstance(v, int):        # already raw bits (a NaN verb tag)
                self.buffer.write_int(v)
            else:
                self.buffer.write_int(float_to_raw_int_bits(float(v)))
        return path_id

    def path_create(self, x_bits: int, y_bits: int) -> int:
        path_id = self.alloc_data_id()
        self.buffer.start(PATH_CREATE)
        self.buffer.write_int(path_id)
        self.buffer.write_int(x_bits)
        self.buffer.write_int(y_bits)
        return path_id

    def path_append_line_to(self, path_id: int, x_bits: int, y_bits: int) -> None:
        self.buffer.start(PATH_APPEND)
        self.buffer.write_int(path_id)
        self.buffer.write_int(5)
        self.buffer.write_int(as_nan_bits(PATH_LINE))
        self.buffer.write_int(float_to_raw_int_bits(0.0))
        self.buffer.write_int(float_to_raw_int_bits(0.0))
        self.buffer.write_int(x_bits)
        self.buffer.write_int(y_bits)

    def path_append_close(self, path_id: int) -> None:
        self.buffer.start(PATH_APPEND)
        self.buffer.write_int(path_id)
        self.buffer.write_int(1)
        self.buffer.write_int(as_nan_bits(PATH_CLOSE))

    def draw_path(self, path_id: int) -> None:
        self.buffer.start(DRAW_PATH)
        self.buffer.write_int(path_id)

    # ── control flow ─────────────────────────────────────────────────────────

    def start_loop(self, index_id: int, from_bits: int, step_bits: int, until_bits: int) -> None:
        self.buffer.start(LOOP_START)
        self.buffer.write_int(index_id)
        for b in (from_bits, step_bits, until_bits):
            self.buffer.write_int(b)

    def end_loop(self) -> None:
        self.container_end()

    def conditional_operations(self, cond_type: int, a_bits: int, b_bits: int) -> None:
        self.buffer.start(CONDITIONAL_OPERATIONS)
        self.buffer.write_byte(cond_type)
        self.buffer.write_int(a_bits)
        self.buffer.write_int(b_bits)

    def end_conditional(self) -> None:
        self.container_end()

    def draw_text_anchored(self, text_id: int, x: int, y: int, pan_x: int, pan_y: int,
                           flags: int) -> None:
        self.buffer.start(DRAW_TEXT_ANCHOR)
        self.buffer.write_int(text_id)
        for b in (x, y, pan_x, pan_y):
            self.buffer.write_int(b)
        self.buffer.write_int(flags)

    def draw_text_run(self, text_id: int, start: int, end: int, ctx_start: int,
                      ctx_end: int, x: int, y: int, rtl: bool = False) -> None:
        """DRAW_TEXT_RUN (43) — draw glyphs [start,end) of a text at (x, baseline=y).

        No measuring: the run is drawn directly at the given left/baseline, which is
        what makes a canvas of positioned runs far cheaper than one Text component per
        span. x/y are raw float bits (may be NaN-encoded expression ids)."""
        self.buffer.start(DRAW_TEXT_RUN)
        for v in (text_id, start, end, ctx_start, ctx_end):
            self.buffer.write_int(v)
        self.buffer.write_int(x)
        self.buffer.write_int(y)
        self.buffer.write_boolean(rtl)

    def draw_round_rect(self, left: int, top: int, right: int, bottom: int,
                        rx: int, ry: int) -> None:
        self.buffer.start(DRAW_ROUND_RECT)
        for b in (left, top, right, bottom, rx, ry):
            self.buffer.write_int(b)

    def draw_arc(self, left: int, top: int, right: int, bottom: int,
                 start_angle: int, sweep_angle: int) -> None:
        self.buffer.start(DRAW_ARC)
        for b in (left, top, right, bottom, start_angle, sweep_angle):
            self.buffer.write_int(b)

    def impulse_start(self, duration_bits: int, start_bits: int) -> None:
        """IMPULSE_START (164) — a container; close it with container_end()."""
        self.buffer.start(IMPULSE_START)
        self.buffer.write_int(duration_bits)
        self.buffer.write_int(start_bits)

    def impulse_process_start(self) -> None:
        """IMPULSE_PROCESS (165) — a container with no payload."""
        self.buffer.start(IMPULSE_PROCESS)

    def draw_sector(self, left: int, top: int, right: int, bottom: int,
                    start_angle: int, sweep_angle: int) -> None:
        """DRAW_SECTOR (52) — same six floats as drawArc, but filled to the centre."""
        self.buffer.start(DRAW_SECTOR)
        for b in (left, top, right, bottom, start_angle, sweep_angle):
            self.buffer.write_int(b)

    # ── canvas transforms (matrix / clip) ────────────────────────────────────

    def matrix_save(self) -> None:
        self.buffer.start(MATRIX_SAVE)

    def matrix_restore(self) -> None:
        self.buffer.start(MATRIX_RESTORE)

    def translate(self, dx: int, dy: int) -> None:
        self.buffer.start(MATRIX_TRANSLATE)
        self.buffer.write_int(dx)
        self.buffer.write_int(dy)

    def rotate(self, angle: int, pivot_x: int = NAN_BITS, pivot_y: int = NAN_BITS) -> None:
        self.buffer.start(MATRIX_ROTATE)
        for b in (angle, pivot_x, pivot_y):
            self.buffer.write_int(b)

    def scale(self, sx: int, sy: int, pivot_x: int = NAN_BITS, pivot_y: int = NAN_BITS) -> None:
        self.buffer.start(MATRIX_SCALE)
        for b in (sx, sy, pivot_x, pivot_y):
            self.buffer.write_int(b)

    def clip_rect(self, left: int, top: int, right: int, bottom: int) -> None:
        self.buffer.start(CLIP_RECT)
        for b in (left, top, right, bottom):
            self.buffer.write_int(b)


# ── modifier emitters (each is `f(writer)`), built by the parser ─────────────
# Float values are passed as raw float32 BITS (literal or expression NaN id).

def mod_width(type_ordinal: int, value_bits: int):
    def emit(w: RemoteComposeWriter) -> None:
        w.buffer.start(MODIFIER_WIDTH)
        w.buffer.write_int(type_ordinal)
        w.buffer.write_int(value_bits)
    return emit


def mod_height(type_ordinal: int, value_bits: int):
    def emit(w: RemoteComposeWriter) -> None:
        w.buffer.start(MODIFIER_HEIGHT)
        w.buffer.write_int(type_ordinal)
        w.buffer.write_int(value_bits)
    return emit


def mod_background(color: int):
    a = ((color >> 24) & 0xFF) / 255.0
    r = ((color >> 16) & 0xFF) / 255.0
    g = ((color >> 8) & 0xFF) / 255.0
    b = (color & 0xFF) / 255.0

    def emit(w: RemoteComposeWriter) -> None:
        w.buffer.start(MODIFIER_BACKGROUND)
        w.buffer.write_int(0)   # flags
        w.buffer.write_int(0)   # colorId
        w.buffer.write_int(0)   # reserve1
        w.buffer.write_int(0)   # reserve2
        w.buffer.write_float(r)
        w.buffer.write_float(g)
        w.buffer.write_float(b)
        w.buffer.write_float(a)
        w.buffer.write_int(0)   # shapeType
    return emit


def mod_background_id(color_id: int):
    """Dynamic background referencing a color id (DynamicSolidBackgroundModifier)."""
    def emit(w: RemoteComposeWriter) -> None:
        w.buffer.start(MODIFIER_BACKGROUND)
        w.buffer.write_int(BG_COLOR_REF)   # flags
        w.buffer.write_int(color_id)
        w.buffer.write_int(0)              # reserve1
        w.buffer.write_int(0)              # reserve2
        w.buffer.write_float(0.0)          # r
        w.buffer.write_float(0.0)          # g
        w.buffer.write_float(0.0)          # b
        w.buffer.write_float(0.0)          # a
        w.buffer.write_int(0)              # shapeType
    return emit


def mod_click(actions, click_type: int = 0):
    """MODIFIER_CLICK (59) as a container: the op, then each action, then CONTAINER_END.

    click_type 0 writes the op with no payload — the single-int form is a different
    encoding upstream (addClickModifierOperation(type)), so do not merge the two.
    """
    def emit(w):
        w.buffer.start(MODIFIER_CLICK)
        if click_type != 0:
            w.buffer.write_int(click_type)
        for a in actions:
            a(w)
        w.buffer.start(CONTAINER_END)
    return emit


def mod_clip_rect():
    """MODIFIER_CLIP_RECT (108): clip to the component's own bounds. No payload."""
    def emit(w):
        w.buffer.start(MODIFIER_CLIP_RECT)
    return emit


def mod_scroll(direction: int, position_bits: int):
    def emit(w):
        w.add_modifier_scroll(direction, position_bits)
    return emit


def mod_visibility(value_id: int):
    """MODIFIER_VISIBILITY (211): the component is shown or hidden by a *variable*.

    The payload is the id of a float the document owns, not a constant — 0 hides, non-zero
    shows. That indirection is what makes filtering possible without a round trip: a click
    action sets the variable and every component reading it appears or disappears.
    """
    def emit(w):
        w.buffer.start(MODIFIER_VISIBILITY)
        w.buffer.write_int(value_id)
    return emit


def value_float_expression_change(target_id: int, value_id: int):
    """VALUE_FLOAT_EXPRESSION_CHANGE_ACTION (227): on click, set the target variable to the
    value of an expression.

    This is what lets a document hold its own state: a chip whose action is
    `{"target": "@d1", "value": "1 - @d1"}` toggles d1 between 0 and 1, and every element
    whose visibility reads d1 updates. No host code is involved.
    """
    def emit(w):
        w.buffer.start(VALUE_FLOAT_EXPRESSION_CHANGE_ACTION)
        w.buffer.write_int(target_id)
        w.buffer.write_int(value_id)
    return emit


def value_float_change(target_id: int, value_bits: int):
    """VALUE_FLOAT_CHANGE_ACTION (222): set the target to a *constant*.

    The sibling of value_float_expression_change, and the one to reach for when the new
    value does not depend on anything — no expression op is emitted at all.
    """
    def emit(w):
        w.buffer.start(VALUE_FLOAT_CHANGE_ACTION)
        w.buffer.write_int(target_id)
        w.buffer.write_int(value_bits)          # float32 bits, as everywhere else
    return emit


def value_integer_change(target_id: int, value: int):
    """VALUE_INTEGER_CHANGE_ACTION (212): set an integer variable to a constant."""
    def emit(w):
        w.buffer.start(VALUE_INTEGER_CHANGE_ACTION)
        w.buffer.write_int(target_id)
        w.buffer.write_int(value)
    return emit


def value_string_change(target_id: int, text_id: int):
    """VALUE_STRING_CHANGE_ACTION (213): point a string variable at another text id."""
    def emit(w):
        w.buffer.start(VALUE_STRING_CHANGE_ACTION)
        w.buffer.write_int(target_id)
        w.buffer.write_int(text_id)
    return emit


def value_integer_expression_change(target_id: int, value_id: int):
    """VALUE_INTEGER_EXPRESSION_CHANGE_ACTION (218): both fields are *longs*, not ints.

    The only action of the five with a 64-bit payload — integer expression ids are long —
    so writing it like its float sibling produces an op half the size the reader expects
    and desyncs everything after it.
    """
    def emit(w):
        w.buffer.start(VALUE_INTEGER_EXPRESSION_CHANGE_ACTION)
        w.buffer.write_long(target_id)
        w.buffer.write_long(value_id)
    return emit


def host_named_action(text_id: int, type_: int, value_id: int):
    """HOST_NAMED_ACTION (210): name text id, value type, value text id."""
    def emit(w):
        w.buffer.start(HOST_NAMED_ACTION)
        w.buffer.write_int(text_id)
        w.buffer.write_int(type_)
        w.buffer.write_int(value_id)
    return emit


def mod_semantics(content_description_id: int, role: int, text_id: int,
                  state_description_id: int, mode: int, enabled: bool, clickable: bool):
    """ACCESSIBILITY_SEMANTICS (250) — CoreSemantics.apply.

    Note the mixed widths: ints for the three text ids, bytes for role and mode, and
    booleans for the two flags. role is -1 when unset, not 0.
    """
    def emit(w):
        w.buffer.start(ACCESSIBILITY_SEMANTICS)
        w.buffer.write_int(content_description_id)
        w.buffer.write_byte(role & 0xFF)
        w.buffer.write_int(text_id)
        w.buffer.write_int(state_description_id)
        w.buffer.write_byte(mode)
        w.buffer.write_boolean(enabled)
        w.buffer.write_boolean(clickable)
    return emit


def mod_offset(x_bits: int, y_bits: int):
    """MODIFIER_OFFSET (221): two floats, either of which may be a NaN-boxed variable."""
    def emit(w):
        w.buffer.start(MODIFIER_OFFSET)
        w.buffer.write_int(x_bits)
        w.buffer.write_int(y_bits)
    return emit


def mod_padding(left_bits: int, top_bits: int, right_bits: int, bottom_bits: int):
    def emit(w: RemoteComposeWriter) -> None:
        w.buffer.start(MODIFIER_PADDING)
        for b in (left_bits, top_bits, right_bits, bottom_bits):
            w.buffer.write_int(b)
    return emit


def mod_border(width: float, corner: float, color: int, shape: int):
    a = ((color >> 24) & 0xFF) / 255.0
    r = ((color >> 16) & 0xFF) / 255.0
    g = ((color >> 8) & 0xFF) / 255.0
    b = (color & 0xFF) / 255.0

    def emit(w: RemoteComposeWriter) -> None:
        w.buffer.start(MODIFIER_BORDER)
        w.buffer.write_int(0); w.buffer.write_int(0); w.buffer.write_int(0); w.buffer.write_int(0)
        w.buffer.write_float(width)
        w.buffer.write_float(corner)
        w.buffer.write_float(r); w.buffer.write_float(g); w.buffer.write_float(b); w.buffer.write_float(a)
        w.buffer.write_int(shape)
    return emit


def mod_width_in(min_bits: int, max_bits: int):
    def emit(w: RemoteComposeWriter) -> None:
        w.buffer.start(MODIFIER_WIDTH_IN)
        w.buffer.write_int(min_bits)
        w.buffer.write_int(max_bits)
    return emit


def mod_height_in(min_bits: int, max_bits: int):
    def emit(w: RemoteComposeWriter) -> None:
        w.buffer.start(MODIFIER_HEIGHT_IN)
        w.buffer.write_int(min_bits)
        w.buffer.write_int(max_bits)
    return emit


def mod_clip_rounded_rect(top_start: float, top_end: float, bottom_start: float, bottom_end: float):
    def emit(w: RemoteComposeWriter) -> None:
        w.buffer.start(MODIFIER_ROUNDED_CLIP_RECT)
        for v in (top_start, top_end, bottom_start, bottom_end):
            w.buffer.write_float(v)
    return emit
