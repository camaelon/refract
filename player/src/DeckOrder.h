// The arithmetic behind reordering a deck, with no window attached to it.
//
// Two things happen between a slide being dragged and a markdown file being rewritten, and
// both are easy to get wrong by one:
//
//   * Slides are grouped. refract expands one `---`-separated block into several slides
//     (bullet fragments, scroll pages, staggered embeds); those move together or not at all.
//   * A drop is an *insertion point* — "before group 5" — while the reorder tool takes the
//     position the block should end up at. Removing the dragged block first closes the gap
//     behind it, so dropping later in the deck lands one place earlier than the insertion
//     point names.
//
// Both are pure functions of the deck's source provenance, so they live here and are tested
// directly rather than through a window.
#pragma once

#include <string>
#include <vector>

namespace refract {

// One step of a slide's provenance: a markdown file (relative to the deck) and a
// `---`-separated block within it.
struct SourceRef {
    std::string file;
    int index = -1;
};

// Where a slide was written: a markdown file (relative to the deck) and the `---`-separated
// block within it. An index below zero means the slide has no provenance — an older
// deck.json, a zip bundle, a directory of loose .rc files — and cannot be reordered.
struct SlideSource {
    std::string file;
    int index = -1;
};

// A run of consecutive slides that came from one block.
struct SlideGroup {
    int first = 0, last = 0;      // inclusive slide indices
    std::string file;
    int index = -1;               // the block within `file`
    int count() const { return last - first + 1; }
};

// Group consecutive slides that name the same block of the same file. Slides without
// provenance never join anything, so a deck that has none becomes one group per slide —
// browsable, and refused by planMove.
std::vector<SlideGroup> groupSlides(const std::vector<SlideSource>& slides);

// group index for each slide, sized to `slideCount`. Slides past the last group map to -1.
std::vector<int> groupOfSlide(const std::vector<SlideGroup>& groups, int slideCount);

// A stretch of consecutive groups written in one markdown file. An `:: include` splices a
// sub-deck's slides in wholesale, and they arrive as a run of their own — which the deck view
// marks off, because a slide can only be reordered inside the file it is written in.
struct SourceRun {
    int firstGroup = 0, lastGroup = 0;   // inclusive
    std::string file;
    bool included = false;               // came from an `:: include`, not the deck's own file
};

std::vector<SourceRun> sourceRuns(const std::vector<SlideGroup>& groups);

// The name to show for an included run: "includes/intro/slides.md" reads as "intro". Empty
// for the deck's own file.
std::string includeName(const std::string& file);

// A slide's full provenance, outermost first: the chain of `:: include` lines that pulled it
// here, ending with the block it is actually written in. A slide of the deck's own markdown
// has a path of one. What the chain is *for* is that the two ends move different things —
// `back()` moves the slide inside the deck it belongs to, `front()` moves the whole thing
// inside the deck the reader is looking at.
struct SlideOrigin {
    std::vector<SourceRef> path;
    int sectionNumber = 0;      // >0 when this slide is itself a section heading
    std::string title;
};

// A stretch of slides that can be picked up and moved as one, and the bar drawn under them
// that does it. Two kinds, and they can overlap (an include inside a section):
//
//   * an included sub-deck — one `:: include` block of the deck that pulled it in;
//   * a section — the `:: section` slide and everything up to the next one, which is a
//     *range* of blocks rather than a single one.
//
// Both come out the same shape because both are a run of consecutive root-level blocks; a
// sub-deck's run just happens to be one block long however many slides it contributes.
struct RunBar {
    int firstSlide = 0, lastSlide = 0;   // inclusive, in deck order
    std::string label;
    // A name for the run that survives the deck being rebuilt and renumbered — a sub-deck's
    // path, or a section's title. Folding is remembered by this rather than by position,
    // since a reorder changes every position after it.
    std::string key;
    bool included = false;               // an include, rather than a section
    std::string file;                    // the markdown the blocks live in
    int firstChunk = 0, lastChunk = 0;   // inclusive block range within `file`
    int slides() const { return lastSlide - firstSlide + 1; }
    int chunks() const { return lastChunk - firstChunk + 1; }
};

// The bars a deck has, include bars first. Slides without provenance contribute none.
std::vector<RunBar> runBars(const std::vector<SlideOrigin>& slides);

// One tile of the grid: an ordinary slide, or a folded run standing in for several.
struct DeckCell {
    int firstSlide = 0, lastSlide = 0;   // inclusive; equal for an ordinary slide
    int bar = -1;                        // the run this cell stands for, or -1
    int slides() const { return lastSlide - firstSlide + 1; }
    bool folded() const { return bar >= 0; }
};

// The tiles to lay out, given which runs are folded (`folded[i]` for `bars[i]`).
//
// A folded run becomes one tile, swallowing anything inside it — a folded include inside a
// folded section is simply part of the section, not a tile of its own. Where two folded runs
// start at the same slide the wider one wins, which is what makes an outer section absorb an
// inner include rather than the other way round.
std::vector<DeckCell> layoutCells(int slideCount, const std::vector<RunBar>& bars,
                                  const std::vector<char>& folded);

// Where a run should land, as the destination index `move_chunks` takes — the position its
// first block ends up at once the run has been lifted out.
//
// `atChunk` is the block under the pointer and `after` says which side of it. Returns -1 when
// there is nothing to do, which includes every drop inside the run's own span: a section
// dropped back on itself is not an error, it is a shrug.
int planRunDrop(const RunBar& bar, int atChunk, bool after);

// The nearest insertion point to `wanted` that `fromGroup` may legally take.
//
// A slide can only move within the file it is written in, so the caret never enters an
// included sub-deck from outside it and never leaves one from inside — rather than following
// the pointer and refusing the drop afterwards. Note that this is *not* a range: an include
// splits the parent deck's slides into two stretches, and a parent slide may still move from
// one to the other, straight past the sub-deck sitting between them.
//
// Returns `wanted` when it is already legal. There is always at least one legal answer (the
// group's own position), so this only returns -1 for a group that does not exist.
int snapDrop(const std::vector<SlideGroup>& groups, int fromGroup, int wanted);

// The move a drop describes: take the group at `fromGroup` and put it before group `drop`
// (`drop == groups.size()` means "at the end").
//
// `outFrom` / `outTo` come back as *deck positions* — the first slide of the group that
// moves, and the first slide of the group it should take the place of — which is what the
// reorder tool takes. False when there is nothing to do or the move is not allowed, with
// `why` set (empty when the move was simply a no-op).
bool planMove(const std::vector<SlideGroup>& groups, int fromGroup, int drop,
              int* outFrom, int* outTo, std::string* why);

}  // namespace refract
