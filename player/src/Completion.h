// Offering a deck's assets while an include is being typed.
//
// Three questions, all of them string work: is the caret inside an unclosed `<`, which
// `includes/` would a name there resolve against, and which names match what has been typed.
// Kept out of the editor because each has an edge that is invisible until it is wrong — a
// `<` that is already closed, a slide that came from a sub-deck and names its own assets,
// a prefix that matches in the middle of a name rather than at the front.
#pragma once

#include <string>
#include <vector>

namespace refract {

// Where an include being typed starts, and what has been typed since.
struct Include {
    bool found = false;
    int  start = 0;          // the column of the `<` itself
    std::string prefix;      // between it and the caret
};

// The unclosed `<` the caret sits after on this line, if it sits after one. A `>` between it
// and the caret means that include is already finished, and nothing is being typed into it.
Include includeAt(const std::string& line, int col);

// The `includes/` directory a `<name>` written in `file` resolves against, relative to the
// deck. "slides.md" resolves against the deck's own; a slide spliced in from a sub-deck —
// "includes/intro/slides.md" — resolves against that sub-deck's, which is what makes an
// image of its own reachable by its bare name.
std::string includeBase(const std::string& file);

// Which of `names` match `prefix`, as indices, best first: what starts with it before what
// merely contains it, each keeping the order it came in. Case is ignored — the names are
// filenames, and remembering their capitalisation is the work this is meant to save. An
// empty prefix matches everything, which is the state right after the `<` is typed.
std::vector<int> matchNames(const std::vector<std::string>& names, const std::string& prefix);

// The names an asset list offers a file: those under its `includes/`, written the way that
// file would have to write them. Anything outside it cannot be named from there at all.
std::vector<std::string> namesUnder(const std::vector<std::string>& paths,
                                    const std::string& base);

}  // namespace refract
