"""Reordering slides by rewriting the markdown they came from.

The player's deck view can drag a slide to a new position. What actually has to move is the
*source*: the block of `slides.md` between two `---` separators. This module does that move on
the text, and nothing else — no rendering, no rebuild — so it stays testable.

Two facts shape the design.

* A source chunk is not a slide. refract expands one chunk into several rendered slides
  (bullet fragments, scroll pages, staggered embeds), so a deck of 40 slides may come from 25
  chunks. Reordering therefore moves *chunks*: every slide a chunk produced travels together,
  which is the only interpretation that keeps a fragment sequence intact.
* Chunk numbering must agree exactly with the parser's. `parse_markdown` splits on
  ``^\\s*---\\s*$`` with no awareness of fenced code blocks, so a ``---`` inside a fence *does*
  start a new slide. This module splits the same way — deliberately, bugs included — because a
  cleverer split would number chunks differently from the ``src_index`` recorded in deck.json
  and move the wrong block.
"""

from __future__ import annotations

import re

# The line-oriented twin of markdown.SLIDE_SEP. Splitting by lines (rather than with the
# multi-line regex, whose \s can swallow the blank lines around a separator) is what lets the
# text be put back together character for character; test_reorder pins the two to the same
# chunk count.
# \r is allowed so a CRLF file splits into the same chunks the parser sees (SLIDE_SEP's
# \s matches the \r); the separator line is stored verbatim, so the CRLF survives.
SEP_LINE = re.compile(r"^[ \t\r]*---[ \t\r]*$")


def split_chunks(text: str) -> tuple[list[list[str]], list[str]]:
    """Split ``text`` into (chunks, separators).

    A chunk is a list of lines, so that an *empty* chunk (two adjacent separators) is an empty
    list and contributes no line at all — the distinction ``""`` would lose. There is always
    one more chunk than separator, and the separator lines are kept verbatim so odd spacing
    (``  ---  ``) survives a rewrite.
    """
    chunks: list[list[str]] = []
    seps: list[str] = []
    cur: list[str] = []
    for line in text.split("\n"):
        if SEP_LINE.match(line):
            chunks.append(cur)
            seps.append(line)
            cur = []
        else:
            cur.append(line)
    chunks.append(cur)
    return chunks, seps


def join_chunks(chunks: list[list[str]], seps: list[str]) -> str:
    """Inverse of :func:`split_chunks`. Round-trips exactly when nothing was reordered."""
    lines: list[str] = []
    for i, chunk in enumerate(chunks):
        lines.extend(chunk)
        if i < len(seps):
            lines.append(seps[i])
    return "\n".join(lines)


def chunk_texts(text: str) -> list[str]:
    """The chunks as strings — for tests and for anything that wants to look at their content."""
    chunks, _ = split_chunks(text)
    return ["\n".join(c) for c in chunks]


def count_chunks(text: str) -> int:
    return len(split_chunks(text)[0])


def _edit(text: str, rearrange) -> str:
    """Run ``rearrange`` over the file's chunks and put the file back together.

    The file's final newline is set aside first. It belongs to the *file*, not to whichever
    chunk happens to be last: leaving it attached would give the last chunk a trailing blank
    line the moment it moved elsewhere, so moving a slide away and back would not restore the
    file byte for byte.
    """
    trailing = text.endswith("\n")
    body = text[:-1] if trailing else text
    chunks, seps = split_chunks(body)
    out = join_chunks(rearrange(chunks), seps)
    return out + "\n" if trailing else out


def reorder_chunks(text: str, order: list[int]) -> str:
    """Rewrite ``text`` with its chunks in ``order``, a permutation of ``range(count_chunks)``.

    The separators stay where they are (they are interchangeable ``---`` lines); only the
    blocks between them move.
    """
    n = count_chunks(text)
    if sorted(order) != list(range(n)):
        raise ValueError(f"order is not a permutation of 0..{n - 1}: {order}")
    return _edit(text, lambda chunks: [chunks[i] for i in order])


def move_chunk(text: str, src: int, dst: int) -> str:
    """Move the chunk at index ``src`` so that it ends up at index ``dst``.

    ``dst`` is the position in the *result*, the way ``list.insert`` after ``list.pop`` behaves:
    moving 0 to 2 in ``[A, B, C]`` gives ``[B, C, A]``. That is what a drag onto slide ``dst``
    does in the deck view, in both directions.
    """
    n = count_chunks(text)
    for name, i in (("src", src), ("dst", dst)):
        if not 0 <= i < n:
            raise IndexError(f"{name} chunk {i} out of range (deck has {n} chunks)")
    if src == dst:
        return text

    def rearrange(chunks):
        chunks.insert(dst, chunks.pop(src))
        return chunks

    return _edit(text, rearrange)


def move_chunks(text: str, first: int, last: int, dst: int) -> str:
    """Move the block of chunks ``first..last`` (inclusive) so it starts at index ``dst``.

    ``dst`` is a position in the *result*, after the block has been lifted out — so it runs
    from 0 to ``count_chunks - (last - first + 1)``, and ``dst == first`` is the no-op. That
    is the same convention :func:`move_chunk` uses, of which this is the general case.

    This is what moves a whole section, or a whole included sub-deck: several consecutive
    ``---``-separated blocks travelling together, keeping the order they were already in.
    """
    n = count_chunks(text)
    if not 0 <= first <= last < n:
        raise IndexError(f"chunks {first}..{last} out of range (deck has {n} chunks)")
    size = last - first + 1
    if not 0 <= dst <= n - size:
        raise IndexError(f"destination {dst} out of range "
                         f"(a block of {size} can start at 0..{n - size})")
    if dst == first:
        return text

    def rearrange(chunks):
        block = chunks[first:last + 1]
        del chunks[first:last + 1]
        chunks[dst:dst] = block
        return chunks

    return _edit(text, rearrange)


def plan_move(slides: list[dict], frm: int, to: int) -> tuple[str, int, int]:
    """Translate a deck-view drag into a chunk move.

    ``slides`` is deck.json's slide list, whose records carry the ``src`` (markdown file,
    relative to the deck) and ``src_index`` (chunk) that produced them. Returns
    ``(src, from_chunk, to_chunk)``.

    Both slides must come from the same file: an ``:: include`` pulls a sub-deck's slides in
    wholesale, and a slide cannot be dragged out of the deck it is written in. (The include
    itself is a chunk of the parent, so the *sub-deck as a whole* still moves freely.)
    """
    n = len(slides)
    for name, i in (("from", frm), ("to", to)):
        if not 0 <= i < n:
            raise IndexError(f"{name} slide {i} out of range (deck has {n} slides)")
    a, b = slides[frm], slides[to]
    if a.get("src_index") is None or b.get("src_index") is None:
        raise ValueError("deck.json has no source provenance (src_index); "
                         "rebuild the deck so slides can be reordered")
    if a.get("src") != b.get("src"):
        raise ValueError(
            f"slides {frm} and {to} come from different files "
            f"({a.get('src')!r} and {b.get('src')!r}); a slide cannot move between decks")
    return a["src"], int(a["src_index"]), int(b["src_index"])


def move_slide_text(text: str, slides: list[dict], frm: int, to: int) -> str:
    """:func:`plan_move` then :func:`move_chunk`, for the common single-file case."""
    _, a, b = plan_move(slides, frm, to)
    return move_chunk(text, a, b)
