"""WireBuffer — byte-identical port of androidx remote-core WireBuffer write side.

All multi-byte values are big-endian, matching
remote-core/.../core/WireBuffer.java:
  writeShort  -> 2 bytes BE
  writeInt    -> 4 bytes BE
  writeLong   -> 8 bytes BE
  writeFloat  -> writeInt(floatToRawIntBits(value))   (IEEE-754 BE)
  writeDouble -> writeLong(doubleToRawLongBits(value))
  writeBuffer -> writeInt(len) followed by the raw bytes
  string      -> writeBuffer(utf8 bytes)
"""

from __future__ import annotations

import struct


class WireBuffer:
    def __init__(self) -> None:
        self._b = bytearray()

    # ── low-level primitives (mirror WireBuffer.java) ────────────────────────

    def write_byte(self, value: int) -> None:
        self._b.append(value & 0xFF)

    def write_boolean(self, value: bool) -> None:
        self._b.append(1 if value else 0)

    def write_short(self, value: int) -> None:
        self._b += (value & 0xFFFF).to_bytes(2, "big")

    def write_int(self, value: int) -> None:
        # Accepts any 32-bit pattern (signed component ids or unsigned constants).
        self._b += (value & 0xFFFFFFFF).to_bytes(4, "big")

    def write_long(self, value: int) -> None:
        self._b += (value & 0xFFFFFFFFFFFFFFFF).to_bytes(8, "big")

    def write_float(self, value: float) -> None:
        # IEEE-754 single, big-endian == writeInt(floatToRawIntBits).
        self._b += struct.pack(">f", value)

    def write_int_bits_as_float(self, bits: int) -> None:
        # For NaN-encoded ids / raw float bits: emit the 32 bits verbatim.
        self.write_int(bits)

    def write_double(self, value: float) -> None:
        self._b += struct.pack(">d", value)

    def write(self, b: bytes) -> None:
        self._b += b

    def write_buffer(self, b: bytes) -> None:
        self.write_int(len(b))
        self._b += b

    def write_utf8(self, s: str) -> None:
        self.write_buffer(s.encode("utf-8"))

    def start(self, op_code: int) -> None:
        # WireBuffer.start(type): records start index then writes the opcode byte.
        self.write_byte(op_code)

    # ── overwrite (for size back-patching, used by some ops) ─────────────────

    def overwrite_int(self, position: int, value: int) -> None:
        self._b[position:position + 4] = (value & 0xFFFFFFFF).to_bytes(4, "big")

    # ── block relocation (WireBuffer.moveBlock — used by global sections) ─────

    def move_block(self, beyond: int, insert_location: int) -> None:
        """Move the tail `[beyond, size)` so it starts at `insert_location`.

        This is how a `global` section is hoisted ahead of the root: the ops are written
        normally and then relocated. Mirrors WireBuffer.moveBlock, including its silent
        no-op guards.
        """
        if insert_location < 0 or beyond > len(self._b) or insert_location >= beyond:
            return
        tail = self._b[beyond:]
        del self._b[beyond:]
        self._b[insert_location:insert_location] = tail

    @property
    def index(self) -> int:
        return len(self._b)

    def to_bytes(self) -> bytes:
        return bytes(self._b)
