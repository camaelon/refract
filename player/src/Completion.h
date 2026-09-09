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

// `<name>` names an asset; `<name | key=value … flag>` carries options for the embed it
// makes. Which of those the caret is in decides what there is to offer — the deck's files,
// the options that mean anything for *that* file, or one option's values.
enum class IncludeWant {
    None,     // the caret is not inside an unclosed `<`
    Name,     // before the `|`: which asset
    Option,   // after it: a key or a flag
    Value,    // after `key=`
};

struct Include {
    bool found = false;              // shorthand for want != None
    IncludeWant want = IncludeWant::None;
    int  start = 0;                  // the column of the `<`, or of the word being typed
    std::string prefix;              // what has been typed of the word
    std::string name;                // the asset named before the `|`, once past it
    std::string key;                 // for Value: the option before the `=`
};

// The unclosed `<` the caret sits inside on this line, if it sits inside one, and which of
// its three parts. A `>` between it and the caret means that include is already finished,
// and nothing is being typed into it.
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

// ── The `::` line ────────────────────────────────────────────────────
//
// `:: <type> [flags] [key=value…] [: params]`. Which of those three vocabularies is wanted
// depends on where the caret is, and the rules are small but not obvious: the first word is
// a type and later bare words are flags, a word with an `=` in it wants that key's values,
// and everything past a lone `:` is a sub-deck name or a speaker rather than vocabulary at
// all.
enum class MetaWant {
    None,    // not on a `::` line, or past the `:` where the words stop being vocabulary
    Type,    // the first word: what kind of slide this is
    Word,    // a later bare word: a flag, or the start of a key
    Value,   // after `key=`
};

struct MetaContext {
    MetaWant want = MetaWant::None;
    int start = 0;           // the column the word being typed starts at
    std::string prefix;      // what has been typed of it
    std::string key;         // for Value: the key before the `=`
};

// What the `::` line under the caret wants completed, if it wants anything.
MetaContext metaAt(const std::string& line, int col);

// The names an asset list offers a file: those under its `includes/`, written the way that
// file would have to write them. Anything outside it cannot be named from there at all.
std::vector<std::string> namesUnder(const std::vector<std::string>& paths,
                                    const std::string& base);

}  // namespace refract
