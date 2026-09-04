#!/usr/bin/env python3
"""Rebuild a deck, and report what the build actually did.

Run by refractplayer's build panel. Runs `refract.py` over the deck the given `out/` directory
belongs to, with the options the panel is showing, and reports how much of the deck had to be
recompiled — which is the number worth seeing, since refract builds incrementally and a small
edit should cost almost nothing.

    python3 player/tools/build.py <deck-out-dir> [--transitions] [--debug] [--force] …

The counts come from the modification times of the outputs, taken either side of the build,
rather than from refract's log: that is exact, survives `--force` (where every slide is
recompiled from an unchanged input), and does not depend on the wording of a print statement.
"""

import argparse
import json
import os
import subprocess
import sys
import time

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
try:
    from refractkit import manifest
except ImportError:  # pragma: no cover - only when the script is copied out of the repo
    sys.stderr.write(f"build.py: cannot import refractkit from {_ROOT}\n")
    raise

# What a build produces and may replace. A file outside this set is none of its business.
BUILT_EXTS = (".rc", ".notes", ".mp4", ".mov", ".m4v", ".webm")


def outputs(out_dir: str) -> dict:
    """Every generated file under out/, with its modification time."""
    found = {}
    for directory in (out_dir, os.path.join(out_dir, "media")):
        try:
            names = os.listdir(directory)
        except OSError:
            continue
        for name in names:
            if not name.endswith(BUILT_EXTS):
                continue
            path = os.path.join(directory, name)
            try:
                found[os.path.relpath(path, out_dir)] = os.stat(path).st_mtime_ns
            except OSError:
                pass
    return found


def refract_args(args, deck: dict) -> list:
    """The options to build with: the panel's choices, over the deck's own size."""
    return manifest.build_args(deck, transitions=args.transitions, debug=args.debug,
                               force=args.force, keep_json=args.keep_json,
                               width=args.width, height=args.height)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    ap.add_argument("out_dir", help="the deck's out/ directory (the one holding deck.json)")
    ap.add_argument("--transitions", action="store_true", help="build with slide transitions")
    ap.add_argument("--debug", action="store_true", help="outline every component")
    ap.add_argument("--force", action="store_true", help="recompile every slide")
    ap.add_argument("--keep-json", action="store_true", help="keep the intermediate JSON")
    ap.add_argument("--width", type=int, default=None)
    ap.add_argument("--height", type=int, default=None)
    ap.add_argument("--json", action="store_true", help="print the result as JSON")
    args = ap.parse_args()

    out_dir = os.path.abspath(args.out_dir)
    deck = {}
    if os.path.isfile(os.path.join(out_dir, "deck.json")):
        deck = manifest.load(out_dir)
        deck_dir = manifest.source_dir(out_dir, deck)
    else:
        # No manifest yet — a deck that has never been built. The convention is <deck>/out,
        # so the deck is one level up; anything else is a directory that is not a deck.
        deck_dir = os.path.dirname(out_dir)
        if not os.path.isfile(os.path.join(deck_dir, "slides.md")):
            message = f"no deck.json in {out_dir}, and no slides.md in {deck_dir}"
            if args.json:
                print(json.dumps({"ok": False, "error": message}))
            else:
                sys.stderr.write(f"build.py: {message}\n")
            return 1

    script = os.path.join(_ROOT, "refract.py")
    if not os.path.isfile(script):
        message = f"cannot find refract.py at {script}"
        if args.json:
            print(json.dumps({"ok": False, "error": message}))
        else:
            sys.stderr.write(f"build.py: {message}\n")
        return 1

    before = outputs(out_dir)
    started = time.time()
    # refract's log goes to stderr: with --json the caller parses stdout, and the panel does.
    proc = subprocess.run([sys.executable, script, deck_dir, *refract_args(args, deck)],
                          stdout=sys.stderr if args.json else None,
                          stderr=subprocess.PIPE, text=True)
    elapsed = time.time() - started
    if proc.stderr:
        sys.stderr.write(proc.stderr)
    after = outputs(out_dir)

    rebuilt = [name for name, stamp in after.items() if before.get(name) != stamp]
    result = {
        "ok": proc.returncode == 0,
        "seconds": round(elapsed, 2),
        "rebuilt": len(rebuilt),
        "reused": len(after) - len(rebuilt),
        "removed": len([name for name in before if name not in after]),
        "slides": len(deck.get("slides") or []),
    }
    if proc.returncode != 0:
        # The last line of refract's own error is the useful one; the panel has room for
        # a sentence, not a traceback.
        tail = [line for line in (proc.stderr or "").strip().splitlines() if line.strip()]
        result["error"] = tail[-1] if tail else f"refract.py exited with {proc.returncode}"

    if args.json:
        print(json.dumps(result))
    elif result["ok"]:
        print(f"{result['rebuilt']} rebuilt, {result['reused']} reused, "
              f"{result['removed']} removed in {result['seconds']}s")
    else:
        sys.stderr.write(f"build.py: {result.get('error')}\n")
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
