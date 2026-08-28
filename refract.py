#!/usr/bin/env python3
"""refract — turn simple markdown into RemoteCompose slides.

Pipeline:  markdown -> component JSON (androidx format) -> [json2rc] -> .rc

v1 grammar (deliberately tiny):
  * ``---`` on its own line separates slides; each slide becomes one ``.rc`` file.
  * An optional ``:: <type> : <parameters>`` line right after the separator (and
    before the title) sets the slide metadata. ``<type>`` is one of ``title``,
    ``section`` or ``content`` (default ``content``).
  * The first ``# heading`` in a slide is the slide title.
  * Every other non-blank line is content; blank lines mark paragraph breaks.
    All content is rendered as a single multi-line Text.

The JSON we emit uses RemoteCompose *components* (Column + Text), so layout is
done by the RemoteCompose engine rather than by pixel math here.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys

SLIDE_SEP = re.compile(r"(?m)^\s*---\s*$")
TITLE_RE = re.compile(r"^#\s+(.*)$")


def parse_meta(spec: str) -> dict:
    """Parse a ``::`` metadata line of the form ``<type of slide> : <parameters>``."""
    kind, _, params = spec.partition(":")
    return {"type": kind.strip(), "params": params.strip()}


def parse_slides(md: str) -> list[dict]:
    """Split markdown into a list of {meta, title, content} slide dicts."""
    slides = []
    for chunk in SLIDE_SEP.split(md):
        meta = None
        title = None
        lines: list[str] = []
        for raw in chunk.strip("\n").splitlines():
            line = raw.strip()
            if not line:
                if lines and lines[-1] != "":
                    lines.append("")  # preserve paragraph break
                continue
            # Metadata: a leading ``::`` line, after the separator and before
            # the title. Anything after ``::`` is "<type> : <parameters>".
            if title is None and not lines and line.startswith("::"):
                if meta is None:
                    meta = parse_meta(line[2:])
                continue
            m = TITLE_RE.match(line)
            if m and title is None:
                title = m.group(1).strip()
            else:
                lines.append(line)
        while lines and lines[-1] == "":
            lines.pop()
        if meta is None and title is None and not lines:
            continue  # skip empty chunk (e.g. leading separator)
        slides.append({"meta": meta, "title": title, "content": "\n".join(lines)})
    return slides


TITLE_COLOR = "#FFFFFFFF"
BODY_COLOR = "#FFE6EEF6"

# Basic slide types, selected via the ``:: <type> : ...`` metadata line.
#   title   — cover slide: big title centered on the slide
#   section — section divider: title centered
#   content — default: title at top, content below (left-aligned)
SLIDE_TYPES = {
    "title":   {"h_align": "center", "v_align": "center", "title_size": 120.0, "body_size": 44.0},
    "section": {"h_align": "center", "v_align": "center", "title_size": 96.0,  "body_size": 36.0},
    "content": {"h_align": "start",  "v_align": "top",    "title_size": 72.0,  "body_size": 36.0},
}
DEFAULT_TYPE = "content"


def slide_type(slide: dict) -> str:
    meta = slide.get("meta") or {}
    kind = (meta.get("type") or DEFAULT_TYPE).lower()
    return kind if kind in SLIDE_TYPES else DEFAULT_TYPE


def build_doc(slide: dict, width: int, height: int, index: int) -> dict:
    """Build a RemoteCompose component-JSON document for one slide."""
    spec = SLIDE_TYPES[slide_type(slide)]
    children = []
    if slide["title"]:
        children.append(
            {"type": "text", "value": slide["title"],
             "fontSize": spec["title_size"], "color": TITLE_COLOR}
        )
    if slide["content"]:
        children.append(
            {"type": "text", "value": slide["content"],
             "fontSize": spec["body_size"], "color": BODY_COLOR}
        )
    doc = {
        "header": {
            "width": width,
            "height": height,
            "contentDescription": slide["title"] or f"Slide {index + 1}",
        },
        "root": {
            "type": "column",
            "horizontalAlignment": spec["h_align"],
            "verticalAlignment": spec["v_align"],
            "modifiers": ["fillMaxSize", {"padding": 80.0}],
            "children": children,
        },
    }
    if slide.get("meta"):
        # Unknown top-level keys are ignored by the parser; keep meta for reference.
        doc["_meta"] = slide["meta"]
    return doc


def slug(text: str | None, index: int) -> str:
    base = re.sub(r"[^a-z0-9]+", "_", (text or "slide").lower()).strip("_")
    return f"{index + 1:02d}_{base or 'slide'}"


def find_json2rc(repo_root: str) -> str | None:
    candidate = os.path.join(
        repo_root, "json2rc", "build", "install", "json2rc", "bin", "json2rc"
    )
    return candidate if os.path.isfile(candidate) else None


def main() -> int:
    ap = argparse.ArgumentParser(description="markdown -> RemoteCompose .rc slides")
    ap.add_argument("input", help="input markdown file")
    ap.add_argument("-o", "--out", default="out", help="output directory (default: out)")
    ap.add_argument("--width", type=int, default=1600, help="slide width (default 1600)")
    ap.add_argument("--height", type=int, default=900, help="slide height (default 900)")
    ap.add_argument("--json-only", action="store_true",
                    help="emit JSON only; do not run json2rc")
    ap.add_argument("--json2rc", default=None,
                    help="path to the json2rc launcher (default: auto-detect)")
    args = ap.parse_args()

    with open(args.input) as f:
        slides = parse_slides(f.read())
    if not slides:
        print("no slides found", file=sys.stderr)
        return 1

    os.makedirs(args.out, exist_ok=True)
    repo_root = os.path.dirname(os.path.abspath(__file__))

    pairs = []  # (json_path, rc_path)
    for i, slide in enumerate(slides):
        name = slug(slide["title"], i)
        doc = build_doc(slide, args.width, args.height, i)
        json_path = os.path.join(args.out, name + ".json")
        rc_path = os.path.join(args.out, name + ".rc")
        with open(json_path, "w") as f:
            json.dump(doc, f, indent=2)
        pairs.append((json_path, rc_path))
        print(f"wrote {json_path}  [{slide_type(slide)}]")

    if args.json_only:
        return 0

    json2rc = args.json2rc or find_json2rc(repo_root)
    if not json2rc:
        print(
            "json2rc launcher not found. Build it first:\n"
            "  (cd json2rc && ./gradlew installDist)\n"
            "or pass --json-only to stop at JSON.",
            file=sys.stderr,
        )
        return 2

    cmd = [json2rc]
    for json_path, rc_path in pairs:
        cmd += [json_path, rc_path]
    result = subprocess.run(cmd)
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
