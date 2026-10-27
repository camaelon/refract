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

import re

from .render import DEFAULT_TYPE, SLIDE_TYPES


_DURATION_RE = re.compile(r"(\d+(?:\.\d+)?)\s*([hms]?)", re.I)


def parse_duration(text) -> float:
    """``"12m"``, ``"90s"``, ``"1h30m"``, ``"45"`` (minutes) → seconds. 0 for anything else.

    The same grammar the player's ``--duration`` takes, deliberately: a talk's planned length
    is written the same way whether it is said on the command line or on a ``:: section``.
    """
    if isinstance(text, (int, float)):
        return float(text) * 60.0        # a bare number is minutes
    if not isinstance(text, str) or not text.strip():
        return 0.0
    total = 0.0
    sawDigit = False
    for value, unit in _DURATION_RE.findall(text):
        sawDigit = True
        n = float(value)
        if unit.lower() == "h":
            total += n * 3600.0
        elif unit.lower() == "m":
            total += n * 60.0
        elif unit.lower() == "s":
            total += n
        else:
            total += n * 60.0            # no unit: minutes
    return total if sawDigit else 0.0


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
    ("as",      "use a named theme preset from theme/: `:: as : name`"),
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
    ("bg",                  "slide background colour or file", []),
    ("background",          "the same, spelled out", []),
    ("bg_doc",              "custom background inclusion (.json/.rc/.png), or none", ["none"]),
    ("accent",              "the slide's accent colour", []),
    ("title_color",         "title colour for this slide", []),
    ("title_pad_top",       "extra margin above title", []),
    ("body_color",          "body colour for this slide", []),
    ("shader",              "named background shader, or none", ["none"]),
    ("chrome",              "hide the footer chrome on this slide",
     ["hidden", "none", "off", "false", "no"]),
    ("camera",              "the template's camera badge: off, or its options (x= y= width= clip= zoom= …)",
     ["off", "on"]),
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
    # On a `:: section`: how long that part of the talk is meant to take. The player adds
    # them up for the deck's planned length, and paces the talk against them.
    ("duration",            "on a section: how long it should take — 12m, 90s, 1h5m", []),
    ("pane_gap",            "gap between columns in a split slide", []),
    ("pane_valign",         "how +++ panes of different heights line up", ["center", "top", "bottom"]),
    ("gap",                 "gap between columns or sections", []),
    # On a `===` section: make it a band of exactly this height rather than one that
    # takes its natural height or shares what is left over.
    ("height",              "on a `===` section: its exact height in px", []),
    ("bullet_sub_weight",   "font weight of nested bullets on this slide", ["200", "300", "400", "500"]),
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
    ("frame", "put it in a device frame from the theme's [frames.<name>], e.g. android", [],
     ["video", "document", "image", "camera"], True),
    ("title", "a caption drawn under the embed — quote it for several words", [],
     ["video", "document", "image"], True),
    ("clip", "the box's shape: roundrect (the theme's corner radius), circle, a radius in px, or none",
     ["roundrect", "circle", "none"],
     ["video", "document", "camera"], True),
    ("width", "the box's width in px, instead of filling what is left", [],
     ["video", "document", "camera"], True),
    ("height", "the box's height in px", [],
     ["video", "document", "camera"], True),
    ("align", "where a sized box sits in its row", ["start", "center", "end"],
     ["video", "document", "camera"], True),
    ("zoom", "zoom in: N shows the middle 1/N (with focus=); T@x,y,z is one keyframe — on "
             "consecutive slides of the same media, each slide eases to its own view", [],
     ["video", "document", "camera", "image"], True),
    ("focus", "what zoom centres on: x,y as fractions 0–1", [],
     ["video", "document", "camera", "image"], True),
    ("zooms", "zoom keyframes \"T@x,y,z; …\": T in the clip (video) or since the slide "
              "opened, x,y the centre 0–1, z the zoom; eased from one view to the next", [],
     ["video", "document", "image"], True),
    ("steps", "with zooms=: a slide per keyframe, so next moves the zoom on", [],
     ["video", "document", "image"], False),
    ("start", "where the clip begins (and loops back to): seconds or m:ss", [],
     ["video"], True),
    ("still", "show the clip frozen on the frame at this time", [],
     ["video"], True),
    ("until", "play from start to this time once, and hold there", [],
     ["video"], True),
    ("once", "play through once and hold on the last frame (a document: run its events once)", [],
     ["video", "document"], False),
    ("events", "a touch script: \"1@click(x,y) wait(2) touchdown(x,y) touchup(x,y) …\" — loops", [],
     ["document"], True),
    ("loop", "0 plays once and holds the last frame; videos loop by default", ["0", "1"],
     ["video"], True),
    ("cue", "a still slide first; next starts the clip (cue=T: freeze on T)", [],
     ["video"], False),
    ("persist", "keep the document alive across slides, on its own clock", [],
     ["document"], False),
    ("step", "this slide's number for a slide-driven document (implies persist)", [],
     ["document"], True),
    ("stepid", "the document's float id that receives step", [],
     ["document"], True),
    ("timeid", "the document's float id that receives the slide's time", [],
     ["document"], True),
    ("prevstepid", "the float id that receives the step of the slide before", [],
     ["document"], True),
    ("prevtimeid", "the float id that receives how long the slide before was shown", [],
     ["document"], True),
    ("from", "play the document's own timeline from this time (seconds)", [],
     ["document"], True),
    ("to", "…to this time, then hold", [],
     ["document"], True),
    ("speed", "how fast the from/to window plays", [],
     ["document"], True),
    ("mirror", "flip the camera left-right, as a speaker expects to see themselves", [],
     ["camera"], False),
    ("device", "which camera: a name substring or an index", [],
     ["camera"], True),
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
