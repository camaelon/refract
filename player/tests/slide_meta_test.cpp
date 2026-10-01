// The `::` line at the top of a slide, read and rewritten.
//
// Returns 0 on success, 1 on any failed assertion.

#include "SlideMeta.h"

#include <cstdio>

static int failures = 0;

#define CHECK(cond, msg) do { \
    if (!(cond)) { std::fprintf(stderr, "FAIL: %s\n", msg); ++failures; } \
} while (0)

static void testReading() {
    CHECK(refract::themeOf(":: as: hero\n# A slide\n") == "hero", "the preset a slide names");
    CHECK(refract::themeOf(":: as: hero height=589.01 h3_pad_top=40\n# A slide\n") == "hero",
          "whatever else is on the line");
    CHECK(refract::themeOf("# A slide\n- a point\n").empty(), "a slide that names none");
    CHECK(refract::themeOf(":: content pane_gap=34.4\n# A slide\n").empty(), "nor does a plain type");
    CHECK(refract::themeOf("\n\n:: as: statement\n").empty() == false, "blank lines before it");
}

static void testApplying() {
    CHECK(refract::withTheme("# A slide\n- a point\n", "hero")
          == ":: as: hero\n# A slide\n- a point\n", "a slide with no line gets one");
    CHECK(refract::withTheme(":: as: hero\n# A slide\n", "statement")
          == ":: as: statement\n# A slide\n", "one preset for another");
    CHECK(refract::withTheme(":: content\n# A slide\n", "hero") == ":: as: hero\n# A slide\n",
          "a type for a preset");
    // Everything else on the line is somebody's, and stays.
    CHECK(refract::withTheme(":: as: hero height=589.01 h3_pad_top=40\n# A\n", "statement")
          == ":: as: statement height=589.01 h3_pad_top=40\n# A\n", "the overrides stay");
    CHECK(refract::withTheme(":: content pane_gap=34.4 [19066:26089:19066]\n# A\n", "bento")
          == ":: as: bento [19066:26089:19066] pane_gap=34.4\n# A\n", "so does a pane ratio");
    CHECK(refract::withTheme(":: content fragment @nico\n# A\n", "hero")
          == ":: as: hero fragment @nico\n# A\n", "so do flags and an author");
}

static void testTakingItAway() {
    CHECK(refract::withTheme(":: as: hero\n# A slide\n", "") == "# A slide\n",
          "the line goes when the preset was all it said");
    CHECK(refract::withTheme(":: as: hero pane_gap=34.4\n# A\n", "") == ":: pane_gap=34.4\n# A\n",
          "and stays for what else was on it");
    CHECK(refract::withTheme("# A slide\n", "") == "# A slide\n", "nothing to take away");
    CHECK(refract::withTheme(":: content\n# A\n", "") == ":: content\n# A\n",
          "a plain type is not a preset and is left alone");
}

int main() {
    testReading();
    testApplying();
    testTakingItAway();
    if (failures) { std::fprintf(stderr, "%d failure(s)\n", failures); return 1; }
    std::printf("slide_meta: all passed\n");
    return 0;
}
