"""Shared-element matching for `:: same` transitions.

Matches content between two consecutive slides by identity, independent of the
rendering backend (expression-lerp today, StateLayout+animationId later) — so this
module is reused across approaches. It answers: which blocks are the *same*, which
*changed*, and which *appear* / *disappear*.

Identity per block kind:
  text     — by its text
  bullets  — per item, by (level, text)
  code     — by (lang, text)
  image    — by path
  graph    — by presence (a graph on both slides is "matched"; if the dot source
             differs it is "changed" → morph)
"""

from __future__ import annotations


def _key(block: dict):
    k = block["kind"]
    if k == "text":
        return ("text", block.get("text", ""))
    if k == "code":
        return ("code", block.get("lang", ""), block.get("text", ""))
    if k == "image":
        return ("image", block.get("path", ""))
    if k == "graph":
        return ("graph",)                     # one graph per slide, matched by presence
    if k == "table":
        return ("table",)
    return (k,)


def _bullet_keys(block: dict):
    return [(it["level"], it["text"]) for it in block["items"]]


def diff_slides(prev_blocks: list[dict], cur_blocks: list[dict]) -> dict:
    """Compare two slides' resolved blocks.

    Returns:
      graph_changed   – bool: a graph is present on both but the dot source differs
      graph_prev/cur  – the graph blocks (or None)
      bullets_new     – set of (level, text) appearing only on the current slide
      bullets_gone    – set of (level, text) only on the previous slide
      blocks_new      – non-bullet blocks appearing only on the current slide (by key)
      blocks_gone     – non-bullet blocks only on the previous slide
    """
    pg = next((b for b in prev_blocks if b["kind"] == "graph"), None)
    cg = next((b for b in cur_blocks if b["kind"] == "graph"), None)

    prev_bullets, cur_bullets = set(), set()
    prev_items = []                      # ordered (index, item) across all prev bullets
    for b in prev_blocks:
        if b["kind"] == "bullets":
            prev_bullets.update(_bullet_keys(b))
            for it in b["items"]:
                prev_items.append((len(prev_items), it))
    for b in cur_blocks:
        if b["kind"] == "bullets":
            cur_bullets.update(_bullet_keys(b))
    # Disappearing bullets, in their previous order (index used to position the collapse).
    gone_ordered = [(idx, it) for idx, it in prev_items
                    if (it["level"], it["text"]) not in cur_bullets]

    prev_keys = {_key(b) for b in prev_blocks if b["kind"] not in ("bullets", "pane_break")}
    cur_keys = {_key(b) for b in cur_blocks if b["kind"] not in ("bullets", "pane_break")}

    return {
        "graph_prev": pg,
        "graph_cur": cg,
        "graph_changed": bool(pg and cg and pg.get("dot") != cg.get("dot")),
        "bullets_new": cur_bullets - prev_bullets,
        "bullets_gone": prev_bullets - cur_bullets,
        "bullets_gone_ordered": gone_ordered,
        "blocks_new": cur_keys - prev_keys,
        "blocks_gone": prev_keys - cur_keys,
        "key": _key,
        "bullet_key": lambda it: (it["level"], it["text"]),
    }
