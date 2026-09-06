"""Slide keys, and keeping them pointing at the right slide when blocks move.

A rehearsal trace and the narration index both name a slide by where it was written — the
markdown file and the `---`-separated block within it, as `slides.md#3.0`. The trailing number
tells apart the several slides one block can produce.

That name is not a name so much as an address: a block's index is its *position*, so moving
one block renumbers every block after it and every key that named them is suddenly naming
somebody else. Filenames have the same problem and worse — they carry the slide's title too —
which is why the keys exist at all, but it does mean an edit that moves blocks has to bring
the keys along with it. That is what this is for, and it is called by the tools that do the
moving, in the same write.
"""

from __future__ import annotations

import json
import os
import re

KEY = re.compile(r"^(?P<src>.+)#(?P<index>\d+)\.(?P<step>\d+)$")


def parse(key: str):
    """(file, block, step) for a key, or None when it is not one."""
    m = KEY.match(key or "")
    if not m:
        return None
    return m.group("src"), int(m.group("index")), int(m.group("step"))


def make(src: str, index: int, step: int) -> str:
    return f"{src}#{index}.{step}"


def remap(key: str, file: str, moved: dict):
    """The key after the blocks of `file` moved as `moved` says.

    Unchanged when the key belongs to another file — an edit to one deck's markdown says
    nothing about a sub-deck's. None when its block is gone, and so is the slide it named.
    """
    parts = parse(key)
    if not parts:
        return key
    src, index, step = parts
    if src != file:
        return key
    if index not in moved:
        return None
    return make(src, moved[index], step)


def remap_mapping(mapping: dict, file: str, moved: dict) -> dict:
    """A key -> anything map, with its keys moved. Entries whose block is gone are dropped."""
    out = {}
    for key, value in mapping.items():
        new = remap(key, file, moved)
        if new is not None:
            out[new] = value
    return out


# ── The files that are keyed this way ────────────────────────────────

def voice_index_path(deck_dir: str) -> str:
    return os.path.join(deck_dir, "voice", "index.json")


def timing_path(out_dir: str) -> str:
    return os.path.join(out_dir, "timing.json")


def _read(path: str):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _write(path: str, doc) -> bool:
    try:
        tmp = path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(doc, f, indent=2)
        os.replace(tmp, path)
        return True
    except OSError:
        return False


def follow(deck_dir: str, out_dir: str, file: str, moved: dict) -> list[str]:
    """Move the keys in the narration index and the rehearsal trace, and say which were written.

    Called by whichever tool has just moved blocks in `file`. Doing nothing is the common
    case — most decks have no recording — and doing nothing is cheap.
    """
    written = []

    index_path = voice_index_path(deck_dir)
    doc = _read(index_path)
    if isinstance(doc, dict) and isinstance(doc.get("slides"), dict):
        doc["slides"] = remap_mapping(doc["slides"], file, moved)
        if _write(index_path, doc):
            written.append(index_path)

    trace_path = timing_path(out_dir)
    doc = _read(trace_path)
    if isinstance(doc, dict) and isinstance(doc.get("slides"), list):
        kept = []
        for entry in doc["slides"]:
            new = remap(entry.get("key", ""), file, moved)
            # An entry whose block is gone is dropped; one that never had a key is left as it
            # is, and goes on being matched by filename as it always was.
            if new is None:
                continue
            if entry.get("key"):
                entry["key"] = new
            kept.append(entry)
        doc["slides"] = kept
        if _write(trace_path, doc):
            written.append(trace_path)

    return written
