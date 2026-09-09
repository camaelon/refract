#include "Completion.h"

#include <cctype>

namespace refract {

namespace {

std::string fold(std::string text) {
    for (char& c : text) c = static_cast<char>(std::tolower(static_cast<unsigned char>(c)));
    return text;
}

}  // namespace

Include includeAt(const std::string& line, int col) {
    if (col < 0 || col > static_cast<int>(line.size())) return {};

    int open = -1;
    for (int i = col - 1; i >= 0; i--) {
        if (line[i] == '>') return {};          // that one is already closed
        if (line[i] == '<') { open = i; break; }
    }
    if (open < 0) return {};

    const std::string inner = line.substr(open + 1, col - open - 1);
    const size_t bar = inner.find('|');
    if (bar == std::string::npos) {
        // No options yet: everything typed so far is the name.
        Include out;
        out.found = true;
        out.want = IncludeWant::Name;
        out.start = open;
        out.prefix = inner;
        return out;
    }

    Include out;
    out.found = true;
    out.name = inner.substr(0, bar);
    // Trim the space either side of the bar off the name.
    while (!out.name.empty() && out.name.back() == ' ') out.name.pop_back();

    // The word the caret is in, back to the last space after the bar.
    const int optionsFrom = open + 1 + static_cast<int>(bar) + 1;
    int start = col;
    while (start > optionsFrom && line[start - 1] != ' ') start--;
    const std::string word = line.substr(start, col - start);

    const size_t equals = word.find('=');
    if (equals != std::string::npos) {
        out.want = IncludeWant::Value;
        out.key = word.substr(0, equals);
        out.prefix = word.substr(equals + 1);
        out.start = start + static_cast<int>(equals) + 1;
        // A quoted value is being typed, not chosen from a list — `title="Two Words"`.
        if (!out.prefix.empty() && (out.prefix[0] == '"' || out.prefix[0] == '\'')) {
            return {};
        }
        return out;
    }
    out.want = IncludeWant::Option;
    out.start = start;
    out.prefix = word;
    return out;
}

std::string includeBase(const std::string& file) {
    const size_t slash = file.rfind('/');
    return (slash == std::string::npos ? std::string() : file.substr(0, slash + 1))
           + "includes/";
}

std::vector<int> matchNames(const std::vector<std::string>& names, const std::string& prefix) {
    const std::string needle = fold(prefix);
    std::vector<int> starts, contains;
    for (size_t i = 0; i < names.size(); i++) {
        const std::string name = fold(names[i]);
        if (needle.empty() || name.rfind(needle, 0) == 0) {
            starts.push_back(static_cast<int>(i));
        } else if (name.find(needle) != std::string::npos) {
            contains.push_back(static_cast<int>(i));
        }
    }
    starts.insert(starts.end(), contains.begin(), contains.end());
    return starts;
}

MetaContext metaAt(const std::string& line, int col) {
    if (col < 0 || col > static_cast<int>(line.size())) return {};

    // The `::` must open the line — a `::` inside prose is not metadata.
    size_t at = 0;
    while (at < line.size() && (line[at] == ' ' || line[at] == '\t')) at++;
    if (line.compare(at, 2, "::") != 0) return {};
    const int bodyFrom = static_cast<int>(at) + 2;
    if (col < bodyFrom) return {};        // the caret is in the `::` itself

    // Past a lone `:` the line is params — a sub-deck's name, or a speaker. Not vocabulary.
    for (int i = bodyFrom; i < col; i++) {
        if (line[i] != ':') continue;
        // Part of `a:b` in a value or a ratio, rather than the separator, only when it is
        // hard up against something on both sides.
        const bool spacedBefore = i == bodyFrom || line[i - 1] == ' ';
        const bool spacedAfter = i + 1 >= static_cast<int>(line.size()) || line[i + 1] == ' ';
        if (spacedBefore || spacedAfter) return {};
    }

    // The word the caret is in: back to the last space.
    int start = col;
    while (start > bodyFrom && line[start - 1] != ' ') start--;
    const std::string word = line.substr(start, col - start);

    // `key=` — everything after the first `=` is that key's value.
    const size_t equals = word.find('=');
    if (equals != std::string::npos) {
        MetaContext out;
        out.want = MetaWant::Value;
        out.key = word.substr(0, equals);
        out.prefix = word.substr(equals + 1);
        out.start = start + static_cast<int>(equals) + 1;
        return out;
    }

    // The first word is the slide's type; anything after it is a flag or a key.
    bool first = true;
    for (int i = bodyFrom; i < start; i++) {
        if (line[i] != ' ') { first = false; break; }
    }
    MetaContext out;
    out.want = first ? MetaWant::Type : MetaWant::Word;
    out.start = start;
    out.prefix = word;
    return out;
}

std::vector<std::string> namesUnder(const std::vector<std::string>& paths,
                                    const std::string& base) {
    std::vector<std::string> names;
    for (const std::string& path : paths) {
        if (path.rfind(base, 0) == 0 && path.size() > base.size()) {
            names.push_back(path.substr(base.size()));
        }
    }
    return names;
}

}  // namespace refract
