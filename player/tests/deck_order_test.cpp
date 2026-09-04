// Reordering arithmetic: grouping slides by the markdown block they came from, and turning
// a drop ("put this block before that one") into the pair of deck positions the reorder
// tool takes.
//
// The companion to refract's tests/test_reorder.py, which covers the other half — turning
// that pair into a rewritten slides.md. Between them the two ends of a drag are pinned:
// this one that the right block is picked, that one that the right text moves.
//
// Pure logic, no window and no engine. Returns 0 on success, 1 on any failed assertion.

#include "DeckOrder.h"

#include <cstdio>
#include <string>
#include <vector>

using refract::SlideGroup;
using refract::SlideSource;

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

// A deck where every slide is its own block: three slides, three chunks.
static std::vector<SlideSource> simpleDeck() {
    return {{"slides.md", 0}, {"slides.md", 1}, {"slides.md", 2}};
}

// Five slides from three blocks — the middle block was expanded into three fragment steps,
// which is what refract does to a stepped bullet list.
static std::vector<SlideSource> expandedDeck() {
    return {{"slides.md", 0},
            {"slides.md", 1}, {"slides.md", 1}, {"slides.md", 1},
            {"slides.md", 2}};
}

// A parent deck with an `:: include` in the middle: two of its slides are written in
// another file entirely.
static std::vector<SlideSource> includingDeck() {
    return {{"slides.md", 0},
            {"includes/sub/slides.md", 0}, {"includes/sub/slides.md", 1},
            {"slides.md", 2}};
}

static void testGrouping() {
    auto groups = refract::groupSlides(simpleDeck());
    checkEq(static_cast<int>(groups.size()), 3, "one group per slide when blocks differ");
    for (int i = 0; i < 3; i++) checkEq(groups[i].count(), 1, "singleton group");

    groups = refract::groupSlides(expandedDeck());
    checkEq(static_cast<int>(groups.size()), 3, "expanded slides collapse into one group");
    checkEq(groups[1].first, 1, "expanded group starts at its first slide");
    checkEq(groups[1].last, 3, "expanded group ends at its last slide");
    checkEq(groups[1].count(), 3, "expanded group counts every step");

    // Same block number in two different files is two different blocks.
    groups = refract::groupSlides(includingDeck());
    checkEq(static_cast<int>(groups.size()), 4, "blocks in different files never merge");

    // Non-adjacent slides from the same block would mean the deck was reordered under us;
    // grouping is by *run*, so they stay apart rather than swallowing what sits between.
    groups = refract::groupSlides({{"slides.md", 0}, {"slides.md", 1}, {"slides.md", 0}});
    checkEq(static_cast<int>(groups.size()), 3, "only consecutive slides group");

    // No provenance: every slide alone, whatever the (absent) block numbers say.
    groups = refract::groupSlides({{"", -1}, {"", -1}, {"", -1}});
    checkEq(static_cast<int>(groups.size()), 3, "slides without provenance never group");

    checkEq(static_cast<int>(refract::groupSlides({}).size()), 0, "empty deck, no groups");
}

static void testGroupOfSlide() {
    auto groups = refract::groupSlides(expandedDeck());
    auto of = refract::groupOfSlide(groups, 5);
    checkEq(static_cast<int>(of.size()), 5, "one entry per slide");
    checkEq(of[0], 0, "slide 0 in group 0");
    checkEq(of[1], 1, "slide 1 in group 1");
    checkEq(of[2], 1, "slide 2 in the same group");
    checkEq(of[3], 1, "slide 3 in the same group");
    checkEq(of[4], 2, "slide 4 in group 2");

    // A count that disagrees with the groups must not read or write past the end.
    auto shortOf = refract::groupOfSlide(groups, 2);
    checkEq(static_cast<int>(shortOf.size()), 2, "clamped to the slide count");
    checkEq(refract::groupOfSlide(groups, 0).empty() ? 1 : 0, 1, "zero slides, no entries");
}

// Move the group at `from` to insertion point `drop`, and report the deck positions.
struct Planned { bool ok; int from; int to; std::string why; };

static Planned plan(const std::vector<SlideGroup>& groups, int from, int drop) {
    Planned p{false, -1, -1, ""};
    p.ok = refract::planMove(groups, from, drop, &p.from, &p.to, &p.why);
    return p;
}

static void testSimpleMoves() {
    auto groups = refract::groupSlides(simpleDeck());

    // Backwards: dropping before group 0 takes group 0's place.
    Planned p = plan(groups, 2, 0);
    CHECK(p.ok, "last slide can move to the front");
    checkEq(p.from, 2, "moves the dragged slide");
    checkEq(p.to, 0, "onto the first slide's position");

    // Forwards: dropping past the end lands on the last group, because removing the
    // dragged one first shifts everything after it down.
    p = plan(groups, 0, 3);
    CHECK(p.ok, "first slide can move to the end");
    checkEq(p.from, 0, "moves the first slide");
    checkEq(p.to, 2, "onto the last slide's position, not past it");

    // One step forwards.
    p = plan(groups, 0, 2);
    CHECK(p.ok, "one step forwards is a move");
    checkEq(p.to, 1, "lands on the group it stepped over");

    // One step backwards.
    p = plan(groups, 2, 1);
    CHECK(p.ok, "one step backwards is a move");
    checkEq(p.to, 1, "takes that group's position");
}

static void testNoOpDrops() {
    auto groups = refract::groupSlides(simpleDeck());
    for (int g = 0; g < 3; g++) {
        // Dropping on either side of itself changes nothing, and is not an error: a drag
        // that ends where it started should be silent, not reported as a refusal.
        Planned before = plan(groups, g, g);
        CHECK(!before.ok && before.why.empty(), "dropping before itself is a silent no-op");
        Planned after = plan(groups, g, g + 1);
        CHECK(!after.ok && after.why.empty(), "dropping after itself is a silent no-op");
    }
}

static void testExpandedSlidesMoveTogether() {
    auto groups = refract::groupSlides(expandedDeck());

    // Whichever step of the fragment sequence was grabbed, the move is described by the
    // group's first slide — the tool moves the whole block from there.
    Planned p = plan(groups, 1, 0);
    CHECK(p.ok, "an expanded block can move");
    checkEq(p.from, 1, "always reported from the block's first slide");
    checkEq(p.to, 0, "onto the first block");

    // Moving to the end skips the whole block, not one of its steps.
    p = plan(groups, 1, 3);
    CHECK(p.ok, "an expanded block can move to the end");
    checkEq(p.to, 4, "lands on the last block's first slide");

    // And the blocks either side of it move across the whole run.
    p = plan(groups, 0, 3);
    CHECK(p.ok, "moving past an expanded block is one step, not three");
    checkEq(p.to, 4, "clears the whole expanded block");
}

static void testCrossFileIsRefused() {
    auto groups = refract::groupSlides(includingDeck());

    Planned p = plan(groups, 0, 2);   // parent slide dropped inside the included deck
    CHECK(!p.ok, "a slide cannot move into another file");
    CHECK(!p.why.empty(), "and says why");

    p = plan(groups, 1, 0);           // included slide dragged out into the parent
    CHECK(!p.ok, "an included slide cannot move into the parent");
    CHECK(!p.why.empty(), "and says why");

    // Inside the included deck it is a perfectly ordinary move.
    p = plan(groups, 2, 1);
    CHECK(p.ok, "slides can be reordered within the deck they are written in");
    checkEq(p.from, 2, "from the included slide");
    checkEq(p.to, 1, "onto its sibling");
}

static void testUnorderableDeck() {
    auto groups = refract::groupSlides({{"", -1}, {"", -1}, {"", -1}});
    Planned p = plan(groups, 0, 2);
    CHECK(!p.ok, "a deck without provenance cannot be reordered");
    CHECK(!p.why.empty(), "and says so rather than failing silently");
}

static void testOutOfRange() {
    auto groups = refract::groupSlides(simpleDeck());
    const int bad[][2] = {{-1, 0}, {3, 0}, {0, -1}, {0, 4}, {99, 99}};
    for (const auto& pair : bad) {
        Planned p = plan(groups, pair[0], pair[1]);
        CHECK(!p.ok, "out-of-range move refused");
        CHECK(!p.why.empty(), "out-of-range move explained");
    }
    // The one past-the-end insertion point that *is* valid.
    CHECK(plan(groups, 0, 3).ok, "dropping at the very end is in range");

    Planned p = plan({}, 0, 0);
    CHECK(!p.ok, "an empty deck has nothing to move");
}

// Every move has an inverse: putting a block back where it came from restores the order.
// Simulated here on the group list, which is what the markdown rewrite does to the file.
static void testMovesAreInvertible() {
    const int n = 5;
    for (int from = 0; from < n; from++) {
        for (int drop = 0; drop <= n; drop++) {
            std::vector<SlideSource> sources;
            for (int i = 0; i < n; i++) sources.push_back({"slides.md", i});
            auto groups = refract::groupSlides(sources);

            Planned p = plan(groups, from, drop);
            if (!p.ok) continue;
            const int landing = drop > from ? drop - 1 : drop;

            // Apply the move to the order, the way move_chunk does to the chunks.
            std::vector<int> order;
            for (int i = 0; i < n; i++) order.push_back(i);
            const int moved = order[from];
            order.erase(order.begin() + from);
            order.insert(order.begin() + landing, moved);
            checkEq(order[landing], moved, "the block ends up where the plan said");

            // Move it back: from its landing position, onto where it started.
            std::vector<int> back = order;
            const int again = back[landing];
            back.erase(back.begin() + landing);
            back.insert(back.begin() + from, again);
            for (int i = 0; i < n; i++) checkEq(back[i], i, "moving back restores the order");
        }
    }
}

static void testSourceRuns() {
    auto runs = refract::sourceRuns(refract::groupSlides(simpleDeck()));
    checkEq(static_cast<int>(runs.size()), 1, "one file, one run");
    CHECK(!runs[0].included, "the deck's own file is not an include");
    checkEq(runs[0].firstGroup, 0, "run starts at the first group");
    checkEq(runs[0].lastGroup, 2, "run ends at the last group");

    runs = refract::sourceRuns(refract::groupSlides(includingDeck()));
    checkEq(static_cast<int>(runs.size()), 3, "parent, include, parent");
    CHECK(!runs[0].included, "the first run is the deck's own");
    CHECK(runs[1].included, "the middle run came from an include");
    CHECK(!runs[2].included, "and the deck resumes after it");
    checkEq(runs[1].firstGroup, 1, "the include starts where its first slide is");
    checkEq(runs[1].lastGroup, 2, "and covers both of its slides");

    // The same sub-deck included twice is two runs, not one — they are in different places
    // and a slide cannot jump between them.
    runs = refract::sourceRuns(refract::groupSlides({
        {"includes/sub/slides.md", 0}, {"slides.md", 0}, {"includes/sub/slides.md", 0}}));
    checkEq(static_cast<int>(runs.size()), 3, "a repeated include is separate runs");

    checkEq(static_cast<int>(refract::sourceRuns({}).size()), 0, "no groups, no runs");
}

static void testIncludeName() {
    CHECK(refract::includeName("slides.md").empty(), "the deck's own file has no name to show");
    CHECK(refract::includeName("includes/intro/slides.md") == "intro", "names the sub-deck");
    CHECK(refract::includeName("includes/a/b/slides.md") == "b", "names the innermost folder");
    CHECK(refract::includeName("").empty(), "an empty path has no name");
}

static void testSnapDrop() {
    auto groups = refract::groupSlides(includingDeck());   // parent, include x2, parent
    // Groups: 0 slides.md, 1 sub, 2 sub, 3 slides.md.

    // A slide in a single-file deck is never snapped anywhere.
    auto plain = refract::groupSlides(simpleDeck());
    for (int drop = 0; drop <= 3; drop++) {
        checkEq(refract::snapDrop(plain, 1, drop), drop, "nothing to snap around");
    }

    // Dragging the parent's first slide over the sub-deck never enters it: the caret sits at
    // whichever end of the include the pointer is nearer, so the include reads as one thing
    // to go before or after rather than as somewhere to land in.
    checkEq(refract::snapDrop(groups, 0, 1), 1, "the near edge of the include");
    checkEq(refract::snapDrop(groups, 0, 2), 1, "still its near edge from just inside");
    checkEq(refract::snapDrop(groups, 0, 3), 4, "the far edge once past its middle");
    checkEq(refract::snapDrop(groups, 0, 4), 4, "and can land after it");
    checkEq(refract::snapDrop(groups, 0, 0), 0, "its own position needs no snapping");

    // The point a stricter, run-based rule would get wrong: the include splits the parent's
    // slides into two stretches, but they are the same file and may still move past each other.
    Planned p = plan(groups, 0, refract::snapDrop(groups, 0, 3));
    CHECK(p.ok, "a parent slide can move past an include");
    checkEq(p.to, 3, "onto the parent slide on the far side");

    // And from the other side of the include, back past it.
    checkEq(refract::snapDrop(groups, 3, 1), 0, "the far side reaches the deck's start");
    p = plan(groups, 3, refract::snapDrop(groups, 3, 1));
    CHECK(p.ok, "and that is a real move");
    checkEq(p.to, 0, "onto the first slide");

    // An included slide cannot leave its sub-deck, in either direction.
    checkEq(refract::snapDrop(groups, 1, 0), 1, "cannot go before the include");
    checkEq(refract::snapDrop(groups, 2, 4), 3, "cannot go after it");
    checkEq(refract::snapDrop(groups, 2, 1), 1, "but moves freely inside it");

    checkEq(refract::snapDrop(groups, 9, 0), -1, "no answer for a group that is not there");
    checkEq(refract::snapDrop({}, 0, 0), -1, "no answer in an empty deck");
}

// The caret and the refusal have to agree: every drop the view offers must be one planMove
// accepts (or a silent no-op), and a snapped drop must never be a refusal.
static void testSnappingNeverOffersARefusedMove() {
    for (const auto& sources : {includingDeck(), expandedDeck(), simpleDeck()}) {
        auto groups = refract::groupSlides(sources);
        const int total = static_cast<int>(groups.size());
        for (int from = 0; from < total; from++) {
            for (int wanted = -2; wanted <= total + 2; wanted++) {
                const int drop = refract::snapDrop(groups, from, wanted);
                CHECK(drop >= 0 && drop <= total, "a snapped drop is in range");
                Planned p = plan(groups, from, drop);
                CHECK(p.ok || p.why.empty(), "a snapped drop is a move or a silent no-op");
            }
        }
    }
}

// A deck shaped like the one the deck view has to draw: a title, a section holding three
// slides *and* an include, then a second section. Root blocks in slides.md are
//   0 title, 1 Part One, 2 Alpha, 3 Beta, 4 :: include, 5 Part Two, 6 Gamma, 7 Delta.
static std::vector<refract::SlideOrigin> sectionedDeck() {
    auto own = [](int chunk, int section, const char* title) {
        refract::SlideOrigin s;
        s.path = {{"slides.md", chunk}};
        s.sectionNumber = section;
        s.title = title;
        return s;
    };
    auto via = [](int parentChunk, int chunk, const char* title) {
        refract::SlideOrigin s;
        s.path = {{"slides.md", parentChunk}, {"includes/intro/slides.md", chunk}};
        s.title = title;
        return s;
    };
    return {own(0, 0, "The Deck"), own(1, 1, "Part One"), own(2, 0, "Alpha"),
            own(3, 0, "Beta"),     via(4, 0, "Sub One"),  via(4, 1, "Sub Two"),
            own(5, 2, "Part Two"), own(6, 0, "Gamma"),    own(7, 0, "Delta")};
}

static const refract::RunBar* findBar(const std::vector<refract::RunBar>& bars, bool included) {
    for (const auto& bar : bars) {
        if (bar.included == included) return &bar;
    }
    return nullptr;
}

static void testRunBars() {
    auto bars = refract::runBars(sectionedDeck());
    checkEq(static_cast<int>(bars.size()), 3, "one include bar and two section bars");

    const refract::RunBar* inc = findBar(bars, true);
    CHECK(inc != nullptr, "the include has a bar");
    checkEq(inc->firstSlide, 4, "covering its first slide");
    checkEq(inc->lastSlide, 5, "and its last");
    checkEq(inc->firstChunk, 4, "and moving the include line");
    checkEq(inc->lastChunk, 4, "which is a single block however many slides it makes");
    CHECK(inc->label == "intro", "named after the sub-deck");
    CHECK(inc->file == "slides.md", "the include line lives in the parent's markdown");

    // The first section runs to the slide before the next heading, and swallows the include
    // along the way — so its block range covers the include line too.
    const refract::RunBar* first = findBar(bars, false);
    CHECK(first != nullptr, "the first section has a bar");
    checkEq(first->firstSlide, 1, "starts at its heading");
    checkEq(first->lastSlide, 5, "and ends at the last slide under it");
    checkEq(first->firstChunk, 1, "block range starts at the heading's block");
    checkEq(first->lastChunk, 4, "and reaches the include it contains");
    CHECK(first->label == "1. Part One", "numbered and named");

    const refract::RunBar& second = bars.back();
    checkEq(second.firstSlide, 6, "the second section starts at its heading");
    checkEq(second.lastSlide, 8, "and runs to the end of the deck");
    checkEq(second.firstChunk, 5, "over its own blocks");
    checkEq(second.lastChunk, 7, "to the last one");
}

static void testRunBarsEdgeCases() {
    // No provenance: nothing can be lifted.
    refract::SlideOrigin bare;
    bare.sectionNumber = 1;
    checkEq(static_cast<int>(refract::runBars({bare, bare}).size()), 0, "no path, no bars");
    checkEq(static_cast<int>(refract::runBars({}).size()), 0, "no slides, no bars");

    // A section covering the whole deck has nowhere to go, so it gets no handle.
    refract::SlideOrigin head, body;
    head.path = {{"slides.md", 0}};
    head.sectionNumber = 1;
    head.title = "Only";
    body.path = {{"slides.md", 1}};
    checkEq(static_cast<int>(refract::runBars({head, body}).size()), 0,
            "a section that is the whole deck gets no bar");

    // Two includes in a row are two bars, not one: different include lines.
    refract::SlideOrigin a, b;
    a.path = {{"slides.md", 0}, {"includes/one/slides.md", 0}};
    b.path = {{"slides.md", 1}, {"includes/two/slides.md", 0}};
    auto bars = refract::runBars({a, b});
    checkEq(static_cast<int>(bars.size()), 2, "adjacent includes stay separate");
    CHECK(bars[0].label == "one" && bars[1].label == "two", "each named for its own sub-deck");
}

static void testPlanRunDrop() {
    auto bars = refract::runBars(sectionedDeck());
    const refract::RunBar& section = *findBar(bars, false);   // blocks 1..4, size 4

    // Before the deck's first block.
    checkEq(refract::planRunDrop(section, 0, /*after=*/false), 0, "to the very front");
    // Dropping after block 0 is exactly where it already is.
    checkEq(refract::planRunDrop(section, 0, true), -1, "already there, so nothing to do");
    // Anywhere inside its own span is a shrug, not an error.
    for (int chunk = 1; chunk <= 4; chunk++) {
        checkEq(refract::planRunDrop(section, chunk, false), -1, "dropped on itself");
        checkEq(refract::planRunDrop(section, chunk, true), -1, "dropped on itself");
    }
    // Past it: the gap the run leaves closes behind it, so the destination shifts by its size.
    checkEq(refract::planRunDrop(section, 5, true), 2, "after block 5 lands at 2");
    checkEq(refract::planRunDrop(section, 7, true), 4, "after the last block lands at the end");
    checkEq(refract::planRunDrop(section, 5, false), -1, "before block 5 is still adjacent");

    const refract::RunBar& inc = *findBar(bars, true);        // block 4..4, size 1
    checkEq(refract::planRunDrop(inc, 0, false), 0, "an include moves to the front");
    checkEq(refract::planRunDrop(inc, 7, true), 7, "or to the end");
    checkEq(refract::planRunDrop(inc, 4, false), -1, "or nowhere, on itself");
    checkEq(refract::planRunDrop(inc, -5, false), 0, "a pointer off the left edge clamps");
}

// Folding turns a run into one tile. These check the tiling, which is what keeps the grid a
// grid whatever is folded — and the swallowing rule, which is what stops a folded include
// inside a folded section from being drawn twice.
static std::vector<char> foldNone(size_t n) { return std::vector<char>(n, 0); }

static void testLayoutCellsUnfolded() {
    auto bars = refract::runBars(sectionedDeck());
    auto cells = refract::layoutCells(9, bars, foldNone(bars.size()));
    checkEq(static_cast<int>(cells.size()), 9, "nothing folded, one tile per slide");
    for (int i = 0; i < 9; i++) {
        checkEq(cells[i].firstSlide, i, "tile holds its own slide");
        checkEq(cells[i].lastSlide, i, "and only that one");
        CHECK(!cells[i].folded(), "and is not a folded run");
    }
}

static void testLayoutCellsFoldedInclude() {
    auto bars = refract::runBars(sectionedDeck());
    auto folded = foldNone(bars.size());
    int inc = -1;
    for (size_t b = 0; b < bars.size(); b++) {
        if (bars[b].included) inc = static_cast<int>(b);
    }
    folded[inc] = 1;

    auto cells = refract::layoutCells(9, bars, folded);
    // Slides 4 and 5 become one tile; the other seven are unchanged.
    checkEq(static_cast<int>(cells.size()), 8, "the sub-deck collapsed to one tile");
    checkEq(cells[4].firstSlide, 4, "the tile starts at the include's first slide");
    checkEq(cells[4].lastSlide, 5, "and covers its last");
    checkEq(cells[4].bar, inc, "and names the run it stands for");
    checkEq(cells[4].slides(), 2, "counting both");
    checkEq(cells[5].firstSlide, 6, "the deck resumes after it");
    CHECK(!cells[5].folded(), "with ordinary slides");
}

static void testLayoutCellsFoldedSection() {
    auto bars = refract::runBars(sectionedDeck());
    auto folded = foldNone(bars.size());
    for (size_t b = 0; b < bars.size(); b++) {
        if (!bars[b].included && bars[b].firstSlide == 1) folded[b] = 1;
    }
    auto cells = refract::layoutCells(9, bars, folded);
    // The title, the folded section (slides 1..5), then Part Two's three slides.
    checkEq(static_cast<int>(cells.size()), 5, "the section collapsed to one tile");
    checkEq(cells[1].firstSlide, 1, "starting at its heading");
    checkEq(cells[1].lastSlide, 5, "and reaching the include it contains");
    checkEq(cells[1].slides(), 5, "five slides behind one tile");
}

static void testAFoldedSectionSwallowsAFoldedInclude() {
    auto bars = refract::runBars(sectionedDeck());
    std::vector<char> folded(bars.size(), 1);      // everything folded
    auto cells = refract::layoutCells(9, bars, folded);
    // The title, section one (which contains the include), section two. The include gets no
    // tile of its own — it is inside the section that swallowed it.
    checkEq(static_cast<int>(cells.size()), 3, "one tile per top-level run");
    checkEq(cells[0].firstSlide, 0, "the title stands alone");
    CHECK(!cells[0].folded(), "and is not a run");
    checkEq(cells[1].firstSlide, 1, "then the first section");
    checkEq(cells[1].lastSlide, 5, "including the sub-deck inside it");
    checkEq(cells[2].firstSlide, 6, "then the second");
    checkEq(cells[2].lastSlide, 8, "to the end");
}

static void testLayoutCellsEdgeCases() {
    auto bars = refract::runBars(sectionedDeck());
    checkEq(static_cast<int>(refract::layoutCells(0, bars, foldNone(bars.size())).size()), 0,
            "no slides, no tiles");
    // A folded flag list shorter than the bars (a stale frame) folds nothing rather than
    // reading past the end.
    checkEq(static_cast<int>(refract::layoutCells(9, bars, {}).size()), 9,
            "no fold flags, nothing folded");
    checkEq(static_cast<int>(refract::layoutCells(9, {}, {}).size()), 9, "no bars, no folds");

    // Every tiling covers every slide exactly once, whatever is folded.
    for (unsigned mask = 0; mask < (1u << bars.size()); mask++) {
        std::vector<char> folded(bars.size(), 0);
        for (size_t b = 0; b < bars.size(); b++) folded[b] = (mask >> b) & 1;
        auto cells = refract::layoutCells(9, bars, folded);
        int expect = 0;
        for (const auto& cell : cells) {
            checkEq(cell.firstSlide, expect, "tiles are contiguous and in order");
            CHECK(cell.lastSlide >= cell.firstSlide, "and never empty");
            expect = cell.lastSlide + 1;
        }
        checkEq(expect, 9, "and together cover the whole deck");
    }
}

int main() {
    testGrouping();
    testGroupOfSlide();
    testSimpleMoves();
    testNoOpDrops();
    testExpandedSlidesMoveTogether();
    testCrossFileIsRefused();
    testUnorderableDeck();
    testOutOfRange();
    testMovesAreInvertible();
    testSourceRuns();
    testIncludeName();
    testSnapDrop();
    testSnappingNeverOffersARefusedMove();
    testRunBars();
    testRunBarsEdgeCases();
    testPlanRunDrop();
    testLayoutCellsUnfolded();
    testLayoutCellsFoldedInclude();
    testLayoutCellsFoldedSection();
    testAFoldedSectionSwallowsAFoldedInclude();
    testLayoutCellsEdgeCases();

    if (failures == 0) std::fprintf(stderr, "deck_order_test: all checks passed\n");
    else std::fprintf(stderr, "deck_order_test: %d failure(s)\n", failures);
    return failures == 0 ? 0 : 1;
}
