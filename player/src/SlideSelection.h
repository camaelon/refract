// Which slides an export takes: "3-12, 20", as typed into a panel or given as --slides.
//
// One rule for the PDF, the movie, the images and the web page, and one wording for what
// the deck view has selected — so the field an export panel opens with is exactly what the
// command line would take, and the other way round.
#pragma once

#include <string>
#include <vector>

namespace refract {

// The slides `spec` names, as 0-based indices in order without repeats: "3-12, 20" is
// slides 3 to 12 and 20, 1-based as the presenter shows them; "7-" runs to the end; empty
// or "all" is every slide. Out-of-range numbers are clamped to the deck. An unreadable
// spec gives an empty list and says why in `error`.
std::vector<int> parseSlideSelection(const std::string& spec, int count, std::string* error = nullptr);

// The compact spelling of a set of 0-based slides, for a field: {2,3,4,8} is "3-5, 9".
// Empty for none.
std::string formatSlideSelection(const std::vector<int>& slides);

}  // namespace refract
