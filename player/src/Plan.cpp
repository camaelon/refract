#include "Plan.h"

#include <algorithm>

namespace refract {

namespace {

// What each section is worth, with the unplanned ones filled in. Empty when nothing was
// planned at all.
std::vector<double> budgets(const std::vector<PlanSection>& sections) {
    double stated = 0.0;
    int counted = 0;
    for (const PlanSection& section : sections) {
        if (section.duration > 0) {
            stated += section.duration;
            counted++;
        }
    }
    if (counted == 0) return {};
    const double average = stated / counted;
    std::vector<double> out;
    out.reserve(sections.size());
    for (const PlanSection& section : sections) {
        out.push_back(section.duration > 0 ? section.duration : average);
    }
    return out;
}

}  // namespace

double plannedTotal(const std::vector<PlanSection>& sections) {
    double total = 0.0;
    for (double budget : budgets(sections)) total += budget;
    return total;
}

float plannedFraction(const std::vector<PlanSection>& sections, int slides, double elapsed) {
    if (slides <= 0 || elapsed < 0) return -1.0f;
    const std::vector<double> budget = budgets(sections);
    if (budget.empty()) return -1.0f;

    double at = 0.0;
    for (size_t i = 0; i < sections.size(); i++) {
        // Where this section's slides begin and end. The first starts at the top of the
        // deck rather than at its own heading, so nothing before it falls outside the plan.
        const int from = i == 0 ? 0 : sections[i].firstSlide;
        const int to = i + 1 < sections.size() ? sections[i + 1].firstSlide : slides;
        if (elapsed < at + budget[i] || i + 1 == sections.size()) {
            const double through = budget[i] > 0
                                       ? std::min(1.0, (elapsed - at) / budget[i]) : 1.0;
            const double slide = from + through * std::max(0, to - from);
            return static_cast<float>(std::min(1.0, slide / slides));
        }
        at += budget[i];
    }
    return 1.0f;
}

}  // namespace refract
