// "3-12, 20": what an export takes, read and written.
//
// Returns 0 on success, 1 on any failed assertion.

#include "SlideSelection.h"

#include <cstdio>

static int failures = 0;

#define CHECK(cond, msg) do { \
    if (!(cond)) { std::fprintf(stderr, "FAIL: %s\n", msg); ++failures; } \
} while (0)

static bool same(const std::vector<int>& a, std::vector<int> b) { return a == b; }

static void testParse() {
    std::string err;
    CHECK(same(refract::parseSlideSelection("3-5, 9", 12, &err), {2, 3, 4, 8}) && err.empty(), "a range and a slide, 1-based in, 0-based out");
    CHECK(same(refract::parseSlideSelection("", 3), {0, 1, 2}), "empty is every slide");
    CHECK(same(refract::parseSlideSelection("all", 3), {0, 1, 2}), "so is all");
    CHECK(same(refract::parseSlideSelection("9, 3, 3", 12), {2, 8}), "in order, without repeats");
    CHECK(same(refract::parseSlideSelection("10-", 12), {9, 10, 11}), "an open range runs to the end");
    CHECK(same(refract::parseSlideSelection("0-2, 40", 12), {0, 1}), "clamped to the deck");
    CHECK(refract::parseSlideSelection("3-x", 12, &err).empty() && !err.empty(), "not a range");
    CHECK(refract::parseSlideSelection("seven", 12, &err).empty() && !err.empty(), "not a number");
    CHECK(refract::parseSlideSelection("50", 12, &err).empty() && !err.empty(), "nothing in the deck");
    CHECK(refract::parseSlideSelection("1-3", 0).empty(), "an empty deck has nothing to select");
}

static void testFormat() {
    CHECK(refract::formatSlideSelection({2, 3, 4, 8}) == "3-5, 9", "runs collapse to ranges");
    CHECK(refract::formatSlideSelection({8, 4, 3, 2, 3}) == "3-5, 9", "whatever order, whatever repeats");
    CHECK(refract::formatSlideSelection({0}) == "1", "one slide is its number");
    CHECK(refract::formatSlideSelection({}).empty(), "none is nothing");
    CHECK(same(refract::parseSlideSelection(refract::formatSlideSelection({0, 1, 5}), 10), {0, 1, 5}), "round trip");
}

int main() {
    testParse();
    testFormat();
    if (failures) { std::fprintf(stderr, "%d failure(s)\n", failures); return 1; }
    std::printf("slide_selection: all passed\n");
    return 0;
}
