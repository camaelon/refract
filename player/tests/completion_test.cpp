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
    CHECK(at.want == refract::IncludeWant::Name, "and it is the name that is wanted");
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

// ── The `::` line ────────────────────────────────────────────────────

static void testNotAMetaLine() {
    CHECK(refract::metaAt("# A heading", 5).want == refract::MetaWant::None,
          "a heading is not a `::` line");
    CHECK(refract::metaAt("see :: for the syntax", 12).want == refract::MetaWant::None,
          "a `::` part way along a line of prose is prose");
    CHECK(refract::metaAt("", 0).want == refract::MetaWant::None, "an empty line");
}

static void testTheFirstWordIsTheType() {
    const refract::MetaContext at = refract::metaAt(":: ", 3);
    CHECK(at.want == refract::MetaWant::Type, "right after `:: ` the first word is wanted");
    CHECK(at.prefix.empty(), "with nothing typed of it");
    CHECK(at.start == 3, "starting where the caret is");

    const refract::MetaContext part = refract::metaAt(":: sec", 6);
    CHECK(part.want == refract::MetaWant::Type, "part way through the first word");
    CHECK(part.prefix == "sec", "and that is the prefix");
    CHECK(part.start == 3, "which starts after the `:: `");
}

static void testTheCaretInsideTheFirstWord() {
    // Typing over the middle of a word: what is behind the caret is the prefix.
    const refract::MetaContext at = refract::metaAt(":: section", 6);
    CHECK(at.want == refract::MetaWant::Type && at.prefix == "sec",
          "the prefix stops at the caret");
}

static void testALaterWordIsAFlagOrAKey() {
    const refract::MetaContext at = refract::metaAt(":: content ste", 14);
    CHECK(at.want == refract::MetaWant::Word, "the second word is not a type");
    CHECK(at.prefix == "ste", "and carries what has been typed");
    CHECK(at.start == 11, "starting after the space");

    CHECK(refract::metaAt(":: content steps no", 19).want == refract::MetaWant::Word,
          "and so is the third");
}

static void testAKeyWantsItsValues() {
    const refract::MetaContext at = refract::metaAt(":: content transition=pu", 24);
    CHECK(at.want == refract::MetaWant::Value, "after `=` the key's values are wanted");
    CHECK(at.key == "transition", "the key is what came before it");
    CHECK(at.prefix == "pu", "and the prefix is what came after");
    CHECK(at.start == 22, "which starts just after the `=`");

    const refract::MetaContext empty = refract::metaAt(":: content chrome=", 18);
    CHECK(empty.want == refract::MetaWant::Value && empty.key == "chrome",
          "an `=` with nothing after it still wants values");
    CHECK(empty.prefix.empty(), "with no prefix");
}

static void testAValueWithAnEqualsInIt() {
    // Only the first `=` splits: a value may contain one.
    const refract::MetaContext at = refract::metaAt(":: content bg=a=b", 17);
    CHECK(at.key == "bg" && at.prefix == "a=b", "the first `=` is the one that splits");
}

static void testParamsAreNotVocabulary() {
    // `:: include : intro` — past the lone colon is a sub-deck's name, not a word from
    // any list, and offering slide types there would be nonsense.
    CHECK(refract::metaAt(":: include : int", 16).want == refract::MetaWant::None,
          "past a spaced colon nothing is offered");
    CHECK(refract::metaAt(":: same : Speaker Name", 22).want == refract::MetaWant::None,
          "and a speaker is not vocabulary either");
    // Before the colon it is still the `::` line's own words.
    CHECK(refract::metaAt(":: inc", 6).want == refract::MetaWant::Type,
          "the type before it is offered as usual");
}

static void testAColonInsideAValueIsNotTheSeparator() {
    // A ratio and a colour can both carry a colon without ending the vocabulary.
    const refract::MetaContext at = refract::metaAt(":: split [2:3] bg", 17);
    CHECK(at.want == refract::MetaWant::Word, "a ratio's colon is not the separator");
    CHECK(at.prefix == "bg", "and the word after it is still a word");
}

static void testTheCaretInsideTheMarker() {
    CHECK(refract::metaAt(":: content", 1).want == refract::MetaWant::None,
          "the caret between the two colons wants nothing");
    // Straight after `::`, with no space yet typed, is the *first* moment worth offering
    // anything — it is the `::` equivalent of typing `<`.
    const refract::MetaContext at = refract::metaAt("::", 2);
    CHECK(at.want == refract::MetaWant::Type, "just after `::` the types are offered");
    CHECK(at.prefix.empty() && at.start == 2, "with nothing typed, at the caret");
}

static void testLeadingSpace() {
    // The parser strips the line before looking for `::`, so this does too.
    const refract::MetaContext at = refract::metaAt("   :: sec", 9);
    CHECK(at.want == refract::MetaWant::Type && at.prefix == "sec",
          "an indented `::` line is still a `::` line");
}

static void testAColumnOffTheEndOfAMetaLine() {
    CHECK(refract::metaAt(":: content", 99).want == refract::MetaWant::None,
          "a column past the line is refused");
    CHECK(refract::metaAt(":: content", -1).want == refract::MetaWant::None,
          "and a negative one");
}

// ── Options after the `|` ────────────────────────────────────────────

static void testTheBarStartsTheOptions() {
    const refract::Include at = refract::includeAt("<clip.mp4 | ", 12);
    CHECK(at.want == refract::IncludeWant::Option, "past the bar an option is wanted");
    CHECK(at.name == "clip.mp4", "and the asset it is for is remembered");
    CHECK(at.prefix.empty(), "with nothing typed of it");
    CHECK(at.start == 12, "at the caret");
}

static void testAPartlyTypedOption() {
    const refract::Include at = refract::includeAt("<clip.mp4 | cr", 14);
    CHECK(at.want == refract::IncludeWant::Option && at.prefix == "cr", "a partial option");
    CHECK(at.start == 12, "starts after the space");
    CHECK(at.name == "clip.mp4", "and still knows its asset");
}

static void testASecondOption() {
    const refract::Include at = refract::includeAt("<clip.mp4 | fit=fill sta", 24);
    CHECK(at.want == refract::IncludeWant::Option && at.prefix == "sta",
          "a later option is still an option");
    CHECK(at.name == "clip.mp4", "with the same asset");
}

static void testAnOptionsValues() {
    const refract::Include at = refract::includeAt("<clip.mp4 | fit=fi", 18);
    CHECK(at.want == refract::IncludeWant::Value, "after `=` the values are wanted");
    CHECK(at.key == "fit", "for that option");
    CHECK(at.prefix == "fi", "with what has been typed");
    CHECK(at.start == 16, "starting after the `=`");
}

static void testAQuotedValueIsNotChosenFromAList() {
    // `title="Launcher Widget"` is prose. Offering a menu over it, and worse completing
    // into it, would be in the way.
    CHECK(refract::includeAt("<a.rc | title=\"Laun", 19).want == refract::IncludeWant::None,
          "a quoted value offers nothing");
    CHECK(refract::includeAt("<a.rc | title='Laun", 19).want == refract::IncludeWant::None,
          "single quotes too");
    // Unquoted, it is still a value — there is just nothing to offer for it.
    CHECK(refract::includeAt("<a.rc | title=One", 17).want == refract::IncludeWant::Value,
          "an unquoted one is an ordinary value");
}

static void testTheNameKeepsItsSpaces() {
    // A name is taken up to the bar with the padding trimmed, however it was spaced.
    CHECK(refract::includeAt("<a/b.json|fit=", 14).name == "a/b.json",
          "no spaces around the bar");
    CHECK(refract::includeAt("<a/b.json   |  fit=", 19).name == "a/b.json",
          "several spaces before it");
}

static void testTheNameIsStillTheNameBeforeTheBar() {
    const refract::Include at = refract::includeAt("<clip", 5);
    CHECK(at.want == refract::IncludeWant::Name && at.prefix == "clip",
          "before any bar it is a name");
    CHECK(at.name.empty(), "and there is no asset decided yet");
}

static void testAClosedIncludeWithOptions() {
    CHECK(!refract::includeAt("<a.mp4 | fit=fill>", 18).found,
          "a finished include with options offers nothing");
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
    testNotAMetaLine();
    testTheFirstWordIsTheType();
    testTheCaretInsideTheFirstWord();
    testALaterWordIsAFlagOrAKey();
    testAKeyWantsItsValues();
    testAValueWithAnEqualsInIt();
    testParamsAreNotVocabulary();
    testAColonInsideAValueIsNotTheSeparator();
    testTheCaretInsideTheMarker();
    testLeadingSpace();
    testAColumnOffTheEndOfAMetaLine();
    testTheBarStartsTheOptions();
    testAPartlyTypedOption();
    testASecondOption();
    testAnOptionsValues();
    testAQuotedValueIsNotChosenFromAList();
    testTheNameKeepsItsSpaces();
    testTheNameIsStillTheNameBeforeTheBar();
    testAClosedIncludeWithOptions();
    if (failures == 0) std::printf("completion: ok\n");
    return failures == 0 ? 0 : 1;
}
