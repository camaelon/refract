#include "DeckOrder.h"

#include <algorithm>

namespace refract {

std::vector<SlideGroup> groupSlides(const std::vector<SlideSource>& slides) {
    std::vector<SlideGroup> groups;
    for (size_t i = 0; i < slides.size(); i++) {
        const SlideSource& s = slides[i];
        const bool joins = !groups.empty() && s.index >= 0
                           && groups.back().index == s.index
                           && groups.back().file == s.file;
        if (joins) groups.back().last = static_cast<int>(i);
        else groups.push_back({static_cast<int>(i), static_cast<int>(i), s.file, s.index});
    }
    return groups;
}

std::vector<int> groupOfSlide(const std::vector<SlideGroup>& groups, int slideCount) {
    std::vector<int> of(slideCount < 0 ? 0 : slideCount, -1);
    for (size_t gi = 0; gi < groups.size(); gi++) {
        for (int s = groups[gi].first; s <= groups[gi].last; s++) {
            if (s >= 0 && s < slideCount) of[s] = static_cast<int>(gi);
        }
    }
    return of;
}

std::vector<SourceRun> sourceRuns(const std::vector<SlideGroup>& groups) {
    std::vector<SourceRun> runs;
    for (size_t gi = 0; gi < groups.size(); gi++) {
        if (!runs.empty() && runs.back().file == groups[gi].file) {
            runs.back().lastGroup = static_cast<int>(gi);
            continue;
        }
        SourceRun run;
        run.firstGroup = run.lastGroup = static_cast<int>(gi);
        run.file = groups[gi].file;
        // refract writes a slide's source relative to the deck, so the deck's own file is
        // "slides.md" and everything an include pulled in is under a directory. That one
        // separator is the whole test.
        run.included = run.file.find('/') != std::string::npos;
        runs.push_back(run);
    }
    return runs;
}

std::string includeName(const std::string& file) {
    const size_t slash = file.rfind('/');
    if (slash == std::string::npos) return {};
    // The directory the sub-deck lives in, not the file: every one of them is "slides.md".
    const std::string dir = file.substr(0, slash);
    const size_t parent = dir.rfind('/');
    return parent == std::string::npos ? dir : dir.substr(parent + 1);
}

namespace {

// The block a slide occupies in the deck the *reader* is looking at: its own, or — for a
// slide an include spliced in — the include line that brought it here.
const SourceRef* rootRef(const SlideOrigin& slide) {
    return slide.path.empty() ? nullptr : &slide.path.front();
}

bool sameRef(const SourceRef& a, const SourceRef& b) {
    return a.index == b.index && a.file == b.file;
}

}  // namespace

std::vector<RunBar> runBars(const std::vector<SlideOrigin>& slides) {
    std::vector<RunBar> bars;
    const int n = static_cast<int>(slides.size());

    // Included sub-decks: consecutive slides that arrived through the same include line.
    for (int i = 0; i < n;) {
        if (slides[i].path.size() < 2) { i++; continue; }
        const SourceRef via = slides[i].path.front();
        int j = i;
        while (j + 1 < n && slides[j + 1].path.size() >= 2
               && sameRef(slides[j + 1].path.front(), via)) {
            j++;
        }
        RunBar bar;
        bar.firstSlide = i;
        bar.lastSlide = j;
        bar.included = true;
        bar.file = via.file;
        bar.firstChunk = bar.lastChunk = via.index;
        // Named after the sub-deck it came from, not the include line — "intro" is what the
        // author calls it, and the line itself is not on screen.
        bar.label = includeName(slides[i].path[1].file);
        bar.key = "inc:" + slides[i].path[1].file;
        bars.push_back(bar);
        i = j + 1;
    }

    // Sections: a heading and everything up to the next heading. Unlike an include this is a
    // run of *several* root blocks, which is the whole reason move_chunks exists.
    for (int i = 0; i < n; i++) {
        if (slides[i].sectionNumber <= 0) continue;
        int j = i;
        while (j + 1 < n && slides[j + 1].sectionNumber <= 0) j++;
        const SourceRef* head = rootRef(slides[i]);
        if (!head || head->index < 0) continue;

        RunBar bar;
        bar.firstSlide = i;
        bar.lastSlide = j;
        bar.included = false;
        bar.file = head->file;
        bar.firstChunk = bar.lastChunk = head->index;
        bool usable = true;
        for (int k = i; k <= j; k++) {
            const SourceRef* ref = rootRef(slides[k]);
            // Every slide under the heading has to sit in the same file at this level, or the
            // section is not one range of blocks and cannot be lifted out as one.
            if (!ref || ref->index < 0 || ref->file != bar.file) { usable = false; break; }
            bar.firstChunk = std::min(bar.firstChunk, ref->index);
            bar.lastChunk = std::max(bar.lastChunk, ref->index);
        }
        // A section that is the whole deck has nowhere to go.
        if (!usable || (i == 0 && j == n - 1)) continue;
        bar.label = std::to_string(slides[i].sectionNumber) + ". " + slides[i].title;
        // By title, not by number: reordering sections renumbers them, and a fold should
        // follow the section the reader folded rather than the position it was in.
        bar.key = "sec:" + slides[i].title;
        bars.push_back(bar);
    }
    return bars;
}

std::vector<DeckCell> layoutCells(int slideCount, const std::vector<RunBar>& bars,
                                  const std::vector<char>& folded) {
    std::vector<DeckCell> cells;
    for (int i = 0; i < slideCount;) {
        int widest = -1;
        for (size_t b = 0; b < bars.size(); b++) {
            if (b < folded.size() && !folded[b]) continue;
            if (b >= folded.size()) continue;
            if (bars[b].firstSlide != i) continue;
            if (widest < 0 || bars[b].lastSlide > bars[widest].lastSlide) {
                widest = static_cast<int>(b);
            }
        }
        if (widest >= 0) {
            const RunBar& bar = bars[widest];
            cells.push_back({bar.firstSlide, std::min(bar.lastSlide, slideCount - 1), widest});
            i = bar.lastSlide + 1;
        } else {
            cells.push_back({i, i, -1});
            i++;
        }
    }
    return cells;
}

int planRunDrop(const RunBar& bar, int atChunk, bool after) {
    int ins = atChunk + (after ? 1 : 0);
    if (ins < 0) ins = 0;
    // Anywhere within the run's own span means "leave it where it is".
    if (ins > bar.firstChunk && ins <= bar.lastChunk + 1) ins = bar.firstChunk;
    // Past the run, the gap it leaves closes behind it.
    const int dst = ins > bar.lastChunk ? ins - bar.chunks() : ins;
    return dst == bar.firstChunk ? -1 : dst;
}

namespace {

// Is `drop` a move this group can actually make? The same question planMove asks, minus the
// arithmetic — kept in one place so the caret and the refusal can never disagree.
bool legalDrop(const std::vector<SlideGroup>& groups, int fromGroup, int drop) {
    const int total = static_cast<int>(groups.size());
    if (drop < 0 || drop > total) return false;
    const int landing = drop > fromGroup ? drop - 1 : drop;
    if (landing < 0 || landing >= total) return false;
    return groups[landing].file == groups[fromGroup].file;
}

}  // namespace

int snapDrop(const std::vector<SlideGroup>& groups, int fromGroup, int wanted) {
    const int total = static_cast<int>(groups.size());
    if (fromGroup < 0 || fromGroup >= total) return -1;
    if (legalDrop(groups, fromGroup, wanted)) return wanted;
    // Outward from where the pointer is, forward first — dragging into a sub-deck then reads
    // as "past it" rather than as "back where you came from", which is the direction someone
    // crossing a sub-deck is usually headed.
    for (int step = 1; step <= total + 1; step++) {
        if (legalDrop(groups, fromGroup, wanted + step)) return wanted + step;
        if (legalDrop(groups, fromGroup, wanted - step)) return wanted - step;
    }
    return fromGroup;            // its own position is always legal
}

bool planMove(const std::vector<SlideGroup>& groups, int fromGroup, int drop,
              int* outFrom, int* outTo, std::string* why) {
    why->clear();
    const int total = static_cast<int>(groups.size());
    if (fromGroup < 0 || fromGroup >= total || drop < 0 || drop > total) {
        *why = "that slide cannot be moved there";
        return false;
    }
    // Dropping *after* the group being moved skips over it: the gap it leaves closes, so
    // the block lands one position earlier than the insertion point.
    const int landing = drop > fromGroup ? drop - 1 : drop;
    if (landing == fromGroup) return false;   // back where it started — not an error

    const SlideGroup& source = groups[fromGroup];
    const SlideGroup& target = groups[landing];
    if (source.index < 0 || target.index < 0) {
        *why = "this deck has no source information, so it cannot be reordered";
        return false;
    }
    if (source.file != target.file) {
        // An `:: include` pulls a sub-deck in wholesale; a slide written in one file cannot
        // be dragged into another. (Moving the include itself still moves all of them.)
        *why = "that slide is written in " + source.file + " and cannot move into "
               + target.file;
        return false;
    }
    *outFrom = source.first;
    *outTo = target.first;
    return true;
}

}  // namespace refract
