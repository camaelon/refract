"""Low-level RemoteCompose component builders shared across renderers."""

from __future__ import annotations

DEBUG_BORDER = {"border": {"width": 1.0, "cornerRadius": 0.0, "color": "#FFFF0000", "shape": 0}}


def dbg(mods: list, debug: bool) -> list:
    """Append a 1px red debug border to a modifier list when debug is on."""
    return mods + [DEBUG_BORDER] if debug else mods


def text(value: str, size: float, color: str, debug: bool,
         extra: list | None = None, mono: bool = False) -> dict:
    """A Text component. ``mono`` selects a monospace font (for code)."""
    comp = {"type": "text", "value": value, "fontSize": size, "color": color}
    if mono:
        comp["fontFamily"] = "monospace"
    mods = dbg(list(extra or []), debug)
    if mods:
        comp["modifiers"] = mods
    return comp
