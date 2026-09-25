"""What is in a deck's includes/, and which of it the deck actually uses.

An `includes/` folder collects things over the life of a talk — the screenshot that was
replaced, the diagram from the version that got cut, the clip nobody ended up playing. Working
out which is which by reading the markdown is exactly the sort of thing to get wrong, so this
asks the same code the build asks: the deck is loaded and its blocks resolved by refract's own
resolver, and what comes back with a path is what is used.

That means usage here cannot drift from usage at build time — they are the same answer.
"""

from __future__ import annotations

import os

from .deck import IMAGE_EXTS, VIDEO_EXTS, load_deck, resolve_blocks
from .settings import load_settings


# What each kind of file is called, for something with a list to draw.
KINDS = [
    ("image", IMAGE_EXTS),
    ("video", VIDEO_EXTS),
    ("document", (".rc", ".json")),
    ("code", (".kt", ".kts", ".java", ".py", ".ts", ".js")),
    ("shader", (".sksl",)),
    ("deck", (".md",)),
]


def kind_of(path: str) -> str:
    ext = os.path.splitext(path)[1].lower()
    for name, exts in KINDS:
        if ext in exts:
            return name
    return "other"


def used_by(deck_dir: str) -> dict:
    """Absolute path -> the slides that use it, by their 1-based position in the deck.

    Everything a slide's blocks resolve to, the sub-decks an `:: include` pulls in, and the
    shader files settings.toml points at. A path a slide names but that is not there does not
    appear: there is no asset to have an opinion about.
    """
    deck_dir = os.path.abspath(deck_dir)
    uses: dict[str, list[int]] = {}

    def note(path: str, slide: int) -> None:
        if not path:
            return
        full = os.path.abspath(path)
        if os.path.exists(full):
            uses.setdefault(full, [])
            if slide not in uses[full]:
                uses[full].append(slide)

    try:
        slides = load_deck(deck_dir, {deck_dir})
    except (FileNotFoundError, OSError):
        slides = []

    from .theme import _resolve_asset_path
    from .buildcache import referenced_files
    import json

    def note_with_deps(path: str, slide: int) -> None:
        if not path:
            return
        full = os.path.abspath(path)
        note(full, slide)
        if full.endswith(".json") and os.path.isfile(full):
            try:
                with open(full) as jf:
                    for ref in referenced_files(json.load(jf)):
                        note(ref, slide)
            except (OSError, ValueError):
                pass

    for i, slide in enumerate(slides, start=1):
        # A slide spliced in from a sub-deck is itself evidence that the sub-deck is used, and
        # so is the markdown it was written in.
        note(slide.get("src_file", ""), i)
        sbase = slide.get("base_dir", deck_dir)
        ovr = (slide.get("meta") or {}).get("overrides") or {}
        for k in ("bg", "background", "bg_doc"):
            v = ovr.get(k)
            if isinstance(v, str) and not v.startswith("#"):
                p = _resolve_asset_path(v, sbase, [deck_dir])
                if p:
                    note_with_deps(p, i)
        try:
            blocks = resolve_blocks(slide)
        except (OSError, KeyError):
            continue
        for block in blocks:
            note(block.get("path", ""), i)
            # A framed `.rc` embed prefers its sibling `.json`; both are the asset.
            note(block.get("json", "") or "", i)

    # Shaders and background inclusions, which the theme reads rather than a slide.
    settings = load_settings(deck_dir)
    shader_files = []
    shader = settings.get("shader", {})
    if isinstance(shader, dict):
        for value in [shader] + [v for v in shader.values() if isinstance(v, dict)]:
            if isinstance(value.get("file"), str):
                shader_files.append(value["file"])
    title = settings.get("title", {})
    if isinstance(title, dict):
        ts = title.get("shader")
        if isinstance(ts, str):
            shader_files.append(ts)
        elif isinstance(ts, dict) and isinstance(ts.get("file"), str):
            shader_files.append(ts["file"])
        for k in ("background", "doc", "include"):
            if isinstance(title.get(k), str):
                p = _resolve_asset_path(title[k], deck_dir)
                if p:
                    note_with_deps(p, 0)
    bg_cfg = settings.get("background", {})
    if isinstance(bg_cfg, dict):
        for v in bg_cfg.values():
            if isinstance(v, str):
                p = _resolve_asset_path(v, deck_dir)
                if p:
                    note_with_deps(p, 0)
    elif isinstance(bg_cfg, str):
        p = _resolve_asset_path(bg_cfg, deck_dir)
        if p:
            note_with_deps(p, 0)
    for tbl_name in ("heading", "section"):
        sec_tbl = settings.get(tbl_name, {})
        if isinstance(sec_tbl, dict):
            for sub in sec_tbl.values():
                if isinstance(sub, dict):
                    for k in ("background", "doc", "include", "shader"):
                        v = sub.get(k)
                        if isinstance(v, str):
                            p = _resolve_asset_path(v, deck_dir)
                            if p:
                                note_with_deps(p, 0)
    for name in shader_files:
        note(os.path.join(deck_dir, name), 0)   # slide 0: the deck itself, not one slide

    return uses


def scan(deck_dir: str) -> list[dict]:
    """Every file under includes/, with its size, kind and who uses it.

    Sub-deck folders are walked into: a deck included by another is a directory of assets like
    any other, and its own images are used or not on their own terms.
    """
    deck_dir = os.path.abspath(deck_dir)
    includes = os.path.join(deck_dir, "includes")
    uses = used_by(deck_dir)

    found = []
    for root, dirs, names in os.walk(includes):
        dirs[:] = sorted(d for d in dirs if not d.startswith("."))
        for name in sorted(names):
            if name.startswith("."):
                continue
            path = os.path.join(root, name)
            try:
                size = os.path.getsize(path)
            except OSError:
                continue
            slides = uses.get(os.path.abspath(path), [])
            found.append({
                "path": os.path.relpath(path, deck_dir),
                "name": name,
                "kind": kind_of(path),
                "size": size,
                "slides": slides,
                "used": bool(slides),
            })
    return found
