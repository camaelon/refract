#!/usr/bin/env python3
"""What is in a deck's includes/, and which of it the deck actually uses.

Run by refractplayer's asset window.

    python3 player/tools/assets.py <deck-out-dir> --list
    python3 player/tools/assets.py <deck-out-dir> --remove includes/old.png

`--list` reports every file under includes/ with its size, its kind, and the slides that use
it. Usage comes from loading the deck with refract's own resolver, so it is the same answer
the build would give rather than a second guess at the markdown.

`--remove` moves a file to `out/.trash/` rather than deleting it. Everything else the player
does to a deck can be taken back, and an asset is the one thing the undo history — which
stores text — cannot hold. A build never looks in there, and `out/` is generated, so emptying
it is always safe.
"""

import argparse
import json
import os
import shutil
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
try:
    from refractkit import assets, manifest
except ImportError:  # pragma: no cover - only when the script is copied out of the repo
    sys.stderr.write(f"assets.py: cannot import refractkit from {_ROOT}\n")
    raise


def fail(message: str) -> int:
    print(json.dumps({"ok": False, "error": message}))
    return 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    ap.add_argument("out_dir", help="the deck's out/ directory (the one holding deck.json)")
    ap.add_argument("--list", action="store_true", help="what is in includes/, and who uses it")
    ap.add_argument("--remove", metavar="PATH", default=None,
                    help="move an asset to out/.trash/ (refused while it is in use)")
    ap.add_argument("--force", action="store_true",
                    help="with --remove: move it even though something uses it")
    args = ap.parse_args()

    if args.list == (args.remove is not None):
        ap.error("give exactly one of --list or --remove")

    out_dir = os.path.abspath(args.out_dir)
    try:
        deck = manifest.load(out_dir)
    except manifest.NotADeck as e:
        return fail(str(e))
    deck_dir = manifest.source_dir(out_dir, deck)

    found = assets.scan(deck_dir)
    if args.list:
        print(json.dumps({
            "ok": True,
            "deck": os.path.basename(deck_dir),
            "dir": deck_dir,
            "assets": found,
            "bytes": sum(a["size"] for a in found),
            "unused": sum(1 for a in found if not a["used"]),
        }))
        return 0

    entry = next((a for a in found if a["path"] == args.remove), None)
    if entry is None:
        return fail(f"there is no {args.remove} in this deck")
    if entry["used"] and not args.force:
        where = ", ".join(str(n) for n in entry["slides"][:4] if n)
        return fail(f"{args.remove} is used by slide {where}" if where
                    else f"{args.remove} is used by the deck's settings")

    source = os.path.join(deck_dir, args.remove)
    target = os.path.join(out_dir, ".trash", args.remove)
    os.makedirs(os.path.dirname(target), exist_ok=True)
    # A name already in the trash is kept: the point of moving rather than deleting is that
    # nothing is lost, and losing the *previous* one to the new one would miss it.
    if os.path.exists(target):
        stem, ext = os.path.splitext(target)
        n = 2
        while os.path.exists(f"{stem}-{n}{ext}"):
            n += 1
        target = f"{stem}-{n}{ext}"
    shutil.move(source, target)

    print(json.dumps({"ok": True, "removed": args.remove,
                      "trash": os.path.relpath(target, deck_dir),
                      "used": entry["used"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
