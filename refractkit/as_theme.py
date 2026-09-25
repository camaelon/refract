"""Slide type 'as' support: load per-slide theme presets from theme/*.toml."""

from __future__ import annotations

import os
import sys
try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib  # type: ignore[no-redef]


def find_theme_toml(name: str, deck_dir: str) -> str | None:
    """Find a theme TOML file by name in deck_dir/theme/, deck_dir/themes/, or deck_dir/."""
    if not name:
        return None
    filename = name if name.endswith(".toml") else f"{name}.toml"
    candidates = [
        os.path.join(deck_dir, "theme", filename),
        os.path.join(deck_dir, "themes", filename),
        os.path.join(deck_dir, filename),
    ]
    for cand in candidates:
        if os.path.isfile(cand):
            return os.path.abspath(cand)
    return None


def load_theme_toml(name: str, deck_dir: str) -> dict:
    """Read and parse a theme TOML file."""
    path = find_theme_toml(name, deck_dir)
    if not path:
        return {}
    try:
        with open(path, "rb") as f:
            return tomllib.load(f)
    except Exception as e:
        print(f"warning: failed to load theme {path}: {e}", file=sys.stderr)
        return {}


def parse_theme_toml(data: dict) -> dict:
    """Extract slide layout, ratio, and overrides from a theme TOML dict.

    Supports both flat key/value settings and section tables
    ([theme], [layout], [font], [heading.N], [section], etc.).
    """
    out_type = "content"
    out_ratio = None
    overrides: dict[str, str] = {}

    # 1. Top-level scalar keys
    for k, v in data.items():
        if isinstance(v, dict):
            continue
        if isinstance(v, list):
            if k == "ratio":
                out_ratio = [int(x) for x in v]
            elif k in ("padding", "pad") and len(v) == 4:
                overrides["pad_left"] = str(v[0])
                overrides["pad_top"] = str(v[1])
                overrides["pad_right"] = str(v[2])
                overrides["pad_bottom"] = str(v[3])
            continue
        k_str = str(k).lower()
        if k_str in ("type", "layout", "slide_type"):
            out_type = str(v).lower()
        elif k_str == "ratio":
            if isinstance(v, str) and ":" in v:
                out_ratio = [int(x) for x in v.split(":")]
        elif isinstance(v, bool):
            overrides[k_str] = "true" if v else "false"
        else:
            overrides[k_str] = str(v)

    # 2. [theme] table
    th = data.get("theme")
    if isinstance(th, dict):
        for k, v in th.items():
            if isinstance(v, (dict, list)):
                continue
            k_str = str(k).lower()
            if k_str in ("background", "bg"):
                overrides["bg"] = str(v)
            elif k_str == "bg_doc":
                overrides["bg_doc"] = str(v)
            elif k_str == "title_color":
                overrides["title_color"] = str(v)
            elif k_str == "body_color":
                overrides["body_color"] = str(v)
            elif k_str == "accent":
                overrides["accent"] = str(v)
            elif k_str in ("title_size", "body_size", "title_weight", "body_weight", "title_gap", "title_pad_top"):
                overrides[k_str] = str(v)
            elif isinstance(v, bool):
                overrides[k_str] = "true" if v else "false"
            else:
                overrides[k_str] = str(v)

    # 3. [layout] table
    layout = data.get("layout")
    if isinstance(layout, dict):
        for k, v in layout.items():
            if isinstance(v, list) and k in ("padding", "pad") and len(v) == 4:
                overrides["pad_left"] = str(v[0])
                overrides["pad_top"] = str(v[1])
                overrides["pad_right"] = str(v[2])
                overrides["pad_bottom"] = str(v[3])
            elif not isinstance(v, (dict, list)):
                k_str = str(k).lower()
                if k_str in ("type", "slide_type"):
                    out_type = str(v).lower()
                elif k_str in ("align", "h_align"):
                    overrides["h_align"] = str(v)
                elif k_str in ("valign", "v_align"):
                    overrides["v_align"] = str(v)
                elif k_str in ("pad_left", "pad_top", "pad_right", "pad_bottom", "pane_gap", "gap", "pad"):
                    overrides[k_str] = str(v)

    # 4. [font] table
    font = data.get("font")
    if isinstance(font, dict):
        for k, v in font.items():
            if isinstance(v, (dict, list)):
                continue
            k_str = str(k).lower()
            if k_str == "title":
                overrides["title_size"] = str(v)
            elif k_str in ("body", "content"):
                overrides["body_size"] = str(v)
            elif k_str == "title_weight":
                overrides["title_weight"] = str(v)
            elif k_str == "body_weight":
                overrides["body_weight"] = str(v)
            elif k_str == "heading":
                overrides["h2_size"] = str(v)
            elif k_str == "subtitle":
                overrides["h3_size"] = str(v)

    # 5. [heading] and [heading.<N>] tables
    heading = data.get("heading") or data.get("headings")
    if isinstance(heading, dict):
        for lvl_key, hcfg in heading.items():
            try:
                lvl = int(lvl_key)
            except (ValueError, TypeError):
                continue
            if isinstance(hcfg, dict):
                for prop, val in hcfg.items():
                    if isinstance(val, (dict, list)):
                        continue
                    prop_str = str(prop).lower()
                    if prop_str in ("size", "font_size"):
                        overrides[f"h{lvl}_size"] = str(val)
                    elif prop_str == "weight":
                        overrides[f"h{lvl}_weight"] = str(val)
                    elif prop_str == "color":
                        overrides[f"h{lvl}_color"] = str(val)
                    elif prop_str in ("family", "font", "font_family"):
                        overrides[f"h{lvl}_family"] = str(val)
                    elif prop_str == "gap":
                        overrides[f"h{lvl}_gap"] = str(val)
                    elif prop_str == "pad_top":
                        overrides[f"h{lvl}_pad_top"] = str(val)
                    elif prop_str == "pad_left":
                        overrides[f"h{lvl}_pad_left"] = str(val)
                    elif prop_str == "pad_right":
                        overrides[f"h{lvl}_pad_right"] = str(val)
                    elif prop_str == "pad_bottom":
                        overrides[f"h{lvl}_pad_bottom"] = str(val)
                    elif prop_str == "band_height":
                        overrides[f"h{lvl}_band_height"] = str(val)
                    elif prop_str in ("line_height", "line_spacing"):
                        overrides[f"h{lvl}_line_height"] = str(val)
                    elif prop_str in ("background", "bg_doc"):
                        overrides[f"h{lvl}_bg_doc"] = str(val)
                    elif prop_str == "bg_color":
                        overrides[f"h{lvl}_bg_color"] = str(val)

    # 6. [background] table
    bg = data.get("background")
    if isinstance(bg, dict):
        for k, v in bg.items():
            if not isinstance(v, (dict, list)):
                overrides["bg_doc"] = str(v)

    # 7. [section] table
    sec = data.get("section")
    if isinstance(sec, dict):
        if "numbered" in sec:
            overrides["numbered"] = "true" if sec["numbered"] else "false"
        if "color" in sec:
            overrides["title_color"] = str(sec["color"])

    return {
        "type": out_type,
        "ratio": out_ratio,
        "overrides": overrides,
    }


def resolve_as_slide(slide: dict, deck_dir: str) -> dict:
    """If slide is `type == 'as'`, resolve its theme TOML settings into the slide."""
    meta = slide.get("meta") or {}
    if (meta.get("type") or "").lower() != "as":
        return slide
    name = (meta.get("params") or "").strip()
    if not name and meta.get("flags"):
        name = meta["flags"][0]
    if not name:
        return slide

    toml_data = load_theme_toml(name, deck_dir)
    if not toml_data:
        return slide

    parsed = parse_theme_toml(toml_data)
    new_meta = dict(meta)
    new_meta["as_theme"] = name
    new_meta["type"] = parsed.get("type") or "content"
    if not new_meta.get("ratio") and parsed.get("ratio"):
        new_meta["ratio"] = parsed["ratio"]

    # Merge overrides: TOML defaults, with slide overrides taking precedence
    merged = dict(parsed.get("overrides") or {})
    merged.update(new_meta.get("overrides") or {})
    new_meta["overrides"] = merged

    slide["meta"] = new_meta
    return slide
