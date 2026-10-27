// The talk as it was planned: how long each part is meant to take.
//
// A `:: section duration=12m` says what a part of the talk is worth. Add them up and the deck
// knows how long it is meant to run; lay them along the deck and the presenter can show where
// the talk *should* be by now — the same ghost marker a rehearsal gives, on a deck that has
// never been rehearsed.
//
// The arithmetic is here, away from the window and the manifest, because it is where the
// judgement calls live: what a section with no duration is worth, and what to do with the
// slides before the first section.
#pragma once

#include <vector>

namespace refract {

// One planned part of the talk: where it starts in the deck, and how long it should take.
// A duration of 0 means the section said nothing about its length.
struct PlanSection {
    int firstSlide = 0;
    double duration = 0.0;
};

// The talk's planned length in seconds, or 0 when nothing was planned.
//
// A section with no `duration=` is worth the average of those that have one. It has to be
// worth *something* — given zero it would be instantaneous, and every section after it would
// read as late — and the average is the assumption that needs least explaining.
double plannedTotal(const std::vector<PlanSection>& sections);

// Where the plan says the talk should be at `elapsed`, as a fraction of the deck (0-1), or
// -1 when there is no plan to say.
//
// The first section's planned time starts at zero, so a title slide before it is part of that
// section's budget rather than a gap. Within a section the position is interpolated across
// its slides: a plan says how long a part takes, not how its slides divide the time.
float plannedFraction(const std::vector<PlanSection>& sections, int slides, double elapsed);

// Each section's place in the plan: when it is due to start (seconds from the top of the
// talk) and what it is worth — `timed` false when that is the average standing in for a
// section that said nothing. Empty when nothing was planned. For showing the plan, as the
// deck view does; the same budgets the pacing uses.
// Where each slide falls in the talk's *time*: `out[i]` is when slide i starts, `out[n]` when
// the talk ends (seconds, or relative units when nothing says how long anything takes).
// A slide takes `known[i]` when that is > 0 (its narration); otherwise its share of its
// part's planned budget — what is left once the part's narrated slides are counted, split
// evenly, never less than a tenth of the part's average slide — and with no plan, the average
// of the known lengths (or 1, when nothing is known: then it is simply the slide count).
std::vector<double> slideTimeline(const std::vector<PlanSection>& sections, int slides,
                                  const std::vector<double>& known);

struct PlanSlot {
    double start = 0.0;
    double duration = 0.0;
    bool timed = false;
};
std::vector<PlanSlot> planSlots(const std::vector<PlanSection>& sections);

}  // namespace refract
