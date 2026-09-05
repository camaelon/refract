// The deck view's grid and the slide editor's lines — the arithmetic behind clicking,
// scrolling and hit-testing, with no window in the way.
//
// Two of this player's bugs lived here and both were reported by a person rather than caught
// by anything: the grid scrolled back to the cursor on every frame, and the editor's click
// mapped against the wrong edge of a line. Each has a test below named after it.
//
// Returns 0 on success, 1 on any failed assertion.

#include "ViewGeometry.h"

#include <cmath>
#include <cstdio>
#include <initializer_list>

using refract::Box;
using refract::Grid;
using refract::GridSpec;
using refract::Lines;

static int failures = 0;

#define CHECK(cond, msg) do { \
    if (!(cond)) { std::fprintf(stderr, "FAIL: %s\n", msg); ++failures; } \
} while (0)

static void checkEq(int got, int want, const char* msg) {
    if (got != want) {
        std::fprintf(stderr, "FAIL: %s (got %d, want %d)\n", msg, got, want);
        ++failures;
    }
}

static void checkNear(float got, float want, const char* msg) {
    if (std::fabs(got - want) > 0.51f) {
        std::fprintf(stderr, "FAIL: %s (got %.2f, want %.2f)\n", msg, got, want);
        ++failures;
    }
}

// A window roughly the size the deck view opens at.
static GridSpec spec() {
    GridSpec s;
    s.width = 1180;
    s.height = 780;
    s.headerH = 74;
    s.pad = 26;
    return s;
}

static void testGridShape() {
    const Grid grid = refract::layoutGrid(spec(), 40);
    CHECK(grid.columns > 1, "a wide window fits several columns");
    CHECK(grid.cardW >= 190, "and none narrower than the minimum");
    checkNear(grid.thumbH, grid.cardW * 9.0f / 16.0f, "the thumbnail keeps the slide's shape");
    CHECK(grid.cardH > grid.thumbH, "and the card has a label strip under it");

    // The cards of a row sit side by side with a gutter between them, and the row is inside
    // the margins.
    const Box first = grid.card(0, 0), second = grid.card(1, 0);
    checkNear(first.left, grid.pad, "the first card starts at the margin");
    checkNear(second.left - first.right, grid.gutter, "one gutter between them");
    checkNear(grid.card(grid.columns - 1, 0).right, spec().width - grid.pad,
              "and the row ends at the other margin");

    // A narrow window falls back to one column rather than to cards nobody can read.
    GridSpec narrow = spec();
    narrow.width = 260;
    checkEq(refract::layoutGrid(narrow, 40).columns, 1, "a narrow window is one column");

    // Fewer cells than would fit: no empty columns.
    checkEq(refract::layoutGrid(spec(), 2).columns, 2, "two cards, two columns");
    checkEq(refract::layoutGrid(spec(), 0).cells, 0, "an empty deck has no cells");
}

static void testCardPositions() {
    const Grid grid = refract::layoutGrid(spec(), 40);
    const Box a = grid.card(0, 0);
    const Box below = grid.card(grid.columns, 0);
    checkNear(below.top - a.bottom, grid.gutter, "the next row is a gutter below");
    checkNear(below.left, a.left, "and starts in the same column");

    // Scrolling moves the cards up by exactly what was scrolled.
    checkNear(grid.card(0, 100).top, a.top - 100, "scrolling moves a card up");
    CHECK(grid.card(-1, 0).width() == 0, "a card off the start is empty");
    CHECK(grid.card(999, 0).width() == 0, "and so is one off the end");
}

static void testHitTesting() {
    const Grid grid = refract::layoutGrid(spec(), 40);
    for (int cell : {0, 1, grid.columns, 17}) {
        const Box box = grid.card(cell, 0);
        checkEq(grid.cellAt(box.centerX(), box.centerY(), 0), cell, "a click lands on its card");
    }
    // The gutter between two cards is not on either of them.
    const Box first = grid.card(0, 0);
    checkEq(grid.cellAt(first.right + grid.gutter * 0.5f, first.centerY(), 0), -1,
            "the gutter is not a card");
    checkEq(grid.cellAt(5, 5, 0), -1, "nor is the header");

    // Scrolled, a click still lands on what is drawn under it.
    const Box scrolled = grid.card(grid.columns, 200);
    checkEq(grid.cellAt(scrolled.centerX(), scrolled.centerY(), 200), grid.columns,
            "hit-testing follows the scroll");

    // Nearest is for dragging, where the pointer is often between things.
    checkEq(grid.nearestCell(first.right + grid.gutter * 0.4f, first.centerY(), 0), 0,
            "in the gutter, the card it is nearer");
    checkEq(grid.nearestCell(first.right + grid.gutter * 0.6f, first.centerY(), 0), 1,
            "and from the other side, the other one");
    checkEq(grid.nearestCell(-500, -500, 0), 0, "off the top left, the first");
    checkEq(refract::layoutGrid(spec(), 0).nearestCell(10, 10, 0), -1,
            "an empty deck has no nearest");
}

// The regression: the grid used to scroll to the cursor on every frame, so a wheel scroll
// lasted until the next redraw and no further. scrollToShow is only called when the cursor
// has actually moved — and, called then, it must leave a cursor that is already visible alone.
static void testScrollingIsNotUndoneByTheCursor() {
    const Grid grid = refract::layoutGrid(spec(), 60);

    // The wheel is turned; the cursor has not moved. The scroll must survive the frame — the
    // bug was that it did not, because the view followed the cursor on every redraw and the
    // cursor was still on the first card.
    checkNear(refract::settleScroll(grid, 200, /*cursor=*/0, /*cursorMoved=*/false), 200,
              "a wheel scroll survives a frame the cursor did not move in");
    // ...and again the next frame, and the next.
    float scroll = 200;
    for (int frame = 0; frame < 20; frame++) scroll = refract::settleScroll(grid, scroll, 0, false);
    checkNear(scroll, 200, "and every frame after that");

    // Move the cursor, and the view does come to it.
    checkNear(refract::settleScroll(grid, 200, 0, true), 0, "moving the cursor brings it back");

    // A cursor below the view brings the view down to it, and then leaves it there.
    const int lastCell = 59;
    const float shown = refract::settleScroll(grid, 0, lastCell, true);
    CHECK(shown > 0, "a cursor below the view scrolls down to it");
    checkNear(refract::settleScroll(grid, shown, lastCell, true), shown, "and stays");

    // A cursor that is already in view is left where the wheel put it.
    checkNear(refract::settleScroll(grid, 0, 1, true), 0, "no scrolling for a visible cursor");

    // Never past the ends, whichever way it got there.
    checkNear(refract::settleScroll(grid, -100, 0, false), 0, "cannot scroll above the top");
    checkNear(refract::settleScroll(grid, 99999, 0, false), grid.scrollMax,
              "nor past the bottom");
    CHECK(refract::layoutGrid(spec(), 2).scrollMax == 0, "a deck that fits does not scroll");
}

// ── The editor's lines ───────────────────────────────────────────────

static Lines lines() {
    Lines l;
    l.baselineTop = 83;    // header, plus one line: the baseline of line 0
    l.height = 21;
    l.gap = 4;
    return l;
}

// The regression: a click was mapped against the text's baseline, which is the *bottom* of
// the line it belongs to, so every click landed a line above where it was aimed.
static void testAClickLandsOnTheLineItIsOver() {
    const Lines l = lines();
    for (int line : {0, 1, 5, 12}) {
        const Box box = refract::lineBox(l, line, 0, 0, 500);
        checkEq(refract::lineAt(l, box.centerY(), 0, 40), line, "a click in a line's box");
        checkEq(refract::lineAt(l, box.top + 1, 0, 40), line, "at its very top");
        checkEq(refract::lineAt(l, box.bottom - 1, 0, 40), line, "and at its very bottom");
    }
    // The boxes are contiguous: there is no gap between two lines to click into.
    checkNear(refract::lineBox(l, 1, 0, 0, 500).top, refract::lineBox(l, 0, 0, 0, 500).bottom,
              "consecutive lines touch");
}

static void testLineHitTestingEdges() {
    const Lines l = lines();
    checkEq(refract::lineAt(l, -1000, 0, 40), 0, "above the text, the first line");
    checkEq(refract::lineAt(l, 99999, 0, 40), 39, "below it, the last");
    checkEq(refract::lineAt(l, 500, 0, 1), 0, "a one-line document has one answer");
    checkEq(refract::lineAt(l, 500, 0, 0), 0, "and an empty one does not divide by nothing");

    // Scrolled, a click lands on what is drawn under it.
    const Box box = refract::lineBox(l, 20, 300, 0, 500);
    checkEq(refract::lineAt(l, box.centerY(), 300, 40), 20, "hit-testing follows the scroll");
}

static void testScrollFollowsTheCaret() {
    const Lines l = lines();
    const float viewH = 400;
    checkNear(refract::scrollToShowLine(l, 0, 0, viewH), 0, "the top needs no scrolling");
    checkNear(refract::scrollToShowLine(l, 3, 0, viewH), 0, "nor does a line already in view");

    const float down = refract::scrollToShowLine(l, 30, 0, viewH);
    CHECK(down > 0, "a caret below the view scrolls to it");
    checkNear(refract::scrollToShowLine(l, 30, down, viewH), down, "and then stays put");

    // A caret above the view comes back to it, and never past the top.
    checkNear(refract::scrollToShowLine(l, 0, 500, viewH), 0, "back to the top");
    CHECK(refract::scrollToShowLine(l, 2, 500, viewH) >= 0, "never negative");
}

int main() {
    testGridShape();
    testCardPositions();
    testHitTesting();
    testScrollingIsNotUndoneByTheCursor();
    testAClickLandsOnTheLineItIsOver();
    testLineHitTestingEdges();
    testScrollFollowsTheCaret();

    if (failures == 0) std::fprintf(stderr, "view_geometry_test: all checks passed\n");
    else std::fprintf(stderr, "view_geometry_test: %d failure(s)\n", failures);
    return failures == 0 ? 0 : 1;
}
