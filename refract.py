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
from refractkit.measure import content_height
from refractkit.render import (build_doc, build_graph_transition_doc, build_push_doc,
                               build_same_doc, build_scroll_doc, build_transition_doc,
                               content_metrics, is_graph_slide, scroll_spec, slide_type,
                               split_left_metrics, split_panes, PUSH_DURATION)
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
    """Number ``section`` slides and synthesize an outline from those sections. A
    ``:: outline`` slide renders the sections as a styled list (numbers in the deck's
    primary colour); ``:: agenda`` is a plainer bullet-list alias. The section number is
    stored on the slide (``section_number``) rather than baked into the title, so the
    renderer can colour it."""
    sections = []  # (number, title)
    n = 0
    for slide in slides:
        if slide_meta_type(slide) == "section" and slide.get("title"):
            n += 1
            sections.append((n, slide["title"]))
            slide["section_number"] = n

    out = []
    for slide in slides:
        stype = slide_meta_type(slide)
        if stype in ("outline", "agenda"):
            meta = slide.get("meta") or {}
            base = {
                "meta": {"type": "content", "params": meta.get("params", ""),
                         "flags": [], "overrides": meta.get("overrides", {}), "ratio": None},
                "title": slide.get("title") or ("Outline" if stype == "outline" else "Agenda"),
                "notes": None,
                "base_dir": slide.get("base_dir", "."),
            }
            if stype == "outline":
                base["blocks"] = [{"kind": "outline",
                                   "items": [{"num": num, "title": title}
                                             for num, title in sections]}]
            else:
                base["blocks"] = [{"kind": "bullets",
                                   "items": [{"level": 0, "text": f"{num}.  {title}"}
                                             for num, title in sections]}]
            out.append(base)
        else:
            out.append(slide)
    return out


def slide_meta_type(slide: dict) -> str:
    return ((slide.get("meta") or {}).get("type") or "").lower()


def intermediate_jsons(pairs: list, json_dir: str) -> list:
    """The json inputs from ``pairs`` that are refract-generated intermediates safe to delete —
    ONLY those living inside ``json_dir``. A source include compiled straight from
    ``includes/`` is never returned, so cleanup can never delete a user's source file."""
    jd = os.path.abspath(json_dir)
    return [jp for jp, _ in pairs if os.path.dirname(os.path.abspath(jp)) == jd]


def slide_accent(slide: dict, theme, speakers: dict) -> str | None:
    """The accent colour a slide is attributed to (speaker or @author), or None."""
    meta = slide.get("meta") or {}
    speaker = meta.get("params", "")
    if speaker in speakers:
        return speakers[speaker]
    author = meta.get("author")
    if author and author in theme.authors:
        return theme.authors[author]
    return None


def compute_sections(slides: list, theme, speakers: dict) -> list:
    """Section spans for the progress bar: one entry per ``section`` slide with its start
    index and the colour of the section's expected speaker — the section slide's own
    attribution, or the first attributed slide within the section, else the deck primary."""
    starts = [i for i, s in enumerate(slides)
              if slide_meta_type(s) == "section" and s.get("title")]
    sections = []
    for si, start in enumerate(starts):
        end = starts[si + 1] if si + 1 < len(starts) else len(slides)
        color = next((c for c in (slide_accent(slides[j], theme, speakers)
                                  for j in range(start, end)) if c), None)
        sections.append({"start": start, "color": color or theme.primary})
    return sections


def _wants_steps(meta: dict, steps_default: bool) -> bool:
    """Whether a slide should be split into multiple .rc files (stepped reveal). Per-slide
    `fragment`/`steps` flags force on; `nosteps`/`nofragment` or `steps=off` force off; else
    the global `[reveal] steps` default applies."""
    flags = meta.get("flags", [])
    if "nosteps" in flags or "nofragment" in flags:
        return False
    if str(meta.get("overrides", {}).get("steps", "")).lower() in ("off", "false", "no", "0"):
        return False
    if "fragment" in flags or "steps" in flags:
        return True
    return steps_default


def expand_fragments(slides: list, steps_default: bool = False) -> list:
    """Expand stepped slides into one .rc per cumulative top-level bullet, so pressing the
    next key reveals the next bullet. Every step after the first is marked ``reveal_step`` so
    it animates that one new bullet in (via the `:: same` diff) rather than re-drawing all."""
    out = []
    for slide in slides:
        meta = slide.get("meta") or {}
        bidx = next((k for k, b in enumerate(slide.get("blocks", []))
                     if b["kind"] == "bullets"), None)
        if bidx is None or not _wants_steps(meta, steps_default):
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
            # A fresh meta per step; steps after the first same-transition from the prior
            # step so only the newly-revealed bullet animates in.
            step_meta = {**meta}
            if step > 1:
                step_meta["reveal_step"] = True
            out.append({**slide, "meta": step_meta, "blocks": new_blocks})
    return out


SCROLL_OVERLAP = 0.12          # fraction of the viewport that consecutive pages share


def _scroll_plan(raw: str, content_h: float, viewport: float) -> tuple:
    """Given the ``scroll`` request (an int or "auto"), the estimated content height and the
    viewport height, return (page_count, [offset per page]). Returns (1, [0.0]) when the
    content already fits or the request is unusable.

    - ``auto``: as many pages as needed, each advancing a fixed step of one viewport (minus a
      small overlap), so per-page motion stays correct even if the height estimate is off.
    - explicit ``N``: exactly N pages, offsets spread evenly across the scrollable range so N
      pages cover the whole content (the author chose the page count deliberately)."""
    import math
    max_off = max(0.0, content_h - viewport)
    if max_off <= 1.0:
        return 1, [0.0]
    if str(raw).strip().lower() == "auto":
        step = max(1.0, viewport * (1.0 - SCROLL_OVERLAP))
        n = int(math.ceil(max_off / step)) + 1
        offs, last = [], None
        for k in range(n):
            off = round(min(k * step, max_off), 2)
            if off == last:
                break
            offs.append(off)
            last = off
        return len(offs), offs
    try:
        n = int(str(raw).strip())
    except ValueError:
        return 1, [0.0]
    if n <= 1:
        return 1, [0.0]
    return n, [round(max_off * k / (n - 1), 2) for k in range(n)]


def expand_scroll(slides: list, theme, width: int, height: int) -> list:
    """Expand ``scroll = N`` / ``scroll = auto`` slides into one .rc per scroll page. Each
    page carries a ``scroll_page`` meta ({index, count, offset, prev_offset, viewport}); the
    renderer clips the content to the viewport and animates it from ``prev_offset`` to
    ``offset`` on load, so pressing next scrolls the content. Only single-column content
    layouts scroll (split/centered slides are left untouched)."""
    out = []
    for slide in slides:
        meta = slide.get("meta") or {}
        raw = (meta.get("overrides") or {}).get("scroll")
        # `:: same` slides carry a *manual* scroll offset (feature handled in the main loop),
        # not an auto-paginated one — leave them for build_same_doc.
        if raw is None or meta.get("type", "").lower() == "same" or meta.get("reveal_step"):
            out.append(slide)
            continue
        stype = slide_type(slide)
        blocks = resolve_blocks(slide)
        if stype in ("title", "section"):
            out.append(slide)          # nothing scrollable on a centred slide
            continue
        panes = split_panes(blocks)
        if stype == "split" and len(panes) > 1:
            # Scroll the first (text) column; the other column stays put.
            col_blocks = [b for pane in panes[:-1] for b in pane]
            col_w, avail_h = split_left_metrics(slide, theme, width, height)
            content_h = content_height(col_blocks, theme.body_size(stype), theme, col_w)
        else:
            col_w, avail_h, _ = content_metrics(slide, theme, width, height)
            content_h = content_height(blocks, theme.body_size(stype), theme, col_w)
        n, offs = _scroll_plan(raw, content_h, avail_h)
        if n <= 1:
            out.append(slide)
            continue
        vp = round(avail_h, 2)
        for k in range(n):
            pmeta = {**meta, "scroll_page": {
                "index": k, "count": n, "offset": offs[k],
                "prev_offset": (offs[k - 1] if k > 0 else None), "viewport": vp}}
            out.append({**slide, "meta": pmeta})
    return out


def _same_scroll_frac(meta: dict) -> float:
    """The manual scroll offset a `:: same` slide requests, in *viewport fractions* (``scroll=1``
    = one screenful down, ``0.5`` = half). 0 when absent or unparseable."""
    raw = (meta.get("overrides") or {}).get("scroll")
    if raw is None:
        return 0.0
    try:
        return max(0.0, float(str(raw).strip()))
    except ValueError:
        return 0.0


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
    if "autosize" in overrides:
        changes["autosize"] = str(overrides["autosize"]).lower() not in ("off", "false", "no", "0")
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
    deck_dir = os.path.abspath(args.deck)
    # Settings precedence: CLI flag > settings.toml > built-in default. Loaded before the
    # deck so the reveal-steps default can drive fragment expansion.
    settings = load_settings(deck_dir)
    theme = build_theme(settings, deck_dir)
    try:
        slides = load_deck(args.deck, {os.path.abspath(args.deck)})
    except FileNotFoundError as e:
        print(e, file=sys.stderr)
        return 1
    slides = apply_agenda(expand_fragments(slides, theme.reveal_steps))
    if not slides:
        print("no slides found", file=sys.stderr)
        return 1

    out_dir = os.path.join(deck_dir, "out")
    json_dir = os.path.join(out_dir, "json")
    media_dir = os.path.join(out_dir, "media")
    os.makedirs(json_dir, exist_ok=True)
    os.makedirs(media_dir, exist_ok=True)
    repo_root = os.path.dirname(os.path.abspath(__file__))

    # Fresh output: remove previously generated files so renamed or deleted slides
    # don't leave stale .rc/.json/asset behind (the player would keep showing them).
    # Videos live in out/ (lone-video slides) and out/media/ (embedded); clear both so a
    # renamed clip doesn't linger as an orphan slide/page.
    vid_exts = (".mp4", ".mov", ".m4v", ".webm")
    for d, exts in ((out_dir, (".rc",) + vid_exts), (json_dir, (".json",)),
                    (media_dir, (".rc",) + vid_exts)):
        for fname in os.listdir(d):
            if fname.endswith(exts):
                os.remove(os.path.join(d, fname))

    slide_cfg = settings.get("slide", {})
    trans_cfg = settings.get("transition", {})
    width = args.width if args.width is not None else slide_cfg.get("width", 1600)
    height = args.height if args.height is not None else slide_cfg.get("height", 900)
    transitions = args.transitions or bool(trans_cfg.get("enabled", False))

    # Expand `scroll = N` / `scroll = auto` slides into one page per scroll window (needs the
    # final width/height to measure overflow against the real content area).
    slides = expand_scroll(slides, theme, width, height)

    speakers = settings.get("speakers", {})
    # Section spans for the progress bar (marks + per-section speaker colours). Deck-wide,
    # so attach to the base theme; per-slide themes are replace()-copies that inherit it.
    theme.chrome_sections = compute_sections(slides, theme, speakers)

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

        # A lone video (no title, nothing else) is a whole-slide passthrough the viewer
        # plays directly. Otherwise videos are embedded in the page (custom component).
        videos = [b for b in blocks if b["kind"] == "video"]
        if videos and not slide.get("title") and len(blocks) == 1:
            v = videos[0]
            dst = os.path.join(out_dir, name + os.path.splitext(v["path"])[1].lower())
            copies.append((v["path"], dst))
            print(f"copy {dst}  [video]")
            prev = None
            continue
        # Embedded videos: copy each into out/media/ (NOT the top-level out/, where a bare
        # .mp4 would be picked up as its own standalone slide/PDF page). The custom component
        # references it as media/<name>; the video host resolves that relative to the slide
        # directory, same as the embedded-rc host.
        for v in videos:
            base = os.path.basename(v["path"])
            copies.append((v["path"], os.path.join(out_dir, "media", base)))
            v["src"] = f"media/{base}"

        # Lone prebuilt .rc (no title / other content): whole-slide passthrough.
        if (not slide.get("title") and len(blocks) == 1
                and blocks[0]["kind"] == "rc_include" and not blocks[0].get("json")):
            copies.append((blocks[0]["path"], rc_path))
            print(f"copy {rc_path}  [rc passthrough]")
            prev = None
            continue

        # Media embedded as a nested document (out/media/<name>.rc, so the rc-document host
        # loads it by name and the viewer doesn't list it as a slide). Three cases:
        #   • rc_include with no .json  → copy the binary .rc as-is.
        #   • rc/json with a crop/fit   → *frame* it (crop/scale need a fixed-size document, so
        #     we embed rather than splice flat): copy the .rc, or compile the .json via json2rc.
        for b in blocks:
            framed = b.get("crop") or b.get("fit")
            if b["kind"] == "rc_include" and not b.get("json"):
                base = os.path.basename(b["path"])
                copies.append((b["path"], os.path.join(out_dir, "media", base)))
                b["src"] = f"media/{base}"
            elif framed and b["kind"] == "rc_include" and b.get("json"):
                base = os.path.basename(b["path"])                 # the prebuilt .rc binary
                copies.append((b["path"], os.path.join(out_dir, "media", base)))
                b.update(json=None, src=f"media/{base}")           # → render_rc_embed
            elif framed and b["kind"] == "json_include":
                # Compile a COPY placed in json_dir (an intermediate that gets cleaned up),
                # never the source in includes/ — passing the source to `pairs` would let the
                # cleanup delete it.
                stem = os.path.splitext(os.path.basename(b["path"]))[0]
                media_rc = os.path.join(out_dir, "media", stem + ".rc")
                interm = os.path.join(json_dir, f"embed_{stem}.json")
                copies.append((b["path"], interm))                 # source → intermediate copy
                pairs.append((interm, media_rc))                   # compile the copy → .rc
                b.update(kind="rc_include", json=None, src=f"media/{stem}.rc")

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
        # Per-slide content-reveal override: `reveal=stagger` / `reveal=immediate`.
        reveal_ov = meta.get("overrides", {}).get("reveal")
        if reveal_ov:
            changes["content_reveal"] = reveal_ov.lower()
        # Per-slide-type transition defaults live in [transition.<type>] (e.g.
        # [transition.section] style="slide-up" duration=0.9 fx=true). Precedence for every
        # knob: per-slide `transition*=` override > [transition.<type>] > [transition] > default.
        stype = slide_type(slide)
        type_trans = trans_cfg.get(stype, {})
        if not isinstance(type_trans, dict):
            type_trans = {}
        # Transition overlay FX (the [shader.transition] shader) is opt-in: a slide draws it
        # only when it — or its slide-type default — requests fx.
        fx_raw = meta.get("overrides", {}).get("transition_fx")
        fx_on = (str(fx_raw).lower() in ("on", "true", "1", "yes")) if fx_raw is not None \
                else bool(type_trans.get("fx", False))
        if not fx_on:
            changes["transition_shader"] = ""
        changes.update(theme_overrides(meta.get("overrides", {}), theme))
        stheme = replace(theme, **changes) if changes else theme

        total = len(slides)
        style = (meta.get("overrides", {}).get("transition")
                 or type_trans.get("style") or trans_cfg.get("style", "fade"))
        # Push/slide duration (seconds); larger = slower.
        push_dur = float(meta.get("overrides", {}).get("transition_duration",
                         type_trans.get("duration", trans_cfg.get("duration", PUSH_DURATION))))
        # `:: same`, or a stepped-reveal step (both animate only the changed content in
        # place, independent of --transitions).
        is_same = meta.get("type", "").lower() == "same" or bool(meta.get("reveal_step"))
        # Scroll page: a later page animates its content scroll from the previous page; the
        # first page (prev_offset None) is a normal slide whose content is clipped to the
        # viewport (scroll_static), so overflow past the first window stays hidden.
        sp = meta.get("scroll_page")
        scroll_static = {"viewport": sp["viewport"], "y": 0.0} if sp else None
        if sp and sp.get("prev_offset") is not None:
            doc = build_scroll_doc(slide, blocks, stheme, width, height, i, args.debug, total,
                                   sp["prev_offset"], sp["offset"], sp["viewport"])
            tag = f"scroll {sp['index'] + 1}/{sp['count']}"
        elif is_same and prev is not None:
            # Scroll-aware `:: same`: a manual per-slide offset (viewport fractions) that
            # scrolls the (overflowing) content from the previous same-slide's offset. The
            # scroll animates on the same $__st progress as the content diff. Presence of the
            # `scroll` key on either slide (even `scroll=0`) opts the content into clipping.
            prev_meta = prev[0].get("meta") or {}
            has_scroll = ("scroll" in (meta.get("overrides") or {})
                          or "scroll" in (prev_meta.get("overrides") or {}))
            same_scroll = None
            if has_scroll:
                _, vp, _ = content_metrics(slide, stheme, width, height)
                same_scroll = scroll_spec(_same_scroll_frac(prev_meta) * vp,
                                          _same_scroll_frac(meta) * vp, vp)
            doc = build_same_doc(prev, (slide, blocks), stheme, width, height, i, args.debug, total,
                                 scroll=same_scroll)
            tag = "step" if meta.get("reveal_step") else "same"
        elif transitions and prev is not None and is_graph_slide(prev[1]) and is_graph_slide(blocks):
            doc = build_graph_transition_doc(prev, (slide, blocks), stheme, width, height, i, args.debug, total)
            tag = "graph-morph"
        elif transitions and prev is not None and style in ("push", "slide", "slide-left"):
            doc = build_push_doc(prev, (slide, blocks), stheme, width, height, i, args.debug, total, duration=push_dur, scroll=scroll_static)
            tag = "push"
        elif transitions and prev is not None and style in ("slide-up", "push-up"):
            doc = build_push_doc(prev, (slide, blocks), stheme, width, height, i, args.debug, total, axis="y", duration=push_dur, scroll=scroll_static)
            tag = "push-up"
        elif transitions and prev is not None:
            doc = build_transition_doc(prev, (slide, blocks), stheme, width, height, i, args.debug, total, scroll=scroll_static)
            tag = "transition"
        else:
            # No previous slide (e.g. the title): render statically — the first slide
            # has nothing to transition in from; its "out" is animated by the next slide.
            doc = build_doc(slide, blocks, stheme, width, height, i, args.debug, total,
                            scroll=scroll_static)
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
        for json_path in intermediate_jsons(pairs, json_dir):
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
