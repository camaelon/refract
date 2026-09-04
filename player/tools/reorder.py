#!/usr/bin/env python3
"""Move a slide to a new position by rewriting the markdown it came from.

Run by refractplayer's deck view when a slide is dragged. Given the deck's `out/` directory
and two slide indices, it edits the `slides.md` block behind the dragged slide and — unless
told not to — rebuilds the deck so the player can reload it.

    python3 player/tools/reorder.py <deck-out-dir> --move FROM --to TO [--no-rebuild]

Indices are 0-based positions in `out/deck.json`. A slide that refract expanded into several
(bullet fragments, scroll pages, staggered embeds) moves as one block: all of them travel with
the markdown chunk that produced them.

A whole section, or a whole included sub-deck, is a *range* of markdown blocks rather than a
slide, and the deck view works out which range that is — so it says so directly:

    python3 player/tools/reorder.py <dir> --file slides.md --chunks 4 9 --to-chunk 0

`--chunks FIRST LAST` are `---`-separated block indices in `--file`, and `--to-chunk` is where
the block should start once it has been lifted out (0 .. count - size).

`--dry-run` prints what would change and writes nothing. `--json` prints a machine-readable
result on stdout, which is what the player reads.
"""

import argparse
import json
import os
import subprocess
import sys

# The reordering itself lives in refractkit, next to the markdown parser whose chunking it has
# to agree with. This script ships inside the refract checkout, so the package is two levels up.
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
try:
    from refractkit import manifest, reorder
except ImportError:  # pragma: no cover - only when the script is copied out of the repo
    sys.stderr.write(f"reorder.py: cannot import refractkit from {_ROOT}\n")
    raise


def rebuild(deck_dir: str, deck: dict) -> int:
    """Re-run refract over the deck, the way it was built. The .rc files are named after the
    slide's position, so every file downstream of the move is rewritten (and refract's
    incremental build reuses everything before it); the player reloads the whole playlist."""
    script = os.path.join(_ROOT, "refract.py")
    if not os.path.isfile(script):
        sys.stderr.write(f"reorder.py: cannot find refract.py at {script}\n")
        return 1
    # refract's build log goes to stderr, not stdout: with --json the caller parses stdout,
    # and the player does exactly that. The log is still shown, just on the other stream.
    return subprocess.call([sys.executable, script, deck_dir, *manifest.build_args(deck)],
                           stdout=sys.stderr)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    ap.add_argument("out_dir", help="the deck's out/ directory (the one holding deck.json)")
    ap.add_argument("--move", type=int, default=None, metavar="FROM",
                    help="index of the slide to move, in deck order")
    ap.add_argument("--to", type=int, default=None, metavar="TO",
                    help="index it should end up at, in deck order")
    ap.add_argument("--file", default=None, metavar="MD",
                    help="markdown file to edit, relative to the deck (with --chunks)")
    ap.add_argument("--chunks", type=int, nargs=2, default=None, metavar=("FIRST", "LAST"),
                    help="inclusive range of `---` blocks to move together")
    ap.add_argument("--to-chunk", type=int, default=None, metavar="DST",
                    help="index the block should start at once lifted out")
    ap.add_argument("--no-rebuild", action="store_true",
                    help="rewrite the markdown but do not re-run refract")
    ap.add_argument("--dry-run", action="store_true", help="report the move, change nothing")
    ap.add_argument("--json", action="store_true", help="print the result as JSON")
    args = ap.parse_args()

    out_dir = os.path.abspath(args.out_dir)
    try:
        deck = manifest.load(out_dir)
    except manifest.NotADeck as e:
        raise SystemExit(f"reorder.py: {e}")
    slides = deck.get("slides") or []
    deck_dir = manifest.source_dir(out_dir, deck)

    run = args.chunks is not None
    if run:
        if args.file is None or args.to_chunk is None:
            ap.error("--chunks needs --file and --to-chunk")
        src, from_chunk, to_chunk = args.file, args.chunks[0], args.chunks[1]
    else:
        if args.move is None or args.to is None:
            ap.error("give either --move/--to or --file/--chunks/--to-chunk")
        try:
            src, from_chunk, to_chunk = reorder.plan_move(slides, args.move, args.to)
        except (IndexError, ValueError) as e:
            if args.json:
                print(json.dumps({"ok": False, "error": str(e)}))
            else:
                sys.stderr.write(f"reorder.py: {e}\n")
            return 1

    md_path = os.path.join(deck_dir, src)
    if not os.path.isfile(md_path):
        msg = f"cannot find {md_path}"
        if args.json:
            print(json.dumps({"ok": False, "error": msg}))
        else:
            sys.stderr.write(f"reorder.py: {msg}\n")
        return 1

    with open(md_path) as f:
        text = f.read()
    try:
        new_text = (reorder.move_chunks(text, from_chunk, to_chunk, args.to_chunk) if run
                    else reorder.move_chunk(text, from_chunk, to_chunk))
    except IndexError as e:
        # deck.json is stale: it names a chunk the markdown no longer has.
        msg = f"{e} — the deck is out of date with {src}"
        if args.json:
            print(json.dumps({"ok": False, "error": msg}))
        else:
            sys.stderr.write(f"reorder.py: {msg}\n")
        return 1

    changed = new_text != text
    result = {
        "ok": True,
        "file": md_path,
        "from_chunk": from_chunk,
        "to_chunk": to_chunk,
        "changed": changed,
        "rebuilt": False,
    }
    if run:
        result["chunks"] = [from_chunk, to_chunk]
        result["dst"] = args.to_chunk

    if not args.dry_run and changed:
        # Written via a temp file in the same directory then renamed, so an interrupted write
        # can never leave a half-rewritten slides.md behind.
        tmp = md_path + ".reorder.tmp"
        with open(tmp, "w") as f:
            f.write(new_text)
        os.replace(tmp, md_path)

    if not args.dry_run and changed and not args.no_rebuild:
        rc = rebuild(deck_dir, deck)
        result["rebuilt"] = rc == 0
        if rc != 0:
            result["ok"] = False
            result["error"] = f"refract.py exited with {rc}"

    if args.json:
        print(json.dumps(result))
    elif not changed:
        print("nothing to do: the slide is already there")
    elif run:
        print(f"moved chunks {from_chunk}-{to_chunk} to {args.to_chunk} in {src}"
              + ("" if result["rebuilt"] else " (not rebuilt)"))
    else:
        print(f"moved chunk {from_chunk} -> {to_chunk} in {src}"
              + ("" if result["rebuilt"] else " (not rebuilt)"))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
