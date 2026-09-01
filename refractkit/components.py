"""Low-level RemoteCompose component builders shared across renderers."""

from __future__ import annotations

DEBUG_BORDER = {"border": {"width": 1.0, "cornerRadius": 0.0, "color": "#FFFF0000", "shape": 0}}


def dbg(mods: list, debug: bool) -> list:
    """Append a 1px red debug border to a modifier list when debug is on."""
    return mods + [DEBUG_BORDER] if debug else mods


def text(value: str, size: float, color: str, debug: bool,
         extra: list | None = None, mono: bool = False,
         family: str | None = None, weight: float | None = None) -> dict:
    """A Text component. ``mono`` selects monospace; ``family`` a named system font;
    ``weight`` a font weight (400 = regular, omitted)."""
    comp = {"type": "text", "value": value, "fontSize": size, "color": color}
    fam = "monospace" if mono else family
    if fam:
        comp["fontFamily"] = fam
    if weight and float(weight) != 400.0:
        comp["fontWeight"] = float(weight)
    mods = dbg(list(extra or []), debug)
    if mods:
        comp["modifiers"] = mods
    return comp
