"""Reordering a deck by rewriting the markdown it was written in.

The player's deck view can drag a slide, a section or an included sub-deck to a new position.
What actually moves is the source: the `---`-separated blocks of a slides.md. The blocks
themselves — splitting, rejoining, reading and replacing one — are :mod:`refractkit.chunks`;
this is the moving, and nothing else, so it stays testable without a renderer in sight.

What moves is a block, not a slide. refract expands one block into several rendered slides
(bullet fragments, scroll pages, staggered embeds), and those only make sense in sequence, so
reordering moves whole blocks and every slide one produced travels with it.
"""

from __future__ import annotations

# Re-exported: the block primitives are this module's alphabet, and callers that reorder
# usually also want to look at what they are reordering.
from .chunks import (SEP_LINE, chunk_texts, count_chunks, join_chunks, read_chunk,
                     replace_chunk, split_chunks, _edit)

__all__ = ["SEP_LINE", "chunk_texts", "count_chunks", "join_chunks", "read_chunk",
           "replace_chunk", "split_chunks", "reorder_chunks", "move_chunk", "move_chunks",
           "plan_move", "move_slide_text"]


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
