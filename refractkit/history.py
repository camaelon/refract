"""Undo for the edits that rewrite a deck's markdown.

Reordering a slide, adding one, deleting one, saving one from the editor — all of them rewrite
`slides.md`, and until this existed none of them could be taken back. The slide editor's own
`cmd+Z` undoes typing *within* a slide; this is the other kind, and it is the one where a
mistake costs something: a slide dropped in the wrong place has to be found again, and a
deleted one is simply gone.

Each edit records the file's contents either side of it. Undo puts the `before` back, redo
puts the `after` back, and a new edit throws away whatever was ahead of the cursor — the same
shape as any undo stack, kept in one JSON file beside the build.

The whole file is stored rather than a diff. A slides.md is tens of kilobytes and the ring is
short; a patch format would be a second thing that can be wrong about what the file says, in
the one place where being wrong loses somebody's work.
"""

from __future__ import annotations

import hashlib
import json
import os
import time

HISTORY_NAME = ".refract-history.json"
# How many edits are kept. Long enough to walk back out of a bad afternoon, short enough that
# the file stays a few hundred kilobytes.
MAX_ENTRIES = 30
VERSION = 1


def path_for(out_dir: str) -> str:
    return os.path.join(out_dir, HISTORY_NAME)


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def load(out_dir: str) -> dict:
    """The history, or an empty one. Never raises: a corrupt history costs undo, not the deck."""
    try:
        with open(path_for(out_dir)) as f:
            doc = json.load(f)
    except (OSError, ValueError):
        return {"version": VERSION, "cursor": 0, "entries": []}
    if doc.get("version") != VERSION or not isinstance(doc.get("entries"), list):
        return {"version": VERSION, "cursor": 0, "entries": []}
    doc.setdefault("cursor", len(doc["entries"]))
    return doc


def save(out_dir: str, doc: dict) -> bool:
    try:
        tmp = path_for(out_dir) + ".tmp"
        with open(tmp, "w") as f:
            json.dump(doc, f)
        os.replace(tmp, path_for(out_dir))
        return True
    except OSError:
        return False


def record(out_dir: str, file: str, before: str, after: str, description: str) -> None:
    """Note an edit that has just been made to `file` (a path relative to the deck).

    Anything ahead of the cursor is dropped: editing after an undo means the redone future no
    longer happened, which is what every undo stack does and what anyone expects.
    """
    if before == after:
        return
    doc = load(out_dir)
    doc["entries"] = doc["entries"][:doc["cursor"]]
    doc["entries"].append({
        "file": file,
        "before": before,
        "after": after,
        "description": description,
        "at": round(time.time(), 3),
    })
    if len(doc["entries"]) > MAX_ENTRIES:
        doc["entries"] = doc["entries"][-MAX_ENTRIES:]
    doc["cursor"] = len(doc["entries"])
    save(out_dir, doc)


def describe(out_dir: str) -> dict:
    """What undo and redo would do, for a caller that wants to say so before doing it."""
    doc = load(out_dir)
    cursor, entries = doc["cursor"], doc["entries"]
    return {
        "undo": entries[cursor - 1]["description"] if cursor > 0 else None,
        "redo": entries[cursor]["description"] if cursor < len(entries) else None,
        "depth": cursor,
        "ahead": len(entries) - cursor,
    }


class Conflict(Exception):
    """The file is not what the history last left it as — somebody else has edited it."""


def _apply(deck_dir: str, entry: dict, want: str, put: str) -> str:
    """Put `put` into the entry's file, having checked it currently holds `want`.

    The check is the point. A slides.md edited in a terminal while the player was open is a
    perfectly ordinary thing to have happened, and undo must not silently throw that away."""
    path = os.path.join(deck_dir, entry["file"])
    try:
        with open(path) as f:
            current = f.read()
    except OSError:
        raise Conflict(f"cannot read {entry['file']}")
    if _digest(current) != _digest(entry[want]):
        raise Conflict(f"{entry['file']} has changed outside the player — "
                       f"nothing was undone")
    tmp = path + ".undo.tmp"
    with open(tmp, "w") as f:
        f.write(entry[put])
    os.replace(tmp, path)
    return path


def undo(out_dir: str, deck_dir: str) -> dict | None:
    """Step back one edit. Returns what was undone, or None when there is nothing to undo."""
    doc = load(out_dir)
    if doc["cursor"] <= 0:
        return None
    entry = doc["entries"][doc["cursor"] - 1]
    _apply(deck_dir, entry, "after", "before")
    doc["cursor"] -= 1
    save(out_dir, doc)
    return entry


def redo(out_dir: str, deck_dir: str) -> dict | None:
    """Step forward one edit. Returns what was redone, or None when there is nothing ahead."""
    doc = load(out_dir)
    if doc["cursor"] >= len(doc["entries"]):
        return None
    entry = doc["entries"][doc["cursor"]]
    _apply(deck_dir, entry, "before", "after")
    doc["cursor"] += 1
    save(out_dir, doc)
    return entry
