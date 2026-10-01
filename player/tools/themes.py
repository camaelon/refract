#!/usr/bin/env python3
"""The deck's theme presets, for whatever offers them to somebody.

A preset is a `theme/<name>.toml` the markdown picks with `:: as: <name>`. The file holds
the whole look of a slide — type, background, title size and weight, the colours — and the
player's theme panel lists them, so this reports what each one is and what it looks like
without the panel needing to read TOML or know refract's grammar.

    python3 player/tools/themes.py <deck>/out [--json]

Each preset comes back with the colours and sizes a swatch is drawn from, resolved the way
refract resolves them: the preset's own keys, falling back to the deck's settings.toml, so a
preset that only sets a title size still says what colour that title will be.
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

try:
    from refractkit import as_theme, manifest
    from refractkit.settings import load_settings
    from refractkit.theme import build_theme
except ImportError as e:                        # pragma: no cover - a broken checkout
    print(json.dumps({"ok": False, "error": f"cannot import refractkit: {e}"}))
    raise SystemExit(1)


def theme_dirs(deck_dir: str) -> list[str]:
    """Where a deck keeps its presets, in the order refract looks."""
    return [os.path.join(deck_dir, "theme"), os.path.join(deck_dir, "themes")]


def preset_files(deck_dir: str) -> list[str]:
    """Every `<name>.toml` a `:: as:` could name, by name, without repeats."""
    seen: dict[str, str] = {}
    for directory in theme_dirs(deck_dir):
        for path in sorted(glob.glob(os.path.join(directory, "*.toml"))):
            name = os.path.splitext(os.path.basename(path))[0]
            seen.setdefault(name, path)
    return [seen[name] for name in sorted(seen)]


def usage(out_dir: str) -> dict:
    """Which slides each preset is on, by their 1-based position: the manifest records the
    theme every slide was built with, so this is a read rather than a parse."""
    used: dict[str, list[int]] = {}
    try:
        deck = manifest.load(out_dir)
    except Exception:                           # noqa: BLE001 - no manifest, no usage
        return used
    for slide in deck.get("slides", []):
        name = slide.get("theme")
        if name:
            used.setdefault(name, []).append(int(slide.get("index", 0)) + 1)
    return used


def describe(path: str, deck_dir: str, base) -> dict:
    """One preset: its name, the slide type it makes, and the look of it.

    The colours are what a slide would actually be drawn in — the preset's own where it sets
    them, the deck's where it does not — because a swatch of the preset's half of the answer
    would be a swatch of something nobody ever sees."""
    name = os.path.splitext(os.path.basename(path))[0]
    parsed = as_theme.parse_theme_toml(as_theme.load_theme_toml(name, deck_dir))
    overrides = parsed.get("overrides", {})

    def number(key, fallback):
        try:
            return round(float(overrides[key]), 2)
        except (KeyError, TypeError, ValueError):
            return fallback

    stype = parsed.get("type") or "content"
    return {
        "name": name,
        "slides": [],
        "file": os.path.relpath(path, deck_dir),
        "type": stype,
        "bg": overrides.get("bg", base.background),
        "bg_doc": overrides.get("bg_doc", ""),
        "title_color": overrides.get("title_color", base.title_colors.get(stype, base.title_color)),
        "body_color": overrides.get("body_color", base.body_color),
        "accent": overrides.get("accent", base.accent),
        "title_size": number("title_size", round(float(base.title_size(stype)), 2)),
        "body_size": number("body_size", round(float(base.body_size(stype)), 2)),
        "align": overrides.get("h_align", ""),
        "keys": len(overrides),
    }


def themes_of(deck_dir: str, out_dir: str = "") -> dict:
    base = build_theme(load_settings(deck_dir), deck_dir)
    used = usage(out_dir) if out_dir else {}
    themes = []
    for path in preset_files(deck_dir):
        preset = describe(path, deck_dir, base)
        preset["slides"] = used.get(preset["name"], [])
        themes.append(preset)
    return {"ok": True, "deck": os.path.basename(deck_dir.rstrip("/")), "dir": deck_dir,
            "themes": themes}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    ap.add_argument("out_dir", help="the deck's out/ directory (the one holding deck.json)")
    ap.add_argument("--json", action="store_true", help="(the default, and the only form)")
    args = ap.parse_args()
    out_dir = os.path.abspath(args.out_dir)
    try:
        deck = manifest.source_dir(out_dir, manifest.load(out_dir))
    except (FileNotFoundError, OSError, ValueError) as e:
        print(json.dumps({"ok": False, "error": f"that is not a built deck: {e}"}))
        return 1
    print(json.dumps(themes_of(deck, out_dir), indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
