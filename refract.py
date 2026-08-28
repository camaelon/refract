#!/usr/bin/env python3
"""refract — turn a simple markdown slide deck into RemoteCompose slides.

Pipeline:  markdown -> component JSON (androidx format) -> [json2rc] -> .rc

Deck layout on disk::

    <deck>/
      slides.md          # the deck
      settings.toml      # optional per-deck settings (colours, size, transitions)
      includes/          # images, sub-decks, .rc / .json resources
      out/               # generated .rc files          (created)
      out/json/          # generated .json documents     (created)

The implementation lives in the ``refractkit`` package; this file is just the CLI.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys

from refractkit.deck import load_deck, resolve_blocks
from refractkit.render import (build_doc, build_graph_transition_doc, build_transition_doc,
                               graph_block, slide_type)
from refractkit.settings import load_settings
from refractkit.theme import build_theme


def slug(slide: dict, index: int) -> str:
    label = slide.get("title") or (slide.get("meta") or {}).get("type") or "slide"
    base = re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_")
    return f"{index + 1:02d}_{base or 'slide'}"


def find_json2rc(repo_root: str) -> str | None:
    for rel in ("prebuilt/json2rc/bin/json2rc",
                "json2rc/build/install/json2rc/bin/json2rc"):
        cand = os.path.join(repo_root, rel)
        if os.path.isfile(cand):
            return cand
    return None


def main() -> int:
    ap = argparse.ArgumentParser(description="markdown deck -> RemoteCompose .rc slides")
    ap.add_argument("deck", nargs="?", default=".", help="deck directory containing slides.md")
    ap.add_argument("--width", type=int, default=None, help="slide width (default 1600 or settings.toml)")
    ap.add_argument("--height", type=int, default=None, help="slide height (default 900 or settings.toml)")
    ap.add_argument("--debug", action="store_true", help="outline each component with a 1px red border")
    ap.add_argument("--transitions", action="store_true",
                    help="emit each slide as a StateLayout that crossfades from the previous slide")
    ap.add_argument("--json-only", action="store_true", help="emit JSON only; do not run json2rc")
    ap.add_argument("--json2rc", default=None, help="path to the json2rc launcher (default: auto-detect)")
    args = ap.parse_args()

    try:
        slides = load_deck(args.deck, {os.path.abspath(args.deck)})
    except FileNotFoundError as e:
        print(e, file=sys.stderr)
        return 1
    if not slides:
        print("no slides found", file=sys.stderr)
        return 1

    deck_dir = os.path.abspath(args.deck)
    out_dir = os.path.join(deck_dir, "out")
    json_dir = os.path.join(out_dir, "json")
    os.makedirs(json_dir, exist_ok=True)
    repo_root = os.path.dirname(os.path.abspath(__file__))

    # Fresh output: remove previously generated files so renamed or deleted slides
    # don't leave stale .rc/.json behind (the player would keep showing them).
    for d, exts in ((out_dir, (".rc",)), (json_dir, (".json",))):
        for fname in os.listdir(d):
            if fname.endswith(exts):
                os.remove(os.path.join(d, fname))

    # Settings precedence: CLI flag > settings.toml > built-in default.
    settings = load_settings(deck_dir)
    theme = build_theme(settings, deck_dir)
    slide_cfg = settings.get("slide", {})
    trans_cfg = settings.get("transition", {})
    width = args.width if args.width is not None else slide_cfg.get("width", 1600)
    height = args.height if args.height is not None else slide_cfg.get("height", 900)
    transitions = args.transitions or bool(trans_cfg.get("enabled", False))

    pairs = []       # (json_path, rc_path) to convert
    copies = []      # (src_rc, dst_rc) whole-slide passthroughs
    prev = None      # (slide, blocks) of the previous non-passthrough slide
    for i, slide in enumerate(slides):
        blocks = resolve_blocks(slide)
        name = slug(slide, i)
        rc_path = os.path.join(out_dir, name + ".rc")

        passthrough = (not slide.get("title") and len(blocks) == 1
                       and blocks[0]["kind"] == "rc_include")
        if passthrough:
            copies.append((blocks[0]["path"], rc_path))
            print(f"copy {rc_path}  [rc passthrough]")
            prev = None  # can't crossfade from a prebuilt .rc
            continue

        if transitions and prev is not None and graph_block(prev[1]) and graph_block(blocks):
            doc = build_graph_transition_doc(prev, (slide, blocks), theme, width, height, i, args.debug)
            tag = "graph-morph"
        elif transitions:
            doc = build_transition_doc(prev, (slide, blocks), theme, width, height, i, args.debug)
            tag = "transition"
        else:
            doc = build_doc(slide, blocks, theme, width, height, i, args.debug)
            tag = slide_type(slide)
        json_path = os.path.join(json_dir, name + ".json")
        with open(json_path, "w") as f:
            json.dump(doc, f, indent=2)
        pairs.append((json_path, rc_path))
        print(f"wrote {json_path}  [{tag}]")
        prev = (slide, blocks)

    for src, dst in copies:
        shutil.copyfile(src, dst)

    if args.json_only:
        return 0

    json2rc = args.json2rc or find_json2rc(repo_root)
    if not json2rc:
        print("json2rc launcher not found. Build it: (cd json2rc && ./gradlew installDist)\n"
              "or pass --json-only to stop at JSON.", file=sys.stderr)
        return 2

    if not pairs:
        return 0
    cmd = [json2rc]
    for json_path, rc_path in pairs:
        cmd += [json_path, rc_path]
    return subprocess.run(cmd).returncode


if __name__ == "__main__":
    raise SystemExit(main())
