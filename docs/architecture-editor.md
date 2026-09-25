# The slide editor, from the inside

The editor is the largest single thing in the player — a text editor, a completion menu, a
preview pane and a save path that rewrites a deck and rebuilds it. This page is how it fits
together and why it is cut where it is. It is for changing the editor, not for using it; for
that, read [the illustrated guide](refractplayer.md).

## The shape of it

Five units, and only the last one knows there is a window:

```
        TextBuffer          lines, caret, selection, undo — no Skia, no GLFW, no refract
             │
      ViewGeometry          rows: wrapping a line to a width, and where a click lands
             │
        Completion          what is being typed: an include, or part of a `::` line
             │
             │   Utf8       bytes that are safe to measure and draw
             │
        SlideEditor         the window: state, input, drawing
             │
        DeckSource          reading and rewriting the deck, through the Python tools
```

Everything above `SlideEditor` is free of Skia and GLFW, compiles on its own, and its tests
run without opening a window — `player/tests/` builds those suites with no engine and no Skia
fetch at all. That is the point of the split: the arithmetic that is easy to get wrong and
impossible to review is the arithmetic that can be tested.

## TextBuffer — the model

Lines, a caret, a selection, an undo stack. It holds `std::vector<std::string>`, one entry per
line, and a `Caret {line, col}` where **col is a byte offset, not a character**. The renderer
measures byte prefixes and the buffer stores UTF-8, so a column counting characters would have
to be converted at every use; motion still moves by whole characters.

What it deliberately does not know: how wide the window is, what font it is drawn in, or that
there is a window at all. Wrapping is not its problem — see below.

Two things worth knowing before changing it:

- **Undo coalesces by edit kind.** Consecutive typing is one step; typing in two places is
  two. `begin(Edit)` decides, by comparing the kind and the caret to the last edit.
- **`revision()` counts every change.** It exists so a view can hold a layout — a wrap, say —
  until the text moves, instead of recomputing it every frame.

## ViewGeometry — rows, not lines

A window has rows; a document has lines. Until a line is longer than the window those are the
same thing, and the editor treated them as the same thing — which is why a long line used to
run off the right-hand edge and stop there.

`wrapLines` turns lines into `WrapRow{line, from, to, first}`: a slice of a line that fits a
width. Every y on screen goes through it. The rules it settles, each with a test named after
it:

| | |
|---|---|
| a word stays whole | break after the last space that fits |
| a word longer than the window | break it mid-word — a path or a URL, where the alternative is characters nobody can reach |
| a cut never splits a character | half a two-byte `é` is invalid UTF-8, and Skia answers that by aborting the process |
| every line keeps a row | so a blank line is somewhere the caret can go |
| the number sits on the first row | a blank gutter is how a continuation row reads as one |

Width is **measured, not counted**. The function takes a `MeasureRange` callback: the editor
passes Skia's text measurement, and a test passes one unit per byte and reasons in characters.
A fallback face is not monospaced, so counting would be wrong on exactly the machines where it
matters.

`rowOfCaret` answers which row a caret is on, and at a wrap point answers the *later* row —
where the next character typed will appear.

## Completion — what is being typed

Pure string work, no state. Two questions:

- `includeAt(line, col)` — is the caret inside an unclosed `<`, and in which part: the asset
  **name**, an **option** past the `|`, or an option's **value** past an `=`.
- `metaAt(line, col)` — is the caret on a `::` line, and does it want a slide **type** (the
  first word), a **flag or key** (a later word), or a key's **values**.

Both are small and both have an edge that is invisible until it is wrong: a `<` that is
already closed, a quoted `title="two words"` that is prose rather than a choice, a `:` that
separates params from vocabulary versus one inside a `[2:3]` ratio.

The *vocabulary* those menus offer is not here and not in the player at all. It comes from
`refractkit/meta.py` and `refractkit/assets.py` through `tools/meta.py` and `tools/assets.py`,
so the editor cannot offer a word the build would reject or a file the deck cannot resolve.
A slide type added to `render.SLIDE_TYPES` appears in the menu with nobody editing C++.

## SlideEditor — the window

One `Impl` holding four groups of state:

1. **The document** — the buffer, which slide or file it came from, whether a save is running.
2. **The layout** — the wrap rows, and the three things that invalidate them: the width, the
   font size, and `buffer.revision()`. Laying out measures every line, so it is held until one
   of those moves.
3. **The menu** — the candidates for wherever the caret is, which are rebuilt only when the
   *context* changes rather than every frame; what is picked; and the image and text previews,
   cached per file.
4. **The window** — the backend, the scroll, the pointer, the hit-test rectangles that are set
   while drawing and read on the next click.

### Three rules that took a bug each to learn

**Follow the caret only when it moves.** A view that scrolls to its cursor on every frame
cannot be scrolled by the wheel: the wheel moves it and the next redraw puts it back, which
reads as a window that refuses to scroll. `followCaret` is set by keys, typing and clicks, and
cleared by the render that acts on it. The deck view learned this first and the editor learned
it again.

**Nothing reaches Skia unchecked.** `textWidth` sizes a glyph buffer from a code-point count,
and Skia answers invalid UTF-8 with `abort()`. Anything drawn can come from a file. `Utf8`
exists for that, and `ellipsize` trims a whole code point at a time — trimming a byte at a time
left a dangling lead byte and took the player down mid-edit.

**The chrome has no font fallback.** One typeface, so a glyph it does not carry draws as a tofu
box. `↩` did. Spell it out.

### The frame of a render

```
layout(width)            wrap, if anything that matters changed
decide the menu          what the caret is in, what to offer, whether the pause has passed
auto-save                if typing stopped long enough ago
draw rows               one pass over visible rows: gutter, selection, text
draw the caret
draw the footer
draw the menu           last, so nothing is over it
```

## DeckSource — the way out

The editor never writes a file. Every read and every rewrite goes through `DeckSource`, which
runs the scripts in `player/tools/`, because **the markdown grammar belongs to refract**: block
numbering has to agree exactly with `markdown.py`'s, and a second implementation in C++ would
drift and rewrite the wrong slide.

Reads are synchronous — one short Python run, and the answer is wanted now. Writes are not:
refract takes seconds on a big deck, and a window frozen for them would be the wrong trade for
an editor whose whole point is not leaving the player. They go through `EditRunner` on a
worker and report back on the main thread once the deck has reloaded.

## Where the tests are

| | |
|---|---|
| `text_buffer` | caret, selection, UTF-8 motion, frame selection, undo |
| `view_geometry` | wrapping, clicking, scrolling, hit-testing |
| `completion` | which include or `::` part is being typed |
| `utf8` | that nothing the chrome trims or cuts comes out invalid |
| `scrolling` | how far a notch and a swipe each move a view |
| `deck_source` | reading a deck through the tools, and what happens when that fails |

The first five need nothing but their own source: `cmake -B build -S player/tests`. That is
deliberate — configuring the player fetches Skia, and none of it is needed to check that a
click lands on the line it is over.

## If you are changing it

- **Adding a completion**: put the "what is being typed" question in `Completion` with tests,
  the vocabulary in `refractkit/`, and only the wiring in `SlideEditor`.
- **Touching the layout**: `wrapLines` is where the judgement is. Add the case to
  `view_geometry_test` first; the property test there — every byte in exactly one row, at five
  widths — catches most mistakes on its own.
- **Drawing anything from a file**: it goes through `displayable` or `ellipsize` before it goes
  to Skia.
- **Adding state to `Impl`**: ask whether it is really view state. If a test could want it, it
  probably belongs one layer up.
