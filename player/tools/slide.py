#!/usr/bin/env python3
"""Read and write the markdown behind one slide.

Run by refractplayer's slide editor. A slide is a `---`-separated block of a slides.md, and
which block is recorded per slide in `out/deck.json` — so the editor can ask for a slide's
source, hand back an edited version, and have the deck rebuilt around it.

    python3 player/tools/slide.py <deck-out-dir> --slide 12 --read
    python3 player/tools/slide.py <deck-out-dir> --slide 12 --write new.md [--no-rebuild]
    python3 player/tools/slide.py <deck-out-dir> --slide 12 --new [--before]
    python3 player/tools/slide.py <deck-out-dir> --slide 12 --delete
    python3 player/tools/slide.py <deck-out-dir> --slide 12 --split 4 [--write new.md]
    python3 player/tools/slide.py <deck-out-dir> --slide 12 --merge
    python3 player/tools/slide.py <deck-out-dir> --slide 12 --duplicate

`--split N` breaks the slide after line N of its markdown; combined with `--write` it applies
the edit and splits it in one go, so the editor can break a slide it is holding unsaved
changes to without saving twice. `--merge` joins it with the slide after it.

`--read` prints JSON: the file, the block index, and the source. `--write` takes the new
source from a file (not stdin, so the player can hand over text with any bytes in it without
plumbing a pipe through fork/exec), replaces that block, and rebuilds the deck the way it was
built before.

Several rendered slides can come from one block — a stepped bullet list is one block and four
slides — so editing any of them edits the block they share. `--read` says how many slides the
block produces, and the editor says so too.
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
    from refractkit import chunks, history, keys, manifest
except ImportError:  # pragma: no cover - only when the script is copied out of the repo
    sys.stderr.write(f"slide.py: cannot import refractkit from {_ROOT}\n")
    raise


def locate(deck: dict, index: int) -> tuple:
    """(src, src_index, how many slides share that block) for a slide, by deck position."""
    slides = deck.get("slides") or []
    if not 0 <= index < len(slides):
        raise IndexError(f"slide {index} out of range (deck has {len(slides)} slides)")
    record = slides[index]
    src, block = record.get("src"), record.get("src_index")
    if not src or block is None:
        raise ValueError("deck.json has no source provenance (src_index); "
                         "rebuild the deck so its slides can be edited")
    shared = sum(1 for s in slides if s.get("src") == src and s.get("src_index") == block)
    return src, int(block), shared


def follow_keys(deck_dir: str, out_dir: str, src: str, moved: dict) -> list:
    """Move the keys in the narration index and the rehearsal trace, reporting both sides so
    the whole edit undoes as one. See refractkit.keys."""
    paths = [keys.voice_index_path(deck_dir), keys.timing_path(out_dir)]
    before = []
    for path in paths:
        try:
            with open(path) as f:
                before.append(f.read())
        except OSError:
            before.append("")
    keys.follow(deck_dir, out_dir, src, moved)
    extra = []
    for path, was in zip(paths, before):
        try:
            with open(path) as f:
                now = f.read()
        except OSError:
            now = ""
        extra.append((os.path.relpath(path, deck_dir), was, now))
    return extra


def rebuild(deck_dir: str, deck: dict) -> int:
    script = os.path.join(_ROOT, "refract.py")
    if not os.path.isfile(script):
        sys.stderr.write(f"slide.py: cannot find refract.py at {script}\n")
        return 1
    # refract's log goes to stderr: the caller parses stdout.
    return subprocess.call([sys.executable, script, deck_dir, *manifest.build_args(deck)],
                           stdout=sys.stderr)


def fail(message: str, as_json: bool) -> int:
    if as_json:
        print(json.dumps({"ok": False, "error": message}))
    else:
        sys.stderr.write(f"slide.py: {message}\n")
    return 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    ap.add_argument("out_dir", help="the deck's out/ directory (the one holding deck.json)")
    ap.add_argument("--slide", type=int, required=True, help="slide index, in deck order")
    ap.add_argument("--read", action="store_true", help="print the slide's markdown")
    ap.add_argument("--write", metavar="FILE", default=None,
                    help="replace the slide's markdown with the contents of FILE")
    ap.add_argument("--new", action="store_true",
                    help="add an empty slide after this one (--before puts it in front)")
    ap.add_argument("--before", action="store_true", help="with --new: insert in front")
    ap.add_argument("--delete", action="store_true",
                    help="remove this slide's markdown block, and every slide it produced")
    ap.add_argument("--split", type=int, default=None, metavar="LINE",
                    help="break this slide in two after LINE of its markdown")
    ap.add_argument("--merge", action="store_true",
                    help="join this slide with the one after it")
    ap.add_argument("--duplicate", action="store_true",
                    help="insert a copy of this slide after it")
    ap.add_argument("--no-rebuild", action="store_true",
                    help="write the markdown but do not re-run refract")
    ap.add_argument("--json", action="store_true", help="print the result as JSON")
    args = ap.parse_args()

    # --split may ride along with --write: the editor breaks a slide it is holding unsaved
    # changes to, and that has to be one edit rather than two rewrites and two rebuilds.
    structural = [args.new, args.delete, args.merge, args.duplicate,
                  args.split is not None and args.write is None]
    modes = [args.read, args.write is not None] + structural
    if sum(1 for m in modes if m) != 1:
        ap.error("give exactly one of --read, --write, --new, --delete, --split, --merge "
                 "or --duplicate")
    # A read always answers in JSON, so its failures do too — the caller is parsing stdout
    # either way, and an error on stderr would look to it like no answer at all.
    as_json = args.json or args.read

    out_dir = os.path.abspath(args.out_dir)
    try:
        deck = manifest.load(out_dir)
    except manifest.NotADeck as e:
        return fail(str(e), as_json)
    deck_dir = manifest.source_dir(out_dir, deck)

    try:
        src, block, shared = locate(deck, args.slide)
    except (IndexError, ValueError) as e:
        return fail(str(e), as_json)

    md_path = os.path.join(deck_dir, src)
    if not os.path.isfile(md_path):
        return fail(f"cannot find {md_path}", as_json)
    with open(md_path) as f:
        text = f.read()

    if args.new or args.delete or args.merge or args.duplicate or args.split is not None:
        # A block is what is added, removed, split or joined — not a slide: deleting one step
        # of a stepped bullet list would leave the others without their source.
        at = block if args.before else block + 1
        try:
            if args.write is not None:
                # The editor's unsaved text, then the split, as one edit.
                with open(args.write) as f:
                    text = chunks.replace_chunk(text, block, f.read())
            if args.new:
                new_text, what = chunks.insert_chunk(text, at, "# New slide\n"), "add a slide"
            elif args.delete:
                new_text, what = chunks.delete_chunk(text, block), \
                    f"delete slide {args.slide + 1}"
            elif args.merge:
                new_text, what = chunks.merge_chunk(text, block), \
                    f"merge slide {args.slide + 1}"
            elif args.duplicate:
                new_text, what = chunks.duplicate_chunk(text, block), \
                    f"duplicate slide {args.slide + 1}"
            else:
                new_text, what = chunks.split_chunk(text, block, args.split), \
                    f"split slide {args.slide + 1}"
        except IndexError as e:
            return fail(f"{e} — the deck is out of date with {src}", as_json)
        except (ValueError, OSError) as e:
            return fail(str(e), as_json)

        # Every one of these moves blocks, so everything keyed by block position moves too.
        # Adding a slide and splitting one both open a gap; deleting and merging both close
        # one — a merge closes the gap where the block it absorbed used to be.
        blocks = chunks.count_chunks(text)
        if args.new:
            order = chunks.insert_order(blocks, at)
        elif args.duplicate:
            order = chunks.insert_order(blocks, block + 1)
        elif args.split is not None:
            order = chunks.insert_order(blocks, block + 1)
        elif args.merge:
            order = chunks.delete_order(blocks, block + 1)
        else:
            order = chunks.delete_order(blocks, block)
        extra = follow_keys(deck_dir, out_dir, src, chunks.permutation(order))

        with open(md_path) as f:
            on_disk = f.read()
        history.record(out_dir, src, on_disk, new_text, what, extra)
        tmp = md_path + ".edit.tmp"
        with open(tmp, "w") as f:
            f.write(new_text)
        os.replace(tmp, md_path)

        result = {"ok": True, "file": src, "block": block if args.delete else at,
                  "changed": True, "rebuilt": False,
                  "removed": shared if args.delete else 0}
        if not args.no_rebuild:
            before = manifest.outputs(out_dir)
            rc = rebuild(deck_dir, deck)
            result["outputs"] = manifest.changed_since(before, out_dir)
            result["rebuilt"] = rc == 0
            if rc != 0:
                result["ok"] = False
                result["error"] = f"refract.py exited with {rc}"
        if as_json:
            print(json.dumps(result))
        else:
            print(("added a slide at" if args.new else "removed") + f" block {result['block']}"
                  f" of {src}" + ("" if result["rebuilt"] else " (not rebuilt)"))
        return 0 if result["ok"] else 1

    if args.read:
        try:
            source = chunks.read_chunk(text, block)
        except IndexError as e:
            return fail(f"{e} — the deck is out of date with {src}", as_json)
        print(json.dumps({"ok": True, "file": src, "block": block, "slides": shared,
                          "text": source}))
        return 0

    with open(args.write) as f:
        replacement = f.read()
    try:
        new_text = chunks.replace_chunk(text, block, replacement)
    except IndexError as e:
        return fail(f"{e} — the deck is out of date with {src}", as_json)

    changed = new_text != text
    result = {"ok": True, "file": src, "block": block, "changed": changed, "rebuilt": False}
    if changed:
        history.record(out_dir, src, text, new_text, f"edit slide {args.slide + 1}")
        # Temp file then rename, so an interrupted write can never leave a half-written
        # slides.md — the file the whole deck is made of.
        tmp = md_path + ".edit.tmp"
        with open(tmp, "w") as f:
            f.write(new_text)
        os.replace(tmp, md_path)

    if changed and not args.no_rebuild:
        before = manifest.outputs(out_dir)
        rc = rebuild(deck_dir, deck)
        result["outputs"] = manifest.changed_since(before, out_dir)
        result["rebuilt"] = rc == 0
        if rc != 0:
            result["ok"] = False
            result["error"] = f"refract.py exited with {rc}"

    if as_json:
        print(json.dumps(result))
    elif not changed:
        print("nothing to do: the slide is unchanged")
    else:
        print(f"wrote block {block} of {src}"
              + ("" if result["rebuilt"] else " (not rebuilt)"))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
