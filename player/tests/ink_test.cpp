// Drawing on slides with the laser: strokes, per slide, kept for the run.
//
// Returns 0 on success, 1 on any failed assertion.

#include "Ink.h"

#include <cstdio>

static int failures = 0;

#define CHECK(cond, msg) do { \
    if (!(cond)) { std::fprintf(stderr, "FAIL: %s\n", msg); ++failures; } \
} while (0)

static void testStrokes() {
    refract::Ink ink;
    CHECK(!ink.any(3) && ink.strokes(3).empty() && !ink.drawing(), "a fresh slide has no marks");
    ink.extend(0.5f, 0.5f);
    CHECK(!ink.any(3), "a move with no button down draws nothing");
    ink.begin(3, 0.10f, 0.10f);
    CHECK(ink.drawing() && ink.any(3) && ink.strokes(3).size() == 1, "the button down starts a stroke");
    ink.extend(0.10f, 0.10f);
    ink.extend(0.1005f, 0.1005f);
    CHECK(ink.strokes(3)[0].points.size() == 1, "a rest or a jitter adds no point");
    ink.extend(0.20f, 0.10f);
    ink.extend(0.30f, 0.10f);
    CHECK(ink.strokes(3)[0].points.size() == 3, "a move does");
    ink.end();
    CHECK(!ink.drawing(), "the button up ends it");
    ink.extend(0.40f, 0.10f);
    CHECK(ink.strokes(3)[0].points.size() == 3, "and nothing is added after");
    ink.begin(3, 0.50f, 0.50f);
    ink.end();
    CHECK(ink.strokes(3).size() == 2 && ink.strokes(3)[1].points.size() == 1, "a click is a dot");
    CHECK(!ink.any(4), "another slide is untouched");
}

static void testPerSlide() {
    refract::Ink ink;
    ink.begin(1, 0.1f, 0.1f);
    ink.extend(0.2f, 0.2f);
    ink.end();
    ink.begin(5, 0.1f, 0.1f);
    ink.end();
    CHECK(ink.marked() == 2, "two slides marked");
    CHECK(ink.any(1) && ink.any(5), "each keeps its own");
    ink.clear(1);
    CHECK(!ink.any(1) && ink.any(5) && ink.marked() == 1, "clearing one leaves the other");
    ink.begin(5, 0.3f, 0.3f);
    ink.clear(5);
    CHECK(!ink.drawing() && !ink.any(5), "clearing the slide being drawn on ends the stroke too");
    ink.begin(7, 0.3f, 0.3f);
    ink.clearAll();
    CHECK(ink.marked() == 0 && !ink.drawing(), "clearing everything");
}

int main() {
    testStrokes();
    testPerSlide();
    if (failures) { std::fprintf(stderr, "%d failure(s)\n", failures); return 1; }
    std::printf("ink: all passed\n");
    return 0;
}
