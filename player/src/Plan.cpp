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

std::vector<double> slideTimeline(const std::vector<PlanSection>& sections, int slides,
                                  const std::vector<double>& known) {
    std::vector<double> out(std::max(0, slides) + 1, 0.0);
    if (slides <= 0) return out;
    auto knownAt = [&](int i) { return i < static_cast<int>(known.size()) && known[i] > 0 ? known[i] : 0.0; };
    std::vector<double> len(slides, 0.0);
    const std::vector<double> budget = budgets(sections);
    if (!budget.empty()) {
        for (size_t k = 0; k < sections.size(); k++) {
            // The part's slides; the first part starts at the top of the deck (as plannedFraction).
            const int from = k == 0 ? 0 : std::clamp(sections[k].firstSlide, 0, slides);
            const int to = k + 1 < sections.size() ? std::clamp(sections[k + 1].firstSlide, from, slides) : slides;
            if (to <= from) continue;
            double voiced = 0.0;
            int unknown = 0;
            for (int i = from; i < to; i++) {
                if (knownAt(i) > 0) voiced += knownAt(i); else unknown++;
            }
            const double floor = 0.1 * budget[k] / (to - from);
            const double each = unknown > 0 ? std::max(floor, (budget[k] - voiced) / unknown) : 0.0;
            for (int i = from; i < to; i++) len[i] = knownAt(i) > 0 ? knownAt(i) : each;
        }
    } else {
        double sum = 0.0;
        int count = 0;
        for (int i = 0; i < slides; i++) if (knownAt(i) > 0) { sum += knownAt(i); count++; }
        const double each = count > 0 ? sum / count : 1.0;
        for (int i = 0; i < slides; i++) len[i] = knownAt(i) > 0 ? knownAt(i) : each;
    }
    for (int i = 0; i < slides; i++) out[i + 1] = out[i] + len[i];
    return out;
}

std::vector<PlanSlot> planSlots(const std::vector<PlanSection>& sections) {
    const std::vector<double> budget = budgets(sections);
    std::vector<PlanSlot> out;
    if (budget.empty()) return out;
    double at = 0.0;
    for (size_t i = 0; i < sections.size(); i++) {
        out.push_back({at, budget[i], sections[i].duration > 0});
        at += budget[i];
    }
    return out;
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
