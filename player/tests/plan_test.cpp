// The talk as it was planned.
//
// `:: section duration=12m` is a claim about a part of the talk; these check what the deck
// makes of a set of them — how long the whole thing is meant to run, and where it should have
// got to by any given moment. The judgement calls are what is worth pinning down: a section
// that states no duration, and the slides that come before the first section.
//
// Returns 0 on success, 1 on any failed assertion.

#include "Plan.h"

#include <cmath>
#include <cstdio>
#include <vector>

static int failures = 0;

#define CHECK(cond, msg) do { \
    if (!(cond)) { std::fprintf(stderr, "FAIL: %s\n", msg); ++failures; } \
} while (0)

static bool near(double a, double b) { return std::fabs(a - b) < 1e-4; }

// Three sections of ten minutes each, starting at slides 0, 10 and 20, over a 30-slide deck.
static std::vector<refract::PlanSection> evenTalk() {
    return {{0, 600}, {10, 600}, {20, 600}};
}

static void testNoPlanAtAll() {
    CHECK(refract::plannedTotal({}) == 0, "a deck with no sections has no plan");
    CHECK(refract::plannedTotal({{0, 0}, {10, 0}}) == 0,
          "nor one whose sections state no duration");
    CHECK(refract::plannedFraction({{0, 0}}, 10, 60) < 0,
          "and there is no position to report");
    CHECK(refract::plannedFraction({}, 10, 60) < 0, "likewise with no sections");
}

static void testTheSlotsLineUp() {
    // Each section is due when the ones before it are done; an untimed one is the average.
    const auto slots = refract::planSlots({{0, 600}, {10, 0}, {20, 1200}});
    CHECK(slots.size() == 3, "a slot per section");
    CHECK(near(slots[0].start, 0) && near(slots[0].duration, 600) && slots[0].timed,
          "the first starts at the top");
    CHECK(near(slots[1].start, 600) && near(slots[1].duration, 900) && !slots[1].timed,
          "an untimed one starts after it and is worth the average");
    CHECK(near(slots[2].start, 1500) && near(slots[2].duration, 1200), "and so on");
    CHECK(refract::planSlots({{0, 0}}).empty(), "nothing planned, no slots");
}

static void testTheTimeline() {
    // Nothing known: the slide count.
    auto t = refract::slideTimeline({}, 4, {});
    CHECK(t.size() == 5 && near(t[4], 4) && near(t[2], 2), "no durations at all: one unit a slide");
    // Narration known for some: the rest take the average of it.
    t = refract::slideTimeline({}, 4, {10, 0, 30, 0});
    CHECK(near(t[1], 10) && near(t[2], 30) && near(t[3], 60) && near(t[4], 80),
          "unnarrated slides take the narrated average");
    // A plan: a part's budget split over its slides, after its narrated ones.
    t = refract::slideTimeline({{0, 100}, {2, 60}}, 4, {0, 0, 20, 0});
    CHECK(near(t[1], 50) && near(t[2], 100), "part one: 100 s over two slides");
    CHECK(near(t[3], 120) && near(t[4], 160), "part two: 20 s narrated, the other 40");
    // A part over budget on narration alone still gives its other slides a sliver.
    t = refract::slideTimeline({{0, 10}}, 2, {30, 0});
    CHECK(near(t[1], 30) && t[2] > t[1], "never zero for a slide");
}

static void testTheTotalIsTheSum() {
    CHECK(near(refract::plannedTotal(evenTalk()), 1800), "three tens make thirty minutes");
    CHECK(near(refract::plannedTotal({{0, 300}, {5, 900}}), 1200), "and uneven parts add up");
}

static void testASectionWithNoDurationTakesTheAverage() {
    // Given zero it would be instantaneous and everything after it would read as late.
    const std::vector<refract::PlanSection> mixed = {{0, 600}, {10, 0}, {20, 1200}};
    CHECK(near(refract::plannedTotal(mixed), 600 + 900 + 1200),
          "the silent section is worth the average of the two that spoke");
}

static void testWhereTheTalkShouldBe() {
    const auto plan = evenTalk();
    CHECK(near(refract::plannedFraction(plan, 30, 0), 0.0),
          "at the start, at the start");
    // Five minutes in: half way through the first section, which is slides 0-9 of 30.
    CHECK(near(refract::plannedFraction(plan, 30, 300), 5.0 / 30),
          "half way through the first part");
    // Ten minutes: the second section begins, at slide 10.
    CHECK(near(refract::plannedFraction(plan, 30, 600), 10.0 / 30),
          "at the boundary, at the boundary");
    CHECK(near(refract::plannedFraction(plan, 30, 900), 15.0 / 30),
          "half way through the second part");
}

static void testPastTheEnd() {
    const auto plan = evenTalk();
    CHECK(near(refract::plannedFraction(plan, 30, 1800), 1.0),
          "at the planned end, at the end of the deck");
    CHECK(near(refract::plannedFraction(plan, 30, 5000), 1.0),
          "and overrunning does not push it past it");
}

static void testSlidesBeforeTheFirstSection() {
    // A title slide, then sections at 1 and 11, over 21 slides. The first section's budget
    // covers the title too, so the plan has no gap at the front.
    const std::vector<refract::PlanSection> plan = {{1, 600}, {11, 600}};
    CHECK(near(refract::plannedFraction(plan, 21, 0), 0.0),
          "the plan starts at the top of the deck, not at the first heading");
    CHECK(near(refract::plannedFraction(plan, 21, 300), 5.5 / 21),
          "and the first budget is spread over the slides before it too");
}

static void testOneSection() {
    const std::vector<refract::PlanSection> plan = {{0, 600}};
    CHECK(near(refract::plannedFraction(plan, 10, 300), 0.5), "half the time, half the deck");
    CHECK(near(refract::plannedTotal(plan), 600), "and the total is its own");
}

static void testTheMonotony() {
    // The property that matters for a marker somebody watches: it only ever goes forwards.
    const auto plan = evenTalk();
    float last = -1;
    for (double t = 0; t <= 2000; t += 7) {
        const float at = refract::plannedFraction(plan, 30, t);
        CHECK(at >= last - 1e-6f, "the planned position never goes backwards");
        CHECK(at >= 0.0f && at <= 1.0f, "and stays on the deck");
        last = at;
    }
}

static void testNonsense() {
    CHECK(refract::plannedFraction(evenTalk(), 0, 60) < 0, "a deck with no slides");
    CHECK(refract::plannedFraction(evenTalk(), 30, -5) < 0, "a negative time");
}

int main() {
    testNoPlanAtAll();
    testTheTotalIsTheSum();
    testTheSlotsLineUp();
    testTheTimeline();
    testASectionWithNoDurationTakesTheAverage();
    testWhereTheTalkShouldBe();
    testPastTheEnd();
    testSlidesBeforeTheFirstSection();
    testOneSection();
    testTheMonotony();
    testNonsense();
    if (failures == 0) std::printf("plan: ok\n");
    return failures == 0 ? 0 : 1;
}
