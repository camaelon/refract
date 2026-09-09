// What may be written on a `::` line.
//
// `:: <type> [flags] [key=value…] [: params]` — and the words that may appear in each place
// are refract's, not the player's. They come from refractkit's own vocabulary through
// tools/meta.py, so the editor cannot offer a word the build would not understand, and a
// word added to refract appears here without anybody editing this file.
#pragma once

#include <string>
#include <vector>

namespace refract {

struct MetaWord {
    std::string name;
    std::string doc;                  // one line saying what it is for
    std::vector<std::string> values;  // for a key with a closed set; empty otherwise
    // For an include option: the asset kinds it does anything for (empty means any), and
    // whether it is written `name=value` or as a bare word.
    std::vector<std::string> kinds;
    bool takesValue = true;

    bool appliesTo(const std::string& kind) const {
        if (kinds.empty()) return true;
        for (const std::string& one : kinds) {
            if (one == kind) return true;
        }
        return false;
    }
};

struct MetaVocabulary {
    std::vector<MetaWord> types;      // the first word: what kind of slide this is
    std::vector<MetaWord> flags;      // bare words after it
    std::vector<MetaWord> keys;       // `key=value` overrides
    // `<name | key=value … flag>` — what an embed can be told, and for which kinds of file.
    std::vector<MetaWord> includeOpts;

    bool empty() const { return types.empty() && flags.empty() && keys.empty(); }
};

}  // namespace refract
