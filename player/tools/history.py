#!/usr/bin/env python3
"""Undo and redo the edits that rewrote a deck's markdown.

Run by refractplayer's deck view. Reordering a slide, adding one, deleting one and saving one
from the editor all rewrite `slides.md`; each records the file either side of itself, and this
walks that back and forward again.

    python3 player/tools/history.py <deck-out-dir> --undo [--no-rebuild]
    python3 player/tools/history.py <deck-out-dir> --redo
    python3 player/tools/history.py <deck-out-dir> --list

An undo refuses when the file has been changed outside the player since the edit — a
slides.md edited in a terminal while the player was open is an ordinary thing to have
happened, and undo must not throw it away to make room for its own idea of the past.
"""

import argparse
import json
import os
import subprocess
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
try:
    from refractkit import history, manifest
except ImportError:  # pragma: no cover - only when the script is copied out of the repo
    sys.stderr.write(f"history.py: cannot import refractkit from {_ROOT}\n")
    raise


def rebuild(deck_dir: str, deck: dict) -> int:
    script = os.path.join(_ROOT, "refract.py")
    if not os.path.isfile(script):
        sys.stderr.write(f"history.py: cannot find refract.py at {script}\n")
        return 1
    return subprocess.call([sys.executable, script, deck_dir, *manifest.build_args(deck)],
                           stdout=sys.stderr)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    ap.add_argument("out_dir", help="the deck's out/ directory (the one holding deck.json)")
    ap.add_argument("--undo", action="store_true", help="take back the last edit")
    ap.add_argument("--redo", action="store_true", help="put it back")
    ap.add_argument("--list", action="store_true", help="what undo and redo would do")
    ap.add_argument("--no-rebuild", action="store_true",
                    help="restore the markdown but do not re-run refract")
    ap.add_argument("--json", action="store_true", help="print the result as JSON")
    args = ap.parse_args()

    if sum(1 for m in (args.undo, args.redo, args.list) if m) != 1:
        ap.error("give exactly one of --undo, --redo or --list")
    # --list always answers in JSON: it exists to be read by the caller.
    as_json = args.json or args.list

    out_dir = os.path.abspath(args.out_dir)
    try:
        deck = manifest.load(out_dir)
    except manifest.NotADeck as e:
        if as_json:
            print(json.dumps({"ok": False, "error": str(e)}))
        else:
            sys.stderr.write(f"history.py: {e}\n")
        return 1
    deck_dir = manifest.source_dir(out_dir, deck)

    if args.list:
        print(json.dumps({"ok": True, **history.describe(out_dir)}))
        return 0

    try:
        entry = history.undo(out_dir, deck_dir) if args.undo \
            else history.redo(out_dir, deck_dir)
    except history.Conflict as e:
        if as_json:
            print(json.dumps({"ok": False, "error": str(e)}))
        else:
            sys.stderr.write(f"history.py: {e}\n")
        return 1

    if entry is None:
        message = "nothing to undo" if args.undo else "nothing to redo"
        if as_json:
            print(json.dumps({"ok": True, "changed": False, "rebuilt": False,
                              "description": message}))
        else:
            print(message)
        return 0

    verb = "undid" if args.undo else "redid"
    result = {"ok": True, "changed": True, "rebuilt": False, "file": entry["file"],
              "description": f"{verb} {entry['description']}"}
    if not args.no_rebuild:
        rc = rebuild(deck_dir, deck)
        result["rebuilt"] = rc == 0
        if rc != 0:
            result["ok"] = False
            result["error"] = f"refract.py exited with {rc}"

    if as_json:
        print(json.dumps(result))
    else:
        print(result["description"] + ("" if result["rebuilt"] else " (not rebuilt)"))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
