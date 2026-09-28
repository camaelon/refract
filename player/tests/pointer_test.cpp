// The mouse over the slide window: hiding it, and the laser's trail.
//
// Returns 0 on success, 1 on any failed assertion.

#include "Pointer.h"

#include <cstdio>

static int failures = 0;

#define CHECK(cond, msg) do { \
    if (!(cond)) { std::fprintf(stderr, "FAIL: %s\n", msg); ++failures; } \
} while (0)

static void testIdle() {
    refract::Pointer p;
    CHECK(p.idle(3.0, 3.0), "untouched since launch, the arrow hides after the wait");
    CHECK(!p.idle(2.9, 3.0), "but not before");
    p.moved(10, 10, 5.0);
    CHECK(!p.idle(7.9, 3.0) && p.idle(8.0, 3.0), "the wait restarts at every move");
    CHECK(p.inside(), "a move means the mouse is over the window");
    p.left();
    CHECK(!p.inside(), "until it leaves");
}

static void testLaserTrail() {
    refract::Pointer p;
    p.moved(0, 0, 0.0);
    CHECK(p.trail(0.1, 0.5).empty(), "no trail while the laser is off");
    p.setLaser(true);
    CHECK(p.trail(0.1, 0.5).empty(), "turning it on starts a fresh trail");
    p.moved(10, 10, 1.0);
    p.moved(20, 10, 1.2);
    p.moved(20, 10, 1.3);              // the mouse rests: no new dot
    p.moved(30, 10, 1.4);
    std::vector<refract::Pointer::Sample> t = p.trail(1.5, 0.5);
    CHECK(t.size() == 3, "three moves, three dots — a rest adds none");
    CHECK(t.front().x == 10 && t.back().x == 30, "oldest first");
    t = p.trail(1.75, 0.5);
    CHECK(t.size() == 2 && t.front().x == 20, "dots older than the fade are gone");
    refract::Pointer::Sample head;
    CHECK(p.head(&head) && head.x == 30, "the dot itself is the newest sample");
    p.left();
    CHECK(p.trail(1.5, 0.5).empty() && !p.head(&head), "nothing drawn once the mouse is out of the window");
    p.entered();
    CHECK(p.head(&head), "and back when it returns");
    CHECK(p.shown(1.5), "the dot shows while the mouse is fresh");
    CHECK(!p.shown(1.4 + refract::kPointerHideAfterSec), "and goes when it has rested as long as the arrow would");
    p.moved(32, 10, 9.0);
    CHECK(p.shown(9.1), "back on the first move");
    p.setLaser(false);
    CHECK(!p.head(&head), "off is off");
    CHECK(p.idle(1.6, 3.0), "and the arrow stays hidden: turning the laser off is not a move");
    p.moved(31, 10, 1.7);
    CHECK(!p.idle(1.8, 3.0), "until the mouse moves");
}

int main() {
    testIdle();
    testLaserTrail();
    if (failures) { std::fprintf(stderr, "%d failure(s)\n", failures); return 1; }
    std::printf("pointer: all passed\n");
    return 0;
}
