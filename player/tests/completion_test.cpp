// Offering a deck's assets while an include is being typed.
//
// Every check here is a case that looks like the others until it isn't: a bracket that is
// already closed, a slide that came out of a sub-deck, a prefix that matches in the middle
// of a name. The menu appearing over the wrong bracket, or offering a name the file cannot
// actually resolve, both build a slide that renders nothing.
//
// Returns 0 on success, 1 on any failed assertion.

#include "Completion.h"

#include <cstdio>
#include <string>
#include <vector>

static int failures = 0;

#define CHECK(cond, msg) do { \
    if (!(cond)) { std::fprintf(stderr, "FAIL: %s\n", msg); ++failures; } \
} while (0)

static void testTheBracketJustTyped() {
    const refract::Include at = refract::includeAt("<", 1);
    CHECK(at.found, "a lone `<` is an include being typed");
    CHECK(at.start == 0, "starting at column 0");
    CHECK(at.prefix.empty(), "with nothing typed into it yet");
}

static void testWhatHasBeenTyped() {
    const refract::Include at = refract::includeAt("some text <lo", 13);
    CHECK(at.found, "a `<` part way along the line");
    CHECK(at.start == 10, "at the column it is on");
    CHECK(at.prefix == "lo", "and what has been typed since");
}

static void testAClosedIncludeIsNotBeingTyped() {
    // The caret is after `<logo.png>`; that include is finished and offering names for it
    // would put a menu over a slide that is already right.
    CHECK(!refract::includeAt("<logo.png>", 10).found, "a closed include offers nothing");
    CHECK(!refract::includeAt("<logo.png> and more", 19).found, "nor does one further back");
    // But a second, unclosed one after it is.
    const refract::Include at = refract::includeAt("<logo.png> <ca", 14);
    CHECK(at.found && at.start == 11 && at.prefix == "ca", "the second one is being typed");
}

static void testNoBracketAtAll() {
    CHECK(!refract::includeAt("", 0).found, "an empty line");
    CHECK(!refract::includeAt("# A heading", 11).found, "ordinary text");
    // The caret is before the bracket, not in it.
    CHECK(!refract::includeAt("<logo", 0).found, "a caret at the start of the line");
}

static void testTheCaretInsideTheName() {
    // Half way through a name: what has been typed is what is *behind* the caret, so
    // completing replaces that and leaves the rest — which is what typing over means.
    const refract::Include at = refract::includeAt("<logo.png", 3);
    CHECK(at.found && at.prefix == "lo", "the prefix stops at the caret");
}

static void testAColumnOffTheEnd() {
    // A caret column past the line cannot be turned into a prefix; it should say no rather
    // than read off the end of the string.
    CHECK(!refract::includeAt("<lo", 99).found, "a column past the line is refused");
    CHECK(!refract::includeAt("<lo", -1).found, "and so is a negative one");
}

static void testWhereANameResolves() {
    CHECK(refract::includeBase("slides.md") == "includes/",
          "the deck's own markdown resolves against its includes/");
    CHECK(refract::includeBase("includes/intro/slides.md") == "includes/intro/includes/",
          "a sub-deck's slide resolves against the sub-deck's");
    CHECK(refract::includeBase("") == "includes/", "and nothing named still has a base");
}

static void testWhichNamesAFileCanWrite() {
    const std::vector<std::string> paths = {
        "includes/logo.png",
        "includes/card.json",
        "includes/deep/diagram.png",
        "includes/intro/slides.md",
        "includes/intro/includes/inner.png",
    };
    const std::vector<std::string> top = refract::namesUnder(paths, "includes/");
    CHECK(top.size() == 5, "everything under includes/ is reachable from the top deck");
    CHECK(top[0] == "logo.png", "by its bare name");
    CHECK(top[2] == "deep/diagram.png", "and a subdirectory by its path, which resolves too");

    // From inside the sub-deck, only the sub-deck's own assets can be named — the top
    // deck's logo.png is not reachable by any name written there.
    const std::vector<std::string> inner =
        refract::namesUnder(paths, "includes/intro/includes/");
    CHECK(inner.size() == 1 && inner[0] == "inner.png", "the sub-deck sees only its own");
}

static void testTheBaseItselfIsNotAName() {
    // A directory entry exactly equal to the base would otherwise come back as "".
    const std::vector<std::string> names = refract::namesUnder({"includes/"}, "includes/");
    CHECK(names.empty(), "the includes/ directory is not an asset");
}

static void testMatching() {
    const std::vector<std::string> names = {"logo.png", "card.json", "widget.rc",
                                            "old-logo.png", "Diagram.PNG"};
    const std::vector<int> all = refract::matchNames(names, "");
    CHECK(all.size() == 5, "an empty prefix offers everything");
    CHECK(all[0] == 0, "in the order it came in");

    const std::vector<int> lo = refract::matchNames(names, "lo");
    CHECK(lo.size() == 2, "two names have `lo` in them");
    CHECK(lo[0] == 0, "the one that starts with it comes first");
    CHECK(lo[1] == 3, "the one that merely contains it comes after");

    CHECK(refract::matchNames(names, "zzz").empty(), "a prefix nothing matches offers nothing");
}

static void testMatchingIgnoresCase() {
    const std::vector<std::string> names = {"Diagram.PNG", "logo.png"};
    CHECK(refract::matchNames(names, "diag").size() == 1, "a lowercase prefix finds it");
    CHECK(refract::matchNames(names, "DIAG").size() == 1, "and so does an uppercase one");
    CHECK(refract::matchNames(names, ".png").size() == 2,
          "an extension typed in either case finds both");
}

static void testMatchingKeepsOrderWithinEachGroup() {
    const std::vector<std::string> names = {"a-x.png", "x-1.png", "b-x.png", "x-2.png"};
    const std::vector<int> out = refract::matchNames(names, "x");
    CHECK(out.size() == 4, "all four have an x");
    CHECK(out[0] == 1 && out[1] == 3, "the two that start with it, in their own order");
    CHECK(out[2] == 0 && out[3] == 2, "then the two that contain it, in theirs");
}

int main() {
    testTheBracketJustTyped();
    testWhatHasBeenTyped();
    testAClosedIncludeIsNotBeingTyped();
    testNoBracketAtAll();
    testTheCaretInsideTheName();
    testAColumnOffTheEnd();
    testWhereANameResolves();
    testWhichNamesAFileCanWrite();
    testTheBaseItselfIsNotAName();
    testMatching();
    testMatchingIgnoresCase();
    testMatchingKeepsOrderWithinEachGroup();
    if (failures == 0) std::printf("completion: ok\n");
    return failures == 0 ? 0 : 1;
}
