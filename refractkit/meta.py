"""The ``::`` line's vocabulary: the slide types, flags and keys a deck can use.

A ``::`` line is ``:: <type> [flags] [key=value…] [: params] [ratio]``, and the words that
may appear in it are spread across the code that acts on them — the layout types in
``render``, the transition knobs in ``refract.py``, ``skip`` in two places at once. Nobody
can hold that list in their head, which is what this is for: one place that says what may be
written, so the editor can offer it and a person can read it.

The layout types are taken from ``render.SLIDE_TYPES`` rather than repeated, so a new one
cannot be added without appearing here. The rest is written down, and ``tests/test_meta.py``
checks the parts that can be checked against the code that honours them.
"""

from __future__ import annotations

from .render import DEFAULT_TYPE, SLIDE_TYPES


# The first word. The layout types come from render; these are what each is for, and the
# ones below them are not layouts at all — they say what to *do* with the block.
LAYOUT_DOC = {
    "title":   "the deck's opening slide — centred, largest type",
    "section": "a divider between parts of the talk",
    "content": "the ordinary slide (the default, so it can be left out)",
    "max":     "near-fullscreen: tight margins, smaller title, chrome kept",
    "split":   "two columns from +++, laid out row-first",
}

SPECIAL_TYPES = [
    ("include", "splice in a sub-deck: `:: include : name`"),
    ("same",    "carry the previous slide's content over and add to it"),
    ("outline", "a generated contents slide, one line per section"),
    ("agenda",  "the same list, as bullets"),
    ("skip",    "drop this slide from the deck entirely"),
]

# Bare words after the type.
FLAGS = [
    ("steps",      "reveal this slide's content one step at a time"),
    ("nosteps",    "...and never, whatever the deck's default is"),
    ("fragment",   "reveal each block as its own step"),
    ("nofragment", "...and never"),
    ("skip",       "drop this slide from the deck entirely"),
    ("freeze",     "hold a still of the outgoing slide through the push"),
]

# `key=value`. `values` lists what the key accepts where that is a closed set, and is empty
# where it is a colour, a number or a name.
KEYS = [
    ("bg",                  "slide background colour", []),
    ("background",          "the same, spelled out", []),
    ("accent",              "the slide's accent colour", []),
    ("title_color",         "title colour for this slide", []),
    ("body_color",          "body colour for this slide", []),
    ("shader",              "named background shader, or none", ["none"]),
    ("chrome",              "hide the footer chrome on this slide",
     ["hidden", "none", "off", "false", "no"]),
    ("pad",                 "margin on every side", []),
    ("pad_left",            "margin on the left", []),
    ("pad_right",           "margin on the right", []),
    ("pad_top",             "margin at the top", []),
    ("pad_bottom",          "margin at the bottom", []),
    ("pad_extra",           "extra margin on top of the theme's", []),
    ("autosize",            "shrink the text to fit rather than scrolling",
     ["true", "false"]),
    ("reveal",              "how content arrives", ["stagger", "immediate"]),
    ("scroll",              "how far a `:: same` continuation is scrolled", []),
    ("steps",               "stepped reveal for this slide", ["off"]),
    ("skip",                "drop this slide", ["true", "false"]),
    ("transition",          "how this slide arrives",
     ["push", "push-up", "slide", "slide-left", "slide-up", "none"]),
    ("transition_duration", "how long it takes, in seconds", []),
    ("transition_fx",       "draw the transition shader over it", ["true", "false"]),
    ("freeze",              "hold a still of the outgoing slide through the push",
     ["true", "false"]),
    ("gate",                "how long an embed waits before it starts, in seconds", []),
]


# `<name | key=value … flag>`. Each is (name, doc, values, kinds, takes_value):
#
# `kinds` names the *asset* kinds the option does anything for — the kinds `assets.scan`
# reports, since that is what the editor knows about a name it is offering options for. An
# option is not worth suggesting where it would be ignored: `crop` on a `.png` does nothing,
# and a menu that says otherwise is a menu that lies.
#
# `takes_value` separates `fit=fill` from a bare word like `stagger`, so the editor knows
# whether to bring an `=` along with the name.
INCLUDE_OPTS = [
    ("crop", "show only part of the source: l,t,r,b as fractions 0–1", [],
     ["video", "document"], True),
    ("fit", "how the embed fills its box", ["fit", "fill", "native"],
     ["video", "document"], True),
    ("ratio", "frame the embed in a box of this aspect ratio, e.g. 16:9", [],
     ["video", "document"], True),
    ("title", "a caption drawn under the embed — quote it for several words", [],
     ["video", "document", "image"], True),
    ("stagger", "reveal this embed on its own step", [],
     ["video", "document", "image", "code"], False),
]


def types() -> list[tuple[str, str]]:
    """Every first word, layouts first, each with a line saying what it is for."""
    out = [(name, LAYOUT_DOC.get(name, ""))
           for name in sorted(SLIDE_TYPES, key=lambda n: (n != DEFAULT_TYPE, n))]
    return out + list(SPECIAL_TYPES)


def vocabulary() -> dict:
    """The whole thing, in the shape the player's editor asks for."""
    return {
        "types": [{"name": n, "doc": d} for n, d in types()],
        "flags": [{"name": n, "doc": d} for n, d in FLAGS],
        "keys": [{"name": n, "doc": d, "values": v} for n, d, v in KEYS],
        "include_opts": [{"name": n, "doc": d, "values": v, "kinds": k, "takes_value": t}
                         for n, d, v, k, t in INCLUDE_OPTS],
    }
