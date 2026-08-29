"""Header op (opcode 0) — byte-identical port of remote-core Header.apply (apiLevel >= 7).

Wire layout (Header.java:apply tag-based):
    start(HEADER=0)
    writeInt(MAJOR_VERSION | MAGIC_NUMBER)   # 1 | 0x048C0000 = 0x048C0001
    writeInt(MINOR_VERSION)                   # 1
    writeInt(PATCH_VERSION)                   # 0
    writeInt(tagCount)
    writeMap(tags)                            # each: writeShort(tag | dataType<<10), ...

DataType (Header.java): INT=0, FLOAT=1, LONG=2, STRING=3.

Header tag numbers (Header.java) and the JSON-key -> tag map
(RemoteComposeJsonParser.parseHeaderTagStatic):
    width               -> DOC_WIDTH=5            (int)
    height              -> DOC_HEIGHT=6           (int)
    desiredFPS / fps    -> DOC_DESIRED_FPS=8      (int)
    contentDescription  -> DOC_CONTENT_DESCRIPTION=9 (string)
    profiles            -> DOC_PROFILES=14        (int)
    featurePaintMeasure -> FEATURE_PAINT_MEASURE=15 (int)
    theme               -> TEST_COLOR_THEME=21    (int)
    ltResize            -> FEATURE_LT_RESIZE=24   (int)
    densityBehavior     -> DOC_DENSITY_BEHAVIOR=27(int)

apiLevel and orderedResources are NOT tags (special-cased by the parser).
The writer SORTS tags by tag number ascending before emitting.
"""

from __future__ import annotations

from .wire import WireBuffer

HEADER_OP = 0
MAGIC_NUMBER = 0x048C0000
MAJOR_VERSION = 1
MINOR_VERSION = 1
PATCH_VERSION = 0

DATA_TYPE_INT = 0
DATA_TYPE_FLOAT = 1
DATA_TYPE_LONG = 2
DATA_TYPE_STRING = 3

# JSON header key -> tag number (parseHeaderTagStatic).
HEADER_KEY_TO_TAG = {
    "width": 5,
    "height": 6,
    "desiredFPS": 8,
    "fps": 8,
    "contentDescription": 9,
    "profiles": 14,
    "featurePaintMeasure": 15,
    "debug": 16,
    "theme": 21,
    "ltResize": 24,
    "densityBehavior": 27,
}


def write_map(buffer: WireBuffer, tags: list[tuple[int, object]]) -> None:
    """Mirror Header.writeMap. `tags` is a list of (tag, value)."""
    for tag, value in tags:
        if isinstance(value, str):
            t = (tag | (DATA_TYPE_STRING << 10)) & 0xFFFF
            buffer.write_short(t)
            data = value.encode("utf-8")
            buffer.write_short(len(data) + 4)
            buffer.write_buffer(data)
        elif isinstance(value, bool):
            # bool is an int in Python; the Java path has no Boolean branch, so a
            # bool would be ignored there. Treat as int to stay explicit.
            t = (tag | (DATA_TYPE_INT << 10)) & 0xFFFF
            buffer.write_short(t)
            buffer.write_short(4)
            buffer.write_int(1 if value else 0)
        elif isinstance(value, int):
            t = (tag | (DATA_TYPE_INT << 10)) & 0xFFFF
            buffer.write_short(t)
            buffer.write_short(4)
            buffer.write_int(value)
        elif isinstance(value, float):
            t = (tag | (DATA_TYPE_FLOAT << 10)) & 0xFFFF
            buffer.write_short(t)
            buffer.write_short(4)
            buffer.write_float(value)
        else:
            raise ValueError(f"unsupported header value type for tag {tag}: {type(value)}")


def apply(buffer: WireBuffer, api_level: int, tags: list[tuple[int, object]]) -> None:
    """Emit the Header op. `tags` already (tag, value); will be sorted by tag here."""
    if api_level < 7:
        raise NotImplementedError("only apiLevel >= 7 is implemented")
    ordered = sorted(tags, key=lambda tv: tv[0])
    buffer.start(HEADER_OP)
    buffer.write_int(MAJOR_VERSION | MAGIC_NUMBER)
    buffer.write_int(MINOR_VERSION)
    buffer.write_int(PATCH_VERSION)
    buffer.write_int(len(ordered))
    write_map(buffer, ordered)
