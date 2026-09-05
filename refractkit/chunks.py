"""The `---`-separated blocks of a slides.md, and the edits that treat them as units.

A refract deck is one markdown file split on `---`. Everything that changes a deck without
retyping it — moving a slide, moving a section, editing one slide's source — is an edit to
that list of blocks, so the splitting and rejoining live here and the operations build on top.

Two facts shape it.

* Blocks are not slides. refract expands one block into several rendered slides (bullet
  fragments, scroll pages, staggered embeds), so a deck of 40 slides may come from 25 blocks.
  Anything working per slide has to map back through `src_index` first.
* Block numbering must agree exactly with the parser's. `parse_markdown` splits on
  ``^\\s*---\\s*$`` with no awareness of fenced code blocks, so a ``---`` inside a fence *does*
  start a new slide. This module splits the same way — deliberately, bugs included — because a
  cleverer split would number blocks differently from the ``src_index`` recorded in deck.json
  and edit the wrong one.
"""

from __future__ import annotations

import re

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


def read_chunk(text: str, index: int) -> str:
    """The source of one block, as the author wrote it.

    Leading and trailing blank lines are trimmed: they are the spacing *around* a block rather
    than part of it, and an editor that opened with two blank lines above the title would
    accumulate them every time the block was saved.
    """
    chunks = chunk_texts(text)
    if not 0 <= index < len(chunks):
        raise IndexError(f"block {index} out of range (deck has {len(chunks)} blocks)")
    return chunks[index].strip("\n")


def replace_chunk(text: str, index: int, replacement: str) -> str:
    """Put ``replacement`` in place of block ``index``, keeping the file's spacing around it.

    The blank lines that separated the block from its ``---`` markers are put back, so a deck
    written with a blank line either side of every separator stays that way and the diff for
    an edit is the edit.
    """
    n = count_chunks(text)
    if not 0 <= index < n:
        raise IndexError(f"block {index} out of range (deck has {n} blocks)")

    trailing = text.endswith("\n")
    body = text[:-1] if trailing else text
    chunks, seps = split_chunks(body)

    old = chunks[index]
    lead = [line for line in _leading_blanks(old)]
    tail = [line for line in _trailing_blanks(old)]
    new_lines = replacement.strip("\n").split("\n") if replacement.strip("\n") else []
    chunks[index] = lead + new_lines + tail

    out = join_chunks(chunks, seps)
    return out + "\n" if trailing else out


def _padding(chunks: list[list[str]]) -> list[str]:
    """The blank line a deck puts either side of its ``---``, or nothing if it does not.

    Taken from the file rather than chosen, so a new slide is spaced the way its neighbours
    are and adding one shows up in the diff as a slide rather than as a reformat.
    """
    for chunk in chunks:
        if chunk and not chunk[0].strip():
            return [chunk[0]]
    return []


def _trimEnds(chunks: list[list[str]]) -> None:
    """Drop blank lines from the very top and bottom of the file.

    A block's padding is the gap around the ``---`` next to it, so the first block has none
    above it and the last none below. Adding or removing a block at either end leaves padding
    for a separator that is no longer there.
    """
    if not chunks:
        return
    while chunks[0] and not chunks[0][0].strip():
        chunks[0].pop(0)
    while chunks[-1] and not chunks[-1][-1].strip():
        chunks[-1].pop()


def insert_chunk(text: str, index: int, source: str = "") -> str:
    """Add a block so that it becomes block ``index``, pushing the rest down.

    The separator and the blank lines around it follow the deck's own style, so a file
    written with a blank line either side of every ``---`` stays that way.
    """
    n = count_chunks(text)
    if not 0 <= index <= n:
        raise IndexError(f"block {index} out of range (deck has {n} blocks)")

    trailing = text.endswith("\n")
    body = text[:-1] if trailing else text
    chunks, seps = split_chunks(body)
    pad = _padding(chunks)

    body_lines = source.strip("\n").split("\n") if source.strip("\n") else []
    lines = pad + body_lines + pad
    # The block at an end of the file has no padding on that side — there is no separator
    # there to pad against — so the neighbour that is about to gain one needs it back.
    if index == len(chunks) and pad and chunks and chunks[-1] and chunks[-1][-1].strip():
        chunks[-1] = chunks[-1] + pad
    if index == 0 and pad and chunks and chunks[0] and chunks[0][0].strip():
        chunks[0] = pad + chunks[0]
    chunks.insert(index, lines)
    # A block needs a separator to be a block: one more than there were, in the gap the new
    # one opened. Copied from a neighbour so `  ---  ` stays `  ---  `.
    seps.insert(min(index, len(seps)), seps[min(index, len(seps) - 1)] if seps else "---")
    _trimEnds(chunks)

    out = join_chunks(chunks, seps)
    return out + "\n" if trailing else out


def delete_chunk(text: str, index: int) -> str:
    """Remove block ``index``, and the separator that held it.

    Refuses to empty the file: a deck of no slides is not a deck, and the markdown would have
    nothing left to put a slide back into.
    """
    n = count_chunks(text)
    if not 0 <= index < n:
        raise IndexError(f"block {index} out of range (deck has {n} blocks)")
    if n == 1:
        raise ValueError("a deck has to keep at least one slide")

    trailing = text.endswith("\n")
    body = text[:-1] if trailing else text
    chunks, seps = split_chunks(body)
    del chunks[index]
    del seps[min(index, len(seps) - 1)]
    _trimEnds(chunks)

    out = join_chunks(chunks, seps)
    return out + "\n" if trailing else out


def _leading_blanks(lines: list[str]) -> list[str]:
    out = []
    for line in lines:
        if line.strip():
            break
        out.append(line)
    return out


def _trailing_blanks(lines: list[str]) -> list[str]:
    out = []
    for line in reversed(lines):
        if line.strip():
            break
        out.insert(0, line)
    # A block that is entirely blank would otherwise have its lines counted twice.
    return out if any(line.strip() for line in lines) else []
