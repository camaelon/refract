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
import time
from dataclasses import replace

from refractkit.deck import load_deck, resolve_blocks
from refractkit.render import (build_doc, build_graph_transition_doc, build_push_doc,
                               build_same_doc, build_transition_doc, is_graph_slide,
                               slide_type, PUSH_DURATION)
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


def apply_agenda(slides: list) -> list:
    """Number ``section`` slides and expand any ``:: agenda`` slide into a table of
    contents listing those numbered sections."""
    sections = []  # (number, title)
    n = 0
    for slide in slides:
        if slide_meta_type(slide) == "section" and slide.get("title"):
            n += 1
            sections.append((n, slide["title"]))
            slide["title"] = f"{n}. {slide['title']}"

    out = []
    for slide in slides:
        if slide_meta_type(slide) == "agenda":
            items = [{"level": 0, "text": f"{num}.  {title}"} for num, title in sections]
            out.append({
                "meta": {"type": "content", "params": (slide.get("meta") or {}).get("params", ""),
                         "flags": [], "overrides": {}, "ratio": None},
                "title": slide.get("title") or "Agenda",
                "blocks": [{"kind": "bullets", "items": items}],
                "notes": None,
                "base_dir": slide.get("base_dir", "."),
            })
        else:
            out.append(slide)
    return out


def slide_meta_type(slide: dict) -> str:
    return ((slide.get("meta") or {}).get("type") or "").lower()


def expand_fragments(slides: list) -> list:
    """Expand slides flagged ``fragment`` into one slide per cumulative top-level
    bullet, so bullets reveal progressively. Non-fragment slides pass through."""
    out = []
    for slide in slides:
        meta = slide.get("meta") or {}
        if "fragment" not in meta.get("flags", []):
            out.append(slide)
            continue
        # Find the (first) bullets block; reveal its top-level groups one at a time.
        bidx = next((k for k, b in enumerate(slide["blocks"]) if b["kind"] == "bullets"), None)
        if bidx is None:
            out.append(slide)
            continue
        items = slide["blocks"][bidx]["items"]
        # Group each top-level bullet with its following sub-bullets.
        groups, cur = [], []
        for it in items:
            if it["level"] == 0 and cur:
                groups.append(cur); cur = []
            cur.append(it)
        if cur:
            groups.append(cur)
        for step in range(1, len(groups) + 1):
            revealed = [it for g in groups[:step] for it in g]
            new_blocks = list(slide["blocks"])
            new_blocks[bidx] = {"kind": "bullets", "items": revealed}
            out.append({**slide, "blocks": new_blocks})
    return out


def theme_overrides(overrides: dict, theme) -> dict:
    """Map per-slide ``key=value`` metadata to Theme field changes."""
    changes = {}
    if "bg" in overrides or "background" in overrides:
        changes["background"] = overrides.get("bg", overrides.get("background"))
    if "accent" in overrides:
        changes["accent"] = overrides["accent"]
    if "title_color" in overrides:
        changes["title_color"] = overrides["title_color"]
    if "body_color" in overrides:
        changes["body_color"] = overrides["body_color"]
    if "shader" in overrides:
        val = overrides["shader"]
        # shader=none disables the background shader on this slide.
        changes["shaders"] = {} if val in ("none", "off", "false") else theme.shaders
    return changes


def find_viewer(repo_root: str) -> str | None:
    cand = os.path.join(repo_root, "prebuilt", "rcviewer")
    return cand if os.path.isfile(cand) else None


def export_deck(viewer: str, out_dir: str, width: int, height: int,
                pdf: str | None, images: str | None) -> None:
    """Export the generated deck to a PDF and/or a directory of PNGs via the viewer."""
    if pdf:
        subprocess.run([viewer, "--pdf", out_dir, pdf, str(width), str(height)])
        print(f"exported {pdf}")
    if images:
        os.makedirs(images, exist_ok=True)
        subprocess.run([viewer, "--screenshot-dir", out_dir, images, str(width), str(height)])
        print(f"exported images to {images}")


def watch_mtime(deck_dir: str) -> float:
    """Latest mtime across slides.md, settings.toml and everything under includes/."""
    latest = 0.0
    for rel in ("slides.md", "settings.toml", "shader.sksl"):
        p = os.path.join(deck_dir, rel)
        if os.path.isfile(p):
            latest = max(latest, os.path.getmtime(p))
    inc = os.path.join(deck_dir, "includes")
    for root, _, files in os.walk(inc):
        for f in files:
            try:
                latest = max(latest, os.path.getmtime(os.path.join(root, f)))
            except OSError:
                pass
    return latest


def main() -> int:
    ap = argparse.ArgumentParser(description="markdown deck -> RemoteCompose .rc slides")
    ap.add_argument("deck", nargs="?", default=".", help="deck directory containing slides.md")
    ap.add_argument("--width", type=int, default=None, help="slide width (default 1600 or settings.toml)")
    ap.add_argument("--height", type=int, default=None, help="slide height (default 900 or settings.toml)")
    ap.add_argument("--debug", action="store_true", help="outline each component with a 1px red border")
    ap.add_argument("--transitions", action="store_true",
                    help="emit each slide as a StateLayout that crossfades from the previous slide")
    ap.add_argument("--json", action="store_true",
                    help="keep the intermediate JSON documents in out/json/ (default: discard)")
    ap.add_argument("--pdf", nargs="?", const="", default=None,
                    help="export the deck to a PDF (default <deck>/out/deck.pdf)")
    ap.add_argument("--images", nargs="?", const="", default=None,
                    help="export each slide to a PNG (default <deck>/out/images/)")
    ap.add_argument("--watch", action="store_true",
                    help="regenerate whenever slides.md / settings.toml / includes change")
    ap.add_argument("--json-only", action="store_true", help="emit JSON only; do not run json2rc")
    ap.add_argument("--json2rc", default=None, help="path to the json2rc launcher (default: auto-detect)")
    args = ap.parse_args()

    if args.watch:
        deck_dir = os.path.abspath(args.deck)
        print(f"watching {deck_dir} … (Ctrl-C to stop)")
        last = -1.0
        try:
            while True:
                cur = watch_mtime(deck_dir)
                if cur != last:
                    last = cur
                    run_once(args)
                    print("— waiting for changes —")
                time.sleep(0.5)
        except KeyboardInterrupt:
            print("\nstopped.")
            return 0

    return run_once(args)


def run_once(args) -> int:
    try:
        slides = load_deck(args.deck, {os.path.abspath(args.deck)})
    except FileNotFoundError as e:
        print(e, file=sys.stderr)
        return 1
    slides = apply_agenda(expand_fragments(slides))
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
    for d, exts in ((out_dir, (".rc", ".url")), (json_dir, (".json",))):
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

    speakers = settings.get("speakers", {})

    pairs = []       # (json_path, rc_path) to convert
    copies = []      # (src, dst) whole-slide passthroughs (rc / video)
    notes = []       # (index, title, notes) speaker notes
    prev = None      # (slide, blocks) of the previous non-passthrough slide
    for i, slide in enumerate(slides):
        blocks = resolve_blocks(slide)
        name = slug(slide, i)
        rc_path = os.path.join(out_dir, name + ".rc")
        if slide.get("notes"):
            notes.append((i + 1, slide.get("title") or f"Slide {i + 1}", slide["notes"]))

        # Web link: write a ".url" sidecar next to the slide's .rc. The viewer reads it
        # and opens an interactive web overlay for that URL when the presenter presses W.
        weblink = next((b for b in blocks if b["kind"] == "weblink"), None)
        if weblink:
            with open(os.path.join(out_dir, name + ".url"), "w") as f:
                f.write(weblink["url"] + "\n")

        # Video slide: copy the video into out/ (the C++ viewer plays it in the slideshow).
        video = next((b for b in blocks if b["kind"] == "video"), None)
        if video:
            dst = os.path.join(out_dir, name + os.path.splitext(video["path"])[1].lower())
            copies.append((video["path"], dst))
            print(f"copy {dst}  [video]")
            prev = None
            continue

        # Lone prebuilt .rc (no title / other content): whole-slide passthrough.
        if (not slide.get("title") and len(blocks) == 1
                and blocks[0]["kind"] == "rc_include" and not blocks[0].get("json")):
            copies.append((blocks[0]["path"], rc_path))
            print(f"copy {rc_path}  [rc passthrough]")
            prev = None
            continue

        # Per-slide theme: speaker accent + author attribution + inline overrides.
        meta = slide.get("meta") or {}
        changes = {}
        speaker = meta.get("params", "")
        if speaker in speakers:
            changes["accent"] = speakers[speaker]
        # ``@author`` attribution: use that author's colour as this slide's accent
        # and surface the name in the chrome.
        author = meta.get("author")
        if author:
            changes["slide_author"] = author
            if author in theme.authors:
                changes["accent"] = theme.authors[author]
        # Transition overlay FX (the [shader.transition] shader) is opt-in per slide:
        # only drawn on a slide's transition when it requests `transition_fx=on`.
        fx = meta.get("overrides", {}).get("transition_fx", "").lower()
        if fx not in ("on", "true", "1", "yes"):
            changes["transition_shader"] = ""
        changes.update(theme_overrides(meta.get("overrides", {}), theme))
        stheme = replace(theme, **changes) if changes else theme

        total = len(slides)
        # Transition style: per-slide `transition=` override > [transition] style > fade.
        style = meta.get("overrides", {}).get("transition", trans_cfg.get("style", "fade"))
        # Push/slide duration (seconds): per-slide `transition_duration=` > [transition]
        # duration > default. Larger = slower.
        push_dur = float(meta.get("overrides", {}).get(
            "transition_duration", trans_cfg.get("duration", PUSH_DURATION)))
        is_same = meta.get("type", "").lower() == "same"
        if is_same and prev is not None:
            # `:: same` — shared-element transition from the previous slide (always on,
            # independent of --transitions, since marking a slide `same` is the opt-in).
            doc = build_same_doc(prev, (slide, blocks), stheme, width, height, i, args.debug, total)
            tag = "same"
        elif transitions and prev is not None and is_graph_slide(prev[1]) and is_graph_slide(blocks):
            doc = build_graph_transition_doc(prev, (slide, blocks), stheme, width, height, i, args.debug, total)
            tag = "graph-morph"
        elif transitions and prev is not None and style in ("push", "slide", "slide-left"):
            doc = build_push_doc(prev, (slide, blocks), stheme, width, height, i, args.debug, total, duration=push_dur)
            tag = "push"
        elif transitions and prev is not None and style in ("slide-up", "push-up"):
            doc = build_push_doc(prev, (slide, blocks), stheme, width, height, i, args.debug, total, axis="y", duration=push_dur)
            tag = "push-up"
        elif transitions and prev is not None:
            doc = build_transition_doc(prev, (slide, blocks), stheme, width, height, i, args.debug, total)
            tag = "transition"
        else:
            # No previous slide (e.g. the title): render statically — the first slide
            # has nothing to transition in from; its "out" is animated by the next slide.
            doc = build_doc(slide, blocks, stheme, width, height, i, args.debug, total)
            tag = slide_type(slide)
        json_path = os.path.join(json_dir, name + ".json")
        with open(json_path, "w") as f:
            json.dump(doc, f, indent=2)
        pairs.append((json_path, rc_path))
        print(f"wrote {json_path}  [{tag}]")
        prev = (slide, blocks)

    for src, dst in copies:
        shutil.copyfile(src, dst)

    # Speaker notes → a presenter markdown file.
    if notes:
        notes_path = os.path.join(out_dir, "notes.md")
        with open(notes_path, "w") as f:
            f.write("# Speaker notes\n\n")
            for n, title, text in notes:
                f.write(f"## {n}. {title}\n\n{text}\n\n")
        print(f"wrote {notes_path}  [{len(notes)} notes]")

    keep_json = args.json or args.json_only
    if args.json_only:
        return 0

    json2rc = args.json2rc or find_json2rc(repo_root)
    if not json2rc:
        print("json2rc launcher not found. Build it: (cd json2rc && ./gradlew installDist)\n"
              "or pass --json-only to stop at JSON.", file=sys.stderr)
        return 2

    rc = 0
    if pairs:
        cmd = [json2rc]
        for json_path, rc_path in pairs:
            cmd += [json_path, rc_path]
        rc = subprocess.run(cmd).returncode

    # The JSON is just an intermediate for json2rc; discard it unless asked to keep.
    if not keep_json:
        for json_path, _ in pairs:
            try:
                os.remove(json_path)
            except OSError:
                pass
        try:
            os.rmdir(json_dir)
        except OSError:
            pass

    # Optional export to PDF / images via the viewer.
    if args.pdf is not None or args.images is not None:
        viewer = find_viewer(repo_root)
        if not viewer:
            print("rcviewer not found in prebuilt/ — cannot export.", file=sys.stderr)
        else:
            pdf = None
            if args.pdf is not None:
                pdf = args.pdf or os.path.join(out_dir, "deck.pdf")
            images = None
            if args.images is not None:
                images = args.images or os.path.join(out_dir, "images")
            export_deck(viewer, out_dir, width, height, pdf, images)

    return rc


if __name__ == "__main__":
    raise SystemExit(main())
