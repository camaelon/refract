"""Deck assembly: load slides.md, expand deck includes, resolve content includes."""

from __future__ import annotations

import os

from .markdown import parse_markdown

IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".gif", ".webp")
VIDEO_EXTS = (".mp4", ".mov", ".m4v", ".webm")
# Source files rendered as highlighted code, mapped to a highlighter language.
CODE_EXTS = {".kt": "kotlin", ".kts": "kotlin", ".java": "java", ".py": "python",
             ".ts": "typescript", ".js": "javascript", ".json": "json"}
INCLUDE_PROBE = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".rc", ".json",
                 ".mp4", ".mov", ".m4v", ".kt", ".java", ".py", ".ts")


def load_deck(deck_dir: str, visited: set[str]) -> list[dict]:
    """Return a flat list of slides, expanding ``:: include : <deck>`` references."""
    deck_dir = os.path.abspath(deck_dir)
    md_path = os.path.join(deck_dir, "slides.md")
    if not os.path.isfile(md_path):
        raise FileNotFoundError(f"no slides.md in {deck_dir}")
    with open(md_path) as f:
        raw_slides = parse_markdown(f.read())

    result = []
    for slide in raw_slides:
        meta = slide.get("meta") or {}
        if meta.get("type", "").lower() == "include":
            name = meta.get("params", "").strip()
            sub_dir = os.path.join(deck_dir, "includes", name)
            sub_md = os.path.join(sub_dir, "slides.md")
            if name and os.path.isfile(sub_md) and os.path.abspath(sub_dir) not in visited:
                sub_slides = load_deck(sub_dir, visited | {os.path.abspath(sub_dir)})
                # An ``@author`` on the include attributes every slide it pulls in,
                # unless that slide names its own author.
                inc_author = meta.get("author")
                if inc_author:
                    for s in sub_slides:
                        sm = s.get("meta") or {}
                        if not sm.get("author"):
                            sm["author"] = inc_author
                            s["meta"] = sm
                result.extend(sub_slides)
            else:
                result.append({
                    "meta": {"type": "section", "params": ""},
                    "title": None,
                    "blocks": [{"kind": "text", "text": f"<section {name} will go there>"}],
                    "base_dir": deck_dir,
                })
        else:
            slide["base_dir"] = deck_dir
            result.append(slide)
    return result


def resolve_include(name: str, includes_dir: str) -> dict:
    """Resolve an ``<name>`` include to a concrete block with an absolute path."""
    _, ext = os.path.splitext(name)
    candidates = [name] if ext else [name + e for e in INCLUDE_PROBE]
    for cand in candidates:
        path = os.path.join(includes_dir, cand)
        if os.path.isfile(path):
            ext = os.path.splitext(path)[1].lower()
            if ext in IMAGE_EXTS:
                return {"kind": "image", "path": os.path.abspath(path)}
            if ext in VIDEO_EXTS:
                return {"kind": "video", "path": os.path.abspath(path), "name": name}
            if ext == ".rc":
                # Prefer the sibling .json when present (spliced into the JSON tree as a flat
                # document); otherwise the binary .rc is embedded *live* as a nested document
                # via the rc-document custom-component host — see render_rc_embed.
                sib = os.path.splitext(path)[0] + ".json"
                return {"kind": "rc_include", "path": os.path.abspath(path), "name": name,
                        "json": os.path.abspath(sib) if os.path.isfile(sib) else None}
            if ext == ".json":
                return {"kind": "json_include", "path": os.path.abspath(path)}
            if ext in CODE_EXTS:
                with open(path, errors="replace") as f:
                    return {"kind": "code", "lang": CODE_EXTS[ext], "text": f.read().rstrip("\n")}
    return {"kind": "missing", "name": name}


def parse_crop(value) -> list | None:
    """Parse a ``crop=l,t,r,b`` value into four source fractions (0–1), or None. Ignored
    unless it's four numbers forming a positive-area rectangle inside the unit square."""
    if not value:
        return None
    try:
        parts = [float(x) for x in str(value).replace(" ", "").split(",")]
    except ValueError:
        return None
    if len(parts) != 4:
        return None
    l, t, r, b = (max(0.0, min(1.0, v)) for v in parts)
    if r <= l or b <= t:
        return None
    return [round(l, 4), round(t, 4), round(r, 4), round(b, 4)]


_FRAMEABLE = ("video", "rc_include", "json_include")
_CAPTIONABLE = _FRAMEABLE + ("image",)


def _apply_include_opts(block: dict, opts: dict) -> dict:
    """Apply per-include options (from ``<name | key=val …>``) to a resolved media block: a
    source ``crop``, a ``fit`` override, and a ``title`` caption drawn below the embed. Crop
    and fit apply to video and rc/json embeds (for a spliced json/rc, a crop/fit reframes it
    as a nested document); the caption applies to those plus images."""
    crop = parse_crop(opts.get("crop"))
    if crop and block["kind"] in _FRAMEABLE:
        block["crop"] = crop
    if opts.get("fit") and block["kind"] in _FRAMEABLE:
        block["fit"] = opts["fit"].lower()
    if opts.get("title") and block["kind"] in _CAPTIONABLE:
        block["caption"] = opts["title"]
    return block


def resolve_blocks(slide: dict) -> list[dict]:
    """Replace ``include`` blocks with resolved image/json/rc/missing blocks."""
    includes_dir = os.path.join(slide["base_dir"], "includes")
    resolved = []
    for block in slide["blocks"]:
        if block["kind"] == "include":
            r = resolve_include(block["name"], includes_dir)
            if block.get("opts"):
                r = _apply_include_opts(r, block["opts"])
            resolved.append(r)
        else:
            resolved.append(block)
    return resolved
