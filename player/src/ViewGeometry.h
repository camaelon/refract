// Where things are: the deck view's grid, and the slide editor's lines.
//
// Both windows compute their layout at the top of a render and then hit-test the pointer
// against it. That arithmetic is the part of a window that is easy to get subtly wrong and
// impossible to notice in a code review — two bugs in this player came out of it, and both
// were found by a person saying "clicking feels off" rather than by anything automatic:
//
//   * the deck view scrolled to the cursor on *every* frame rather than only when the cursor
//     moved, which silently undid the wheel;
//   * the editor mapped a click against the text's *baseline* rather than its line box, which
//     put every click a line above where it was aimed.
//
// So it lives here, with no Skia and no window behind it, and is tested directly.
#pragma once

namespace refract {

struct Box {
    float left = 0, top = 0, right = 0, bottom = 0;
    float width() const { return right - left; }
    float height() const { return bottom - top; }
    float centerX() const { return (left + right) * 0.5f; }
    float centerY() const { return (top + bottom) * 0.5f; }
    bool contains(float x, float y) const {
        return x >= left && x < right && y >= top && y < bottom;
    }
};

// ── The deck view's grid ─────────────────────────────────────────────

struct GridSpec {
    float width = 0, height = 0;
    float headerH = 0;          // the strip above the grid
    float pad = 0;              // margin around it
    float gutter = 14;          // between cards
    float minCardW = 190;       // below this the titles stop being readable
    float thumbAspect = 9.0f / 16.0f;
    float labelH = 34;          // the strip under a card: number, title, any run bars
};

struct Grid {
    int   columns = 1;
    int   cells = 0;
    float cardW = 0, thumbH = 0, cardH = 0;
    float gutter = 0, pad = 0, headerH = 0;
    float viewH = 0;            // how much of the grid is on screen
    float scrollMax = 0;

    // Where a card is, at this scroll. Cells outside the deck give an empty box.
    Box card(int cell, float scroll) const;
    // The cell under a point, or -1 when the point is not on one.
    int cellAt(float x, float y, float scroll) const;
    // The cell a point is nearest, or -1 when there are none. Vertical distance is weighted:
    // rows are far apart compared to columns, and a pointer between two rows should not snap
    // sideways to a card it is nowhere near.
    int nearestCell(float x, float y, float scroll) const;

    // The scroll that brings `cell` into view, or `scroll` unchanged when it already is.
    // Only ever called when the cursor has *moved* — applying it every frame is what undid
    // the wheel.
    float scrollToShow(int cell, float scroll) const;
    float clampScroll(float scroll) const;
};

Grid layoutGrid(const GridSpec& spec, int cells);

// The scroll for this frame, and the rule that binds the view to the cursor.
//
// `cursorMoved` must be true only on the frame the cursor was actually moved — by a key, a
// click, or a selection restored after an edit — and false on every other. Passing true
// always is the bug this is written down to prevent: the view then follows the cursor on
// every redraw, which quietly undoes the wheel a fiftieth of a second after it turns.
float settleScroll(const Grid& grid, float scroll, int cursor, bool cursorMoved);

// ── The slide editor's lines ─────────────────────────────────────────

struct Lines {
    float baselineTop = 0;   // the baseline of line 0, before scrolling
    float height = 1;        // one line, including the gap
    float gap = 0;           // between the baseline and the bottom of the line's box
};

// A line's box — the strip a click lands in and a selection is painted over. It runs from one
// line *above* the baseline, which is the whole point: the baseline is where the glyphs sit,
// not where the line starts.
Box lineBox(const Lines& lines, int line, float scroll, float left, float right);

// The line under a point. Clamped into the document, so a click in the margin below the last
// line lands on the last line rather than nowhere.
int lineAt(const Lines& lines, float y, float scroll, int lineCount);

// The scroll that keeps `line` on screen, given how tall the text area is.
float scrollToShowLine(const Lines& lines, int line, float scroll, float viewH);

}  // namespace refract
