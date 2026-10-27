"""Deck assembly: load slides.md, expand deck includes, resolve content includes."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from urllib.parse import unquote

from .markdown import parse_markdown

IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".gif", ".webp")
VIDEO_EXTS = (".mp4", ".mov", ".m4v", ".webm")
# Source files rendered as highlighted code, mapped to a highlighter language.
CODE_EXTS = {".kt": "kotlin", ".kts": "kotlin", ".java": "java", ".py": "python",
             ".ts": "typescript", ".js": "javascript", ".json": "json"}
INCLUDE_PROBE = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".rc", ".json",
                 ".mp4", ".mov", ".m4v", ".kt", ".java", ".py", ".ts")


def load_deck(deck_dir: str, visited: set[str], root_dir: str | None = None) -> list[dict]:
    """Return a flat list of slides, expanding ``:: include : <deck>`` references.

    ``root_dir`` is the outermost deck (the one being built); every slide records it as
    ``root_dir`` so a sub-deck's lookups — ``:: as:`` templates, ``bg_doc`` plates,
    ``theme/include`` assets — can fall back to the main deck's folders."""
    deck_dir = os.path.abspath(deck_dir)
    root_dir = os.path.abspath(root_dir) if root_dir else deck_dir
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
                sub_slides = load_deck(sub_dir, visited | {os.path.abspath(sub_dir)}, root_dir)
                # Where the include *itself* is written. A sub-deck's slides live in their own
                # slides.md, so reordering one of them rewrites that file — but moving the
                # whole sub-deck means moving this one ``:: include`` line in *this* file, and
                # nothing else records where it was. Prepended, so ``src_via`` reads outermost
                # first and a nested include keeps its whole chain.
                for sub in sub_slides:
                    sub.setdefault("src_via", []).insert(
                        0, {"src": md_path, "src_index": slide.get("src_index")})
                # ``duration=`` on the include plans the whole sub-deck as one part of the talk
                # (``:: include : capabilities duration=8m``), as ``:: section duration=`` plans
                # a section: it rides on the first slide the include pulls in. If that slide is
                # a section already, it simply becomes that section's duration.
                inc_dur = (meta.get("overrides") or {}).get("duration")
                if inc_dur is not None and sub_slides:
                    from .meta import parse_duration
                    seconds = parse_duration(inc_dur)
                    first = sub_slides[0]
                    fm = first.get("meta") or {}
                    if seconds <= 0:
                        print(f"note: `:: include : {name} duration={inc_dur}` is not a duration "
                              f"(12m, 90s, 1h30m, or minutes)", file=sys.stderr)
                    elif fm.get("type", "").lower() == "section" and "duration" not in (fm.get("overrides") or {}):
                        fm.setdefault("overrides", {})["duration"] = inc_dur
                        first["meta"] = fm
                    else:
                        first["plan_part"] = {"duration": seconds, "title": first.get("title") or name}
                    timed = [s for s in sub_slides[1:] if (s.get("meta") or {}).get("type", "").lower() == "section"]
                    if timed:
                        print(f"note: `:: include : {name}` has a duration and sections of its own — "
                              f"each section starts a new part of the plan, so the include's time "
                              f"covers only the slides before the first of them", file=sys.stderr)
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
                    "root_dir": root_dir,
                    "src_file": md_path,
                    "src_index": slide.get("src_index"),
                })
        else:
            slide["base_dir"] = deck_dir
            slide["root_dir"] = root_dir
            slide["src_file"] = md_path
            from .as_theme import resolve_as_slide
            resolve_as_slide(slide, deck_dir, [root_dir])
            result.append(slide)
    return result


def resolve_include(name: str, includes_dir: str, extra_dirs: list[str] | None = None) -> dict:
    """Resolve an ``<name>`` include to a concrete block with an absolute path.

    ``<camera>`` is the one include with no file behind it: the player's camera feed, drawn
    live into the box at playback (``<camera:FaceTime>`` names the device by a substring of
    its name, or by index). It frames, crops, clips and captions like a video."""
    low = name.strip().lower()
    if low == "camera" or low.startswith("camera:"):
        return {"kind": "camera", "device": name.strip().partition(":")[2].strip(), "name": name}
    _, ext = os.path.splitext(name)
    candidates = [name] if ext else [name + e for e in INCLUDE_PROBE]
    search_dirs = [includes_dir] + [d for d in (extra_dirs or []) if d and os.path.isdir(d)]
    for sdir in search_dirs:
        for cand in candidates:
            path = os.path.join(sdir, cand)
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


def zoom_crop(zoom: float, focus=(0.5, 0.5), within: list | None = None) -> list | None:
    """The ``crop`` rectangle a ``zoom=N`` means: the middle 1/N of the frame (by side), centred
    on ``focus`` (fractions of the frame, default the centre) and kept inside it. ``within``
    is a crop already asked for: the zoom then applies inside that rectangle."""
    try:
        z = float(zoom)
    except (TypeError, ValueError):
        return None
    if z <= 1.0:
        return within
    half = 0.5 / z
    fx, fy = focus if focus else (0.5, 0.5)
    cx = min(max(float(fx), half), 1.0 - half)
    cy = min(max(float(fy), half), 1.0 - half)
    rect = [cx - half, cy - half, cx + half, cy + half]
    if within:
        l, t, r, b = within
        rect = [l + rect[0] * (r - l), t + rect[1] * (b - t), l + rect[2] * (r - l), t + rect[3] * (b - t)]
    return [round(v, 4) for v in rect]


def parse_focus(value) -> tuple | None:
    """``focus=x,y`` as two fractions 0–1, or None."""
    if not value:
        return None
    try:
        parts = [float(x) for x in str(value).replace(" ", "").split(",")]
    except ValueError:
        return None
    if len(parts) != 2:
        return None
    return (min(max(parts[0], 0.0), 1.0), min(max(parts[1], 0.0), 1.0))


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


def parse_ratio(value) -> float | None:
    """Parse an embed aspect ratio into a ``width / height`` float, or None. Accepts ``W:H``
    (e.g. ``16:9``, ``1:1``) or a bare decimal (``1.5`` = 3:2). Non-positive / malformed
    values are ignored."""
    if not value:
        return None
    s = str(value).strip()
    try:
        w, h = ((float(x) for x in s.split(":", 1)) if ":" in s else (float(s), 1.0))
    except ValueError:
        return None
    if w <= 0 or h <= 0:
        return None
    return round(w / h, 4)


_FRAMEABLE = ("video", "rc_include", "json_include", "camera")
_ZOOMABLE = ("video", "image", "rc_include", "json_include")
_CAPTIONABLE = _FRAMEABLE + ("image",)


def parse_clip_time(raw) -> float | None:
    """A time in a clip: seconds (``12``, ``12.5``) or a timestamp (``1:23``, ``1:02:03.5``).
    None when absent or unreadable."""
    if raw is None or raw is True:
        return None
    try:
        parts = [float(p) for p in str(raw).strip().split(":")]
    except ValueError:
        return None
    t = 0.0
    for p in parts:
        t = t * 60.0 + p
    return max(0.0, t)


def parse_zooms(raw) -> list[tuple] | None:
    """Zoom keyframes ``T@x,y,z; T@x,y,z`` — T a clip time (seconds or ``m:ss``), x,y the
    centre as fractions of the (cropped) frame, z the zoom factor (1 = whole frame). Returns
    [(t, x, y, z)] sorted by time, or None when absent or nothing reads."""
    if not raw or raw is True:
        return None
    keys = []
    for part in str(raw).replace("\n", ";").split(";"):
        if "@" not in part:
            continue
        t_raw, _, rest = part.strip().partition("@")
        t_raw = t_raw.strip()
        # A negative time is a key the slide opens already settled on (chains use one).
        neg = t_raw.startswith("-")
        t = parse_clip_time(t_raw.lstrip("-")) if t_raw.lstrip("-") else 0.0
        if t is not None and neg:
            t = -t
        try:
            vals = [float(v) for v in rest.replace(" ", "").split(",")]
        except ValueError:
            continue
        if t is None or len(vals) < 2:
            continue
        x, y = vals[0], vals[1]
        z = max(1.0, vals[2]) if len(vals) > 2 else 1.0
        keys.append((t, min(max(x, 0.0), 1.0), min(max(y, 0.0), 1.0), z))
    return sorted(keys, key=lambda k: k[0]) or None     # by time; ties keep the written order


def _apply_include_opts(block: dict, opts: dict) -> dict:
    """Apply per-include options (from ``<name | key=val …>``) to a resolved media block: a
    source ``crop``, a ``fit`` override, and a ``title`` caption drawn below the embed. Crop
    and fit apply to video and rc/json embeds (for a spliced json/rc, a crop/fit reframes it
    as a nested document); the caption applies to those plus images."""
    # ``zoom=T@x,y,z`` is one zoom keyframe (see ``zooms``), not the static zoom.
    if block["kind"] in _ZOOMABLE and "@" in str(opts.get("zoom") or ""):
        opts = {**opts, "zooms": opts["zoom"]}
        opts.pop("zoom")
    crop = parse_crop(opts.get("crop"))
    if crop and block["kind"] in _FRAMEABLE:
        block["crop"] = crop
    if opts.get("fit") and block["kind"] in _FRAMEABLE:
        block["fit"] = opts["fit"].lower()
    # ``ratio=W:H`` frames the embed in a centred box of that aspect ratio (rendered live as a
    # custom component) rather than filling the whole content area.
    ratio = parse_ratio(opts.get("ratio"))
    if ratio and block["kind"] in _FRAMEABLE:
        block["ratio"] = ratio
    # A video: ``start=`` begins playback there (and loops back to it); ``still=`` shows that one
    # frame, frozen. ``cue`` (see refract.py ``expand_video_cue``) puts a still slide in front.
    if block["kind"] == "video":
        for k in ("start", "still", "until"):
            t = parse_clip_time(opts.get(k))
            if t is not None:
                block[k] = t
        # ``once`` (or ``loop=0``) plays the clip through and holds its last frame; it loops by default.
        loop = opts.get("loop")
        if opts.get("once") or (isinstance(loop, str) and loop.lower() in ("0", "false", "off", "no", "once")):
            block["loop"] = False
    # ``zooms=T@x,y,z; …`` — keyframed zoom, eased from one view to the next: on the clip's clock
    # for a video, on the slide's (seconds since it opened) for an image or a document.
    if block["kind"] in _ZOOMABLE:
        zooms = parse_zooms(opts.get("zooms"))
        if zooms:
            block["zooms"] = zooms
    # An image's static ``zoom=N`` (``focus=x,y``): the same view, already settled as the slide opens.
    if block["kind"] == "image" and opts.get("zoom") and not block.get("zooms"):
        try:
            z = max(1.0, float(opts["zoom"]))
        except (TypeError, ValueError):
            z = 0.0
        if z:
            fx, fy = parse_focus(opts.get("focus")) or (0.5, 0.5)
            block["zooms"] = [(-1.0, fx, fy, z)]
    # ``frame=<name>`` puts the embed in a device frame the theme defines (``[frames.<name>]``).
    if opts.get("frame") and block["kind"] in _CAPTIONABLE and block["kind"] != "json_include":
        if str(opts["frame"]).lower() not in ("none", "off", "no", "0"):
            block["frame"] = str(opts["frame"]).lower()
    if opts.get("title") and block["kind"] in _CAPTIONABLE:
        block["caption"] = opts["title"]
    # ``clip=circle`` | ``clip=<px>`` | ``clip=none`` rounds (or fully rounds, or squares) the
    # embed's box, over the theme's image corner radius.
    if opts.get("clip") and block["kind"] in _FRAMEABLE:
        block["clip"] = str(opts["clip"]).lower()
    # ``width=`` / ``height=`` size the box outright (px), as they do an image, instead of
    # filling what is left; one of them with ``ratio=`` gives the other. ``align=`` places a
    # sized box in its row (start by default).
    if block["kind"] in _FRAMEABLE:
        for k in ("width", "height"):
            if opts.get(k):
                try:
                    block[k] = float(opts[k])
                except (TypeError, ValueError):
                    pass
        if opts.get("align"):
            block["align"] = str(opts["align"]).lower()
    # ``zoom=N`` shows the middle 1/N of the frame — a face, closer — centred on ``focus=x,y``
    # when given; it composes with a ``crop`` by zooming inside it.
    if opts.get("zoom") and block["kind"] in _FRAMEABLE:
        zoomed = zoom_crop(opts["zoom"], parse_focus(opts.get("focus")), block.get("crop"))
        if zoomed:
            block["crop"] = zoomed
            block["zoom"] = float(opts["zoom"])
    # The camera: ``mirror`` flips it like a mirror (what a speaker expects to see of
    # themselves), ``device=`` picks one when the machine has several.
    if block["kind"] == "camera":
        if opts.get("mirror") and str(opts["mirror"]).lower() not in ("0", "false", "off", "no"):
            block["mirror"] = True
        if opts.get("device"):
            block["device"] = str(opts["device"])
    # Slide-driven embedded documents: ``persist`` keeps the document alive across slides on
    # its own clock; ``step=N`` hands it this slide's number and ``stepid``/``timeid`` name
    # the document's float ids that receive the step and the host's slide time. Or, for a
    # document that knows nothing about slides, ``from``/``to`` (seconds of its own timeline) and
    # ``speed``: the slide plays that window and holds at ``to``. Passed through to the
    # embedded-document host untouched.
    if block["kind"] == "rc_include":
        for k in ("persist", "step", "stepid", "timeid", "prevstepid", "prevtimeid", "from", "to", "speed"):
            if k in opts:
                block[k] = "1" if opts[k] is True else str(opts[k])
        # ``events="1@click(588,542) wait(2) click(312,542) …"`` — a touch script the host plays
        # on the document (see render_rc_embed); it loops unless ``once``.
        if opts.get("events"):
            block["events"] = " ".join(str(opts["events"]).split())
            if opts.get("once") or str(opts.get("loop", "")).lower() in ("0", "false", "off", "no", "once"):
                block["once"] = "1"
    # Stagger reveal state (set by refract's expand_embed_stagger on generated step slides):
    # "shown" | "fade" | "hidden" — the renderer alpha-gates the embed accordingly.
    if opts.get("_reveal") and block["kind"] in _CAPTIONABLE:
        block["_reveal"] = opts["_reveal"]
    block["opts"] = opts
    return block


def resolve_page_url(url: str, deck_dir: str, extra_dirs: list[str] | None = None) -> str:
    """A ``file:`` URL pointing at a page in the deck, made absolute.

    A demo that travels with the deck should be named the way everything else in a deck is —
    by where it sits — so ``<file://demos/app/index.html>`` is the deck's own
    ``demos/app/index.html``. Anything already absolute (``file:///…``), and anything that is
    not a ``file:`` URL at all, is left exactly as it was written.

    A relative page is looked for beside ``slides.md`` first, then in ``includes/``, then
    wherever else includes come from — a sub-deck's page can live in the main deck. When it
    is nowhere, the deck's own path is what comes back, so the player names a real file when
    it says the page is missing rather than something that was never looked for."""
    if not url or not url.lower().startswith("file:"):
        return url
    rest = url[len("file:"):]
    if rest.startswith("///"):
        return url                              # file:///abs/path
    if rest.startswith("//"):
        rest = rest[2:]
        host, _, _after = rest.partition("/")
        if host.lower() == "localhost":         # file://localhost/abs/path: already absolute
            return url
    # What is left is a relative path: file://demos/x.html, file:demos/x.html, file://./x.html
    rest = rest.lstrip("/")
    if not rest:
        return url
    path, sep, tail = rest.partition("#")       # a fragment belongs to the URL, not the path
    query, qsep, after_query = "", "", ""
    if "?" in path:
        path, qsep, query = path.partition("?")
    path = unquote(path)
    candidates = [os.path.join(deck_dir, path), os.path.join(deck_dir, "includes", path)]
    for extra in extra_dirs or []:
        candidates.append(os.path.join(extra, path))
        # includes/ dirs are the usual `extra`; their deck is worth a look too.
        candidates.append(os.path.join(os.path.dirname(extra), path))
    found = next((c for c in candidates if os.path.exists(c)), candidates[0])
    return Path(os.path.abspath(found)).as_uri() + (qsep + query if qsep else "") + (sep + tail if sep else "")


def _resolve_block_list(blocks: list[dict], includes_dir: str,
                       extra_dirs: list[str] | None = None,
                       deck_dir: str | None = None) -> list[dict]:
    """Replace ``include`` blocks with resolved image/json/rc/missing blocks, and point a
    relative ``file:`` page at the deck it lives in (others pass through). Idempotent —
    re-resolving already-resolved blocks is a no-op."""
    if deck_dir is None:
        deck_dir = os.path.dirname(includes_dir) or "."
    resolved = []
    for block in blocks:
        if block["kind"] == "include":
            r = resolve_include(block["name"], includes_dir, extra_dirs)
            if block.get("opts"):
                r = _apply_include_opts(r, block["opts"])
            resolved.append(r)
        elif block["kind"] == "weblink":
            resolved.append({**block, "url": resolve_page_url(block["url"], deck_dir, extra_dirs)})
        else:
            resolved.append(block)
    return resolved


def resolve_blocks(slide: dict) -> list[dict]:
    """Resolve the slide's includes. Also resolves each ``===`` layout section's blocks in
    place, so a sectioned slide's sections render with real media blocks."""
    deck_dir = slide.get("base_dir", ".")
    includes_dir = os.path.join(deck_dir, "includes")
    root_dir = slide.get("root_dir")
    is_sub = bool(root_dir) and os.path.abspath(root_dir) != os.path.abspath(deck_dir)
    # Search order for ``<name>``: the deck's own includes/, then — for a slide that came in
    # through ``:: include`` — the root deck's includes/, then theme assets, own before root.
    # So a sub-deck can lean on the main deck's pictures and documents, and still shadow any
    # of them with a file of the same name in its own includes/.
    extra_dirs = [os.path.join(root_dir, "includes")] if is_sub else []
    for base in ([deck_dir, root_dir] if is_sub else [deck_dir]):
        extra_dirs += [
            os.path.join(base, "theme", "include"),
            os.path.join(base, "theme", "includes"),
            os.path.join(base, "themes", "include"),
            os.path.join(base, "themes", "includes"),
        ]
    for sec in slide.get("sections", []):
        sec["blocks"] = _resolve_block_list(sec["blocks"], includes_dir, extra_dirs, deck_dir)
    return _resolve_block_list(slide["blocks"], includes_dir, extra_dirs, deck_dir)
