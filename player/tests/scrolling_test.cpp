// Turning a scroll event into a distance.
//
// One callback, two devices, no flag saying which. The thing worth pinning down is that a
// wheel notch moves a useful distance — a notch that moves one row is the complaint this
// came from — without a trackpad swipe becoming a leap.
//
// Returns 0 on success, 1 on any failed assertion.

#include "Scrolling.h"

#include <cmath>
#include <cstdio>

static int failures = 0;

#define CHECK(cond, msg) do { \
    if (!(cond)) { std::fprintf(stderr, "FAIL: %s\n", msg); ++failures; } \
} while (0)

static void testAWheelNotchMovesSeveralLines() {
    const float row = 44;
    const float one = refract::scrollPixels(1.0, row);
    CHECK(one > row * 2, "a notch moves more than two rows");
    CHECK(one < row * 5, "and not a screenful");
    // The complaint: one notch, one row.
    CHECK(one != row, "a notch is not one row");
}

static void testDirection() {
    CHECK(refract::scrollPixels(-1.0, 44) == -refract::scrollPixels(1.0, 44),
          "down is up, mirrored");
    CHECK(refract::scrollPixels(0.0, 44) == 0.0f, "nothing is nothing");
}

static void testNotchesScaleWithTheView() {
    // A card in the deck view is much taller than a row in the asset list, and a notch
    // should mean the same *amount of view* in both.
    CHECK(refract::scrollPixels(1.0, 150) > refract::scrollPixels(1.0, 44),
          "a taller row means a longer notch");
    CHECK(std::fabs(refract::scrollPixels(1.0, 150) / refract::scrollPixels(1.0, 44)
                    - 150.0f / 44.0f) < 0.01f,
          "in proportion");
}

static void testATwoNotchEventIsTwoNotches() {
    CHECK(std::fabs(refract::scrollPixels(2.0, 44) - 2 * refract::scrollPixels(1.0, 44)) < 0.01f,
          "two notches at once move twice as far");
}

static void testASwipeIsAContinuousDistance() {
    // Precise deltas arrive as a stream of small fractions. They must not each be given a
    // notch's distance, or a swipe would fly off the end of the list.
    const float small = refract::scrollPixels(0.2, 44);
    CHECK(small > 0, "a small swipe still moves");
    CHECK(small < refract::scrollPixels(1.0, 44) * 0.5f, "but much less than a notch");
    // And it accumulates smoothly: ten events of 0.2 are one event of 2.0-worth of finger.
    float summed = 0;
    for (int i = 0; i < 10; i++) summed += refract::scrollPixels(0.2, 44);
    CHECK(std::fabs(summed - refract::scrollPixels(0.2, 44) * 10) < 0.01f,
          "a swipe is linear in the finger's movement");
}

static void testASwipeDoesNotDependOnTheRowHeight() {
    // The finger has already said how far; the view's rows have nothing to add to it.
    CHECK(refract::scrollPixels(0.3, 44) == refract::scrollPixels(0.3, 200),
          "a swipe moves the same distance whatever is being scrolled");
}

static void testAViewThatHasNotBeenLaidOutYet() {
    // A panel can be scrolled before its first frame, when it does not yet know how tall its
    // rows are. A notch still has to move something.
    CHECK(refract::scrollPixels(1.0, 0) > 0, "a notch moves even with no row height");
    CHECK(refract::scrollPixels(1.0, -5) > 0, "and with a nonsensical one");
}

int main() {
    testAWheelNotchMovesSeveralLines();
    testDirection();
    testNotchesScaleWithTheView();
    testATwoNotchEventIsTwoNotches();
    testASwipeIsAContinuousDistance();
    testASwipeDoesNotDependOnTheRowHeight();
    testAViewThatHasNotBeenLaidOutYet();
    if (failures == 0) std::printf("scrolling: ok\n");
    return failures == 0 ? 0 : 1;
}
