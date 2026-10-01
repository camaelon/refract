#include "SlideMeta.h"

#include <cctype>
#include <sstream>
#include <vector>

namespace refract {

namespace {

// The slide's own `::` line: the first line of the block, when it has one. Returns the line
// number, or -1.
int metaLine(const std::vector<std::string>& lines) {
    for (size_t i = 0; i < lines.size(); i++) {
        const std::string& line = lines[i];
        size_t at = line.find_first_not_of(" \t");
        if (at == std::string::npos) continue;          // blank: keep looking
        return line.compare(at, 2, "::") == 0 ? static_cast<int>(i) : -1;
    }
    return -1;
}

std::vector<std::string> split(const std::string& text) {
    std::vector<std::string> out;
    std::string line;
    for (char c : text) {
        if (c == '\n') { out.push_back(line); line.clear(); }
        else if (c != '\r') line += c;
    }
    out.push_back(line);
    return out;
}

std::string join(const std::vector<std::string>& lines) {
    std::string out;
    for (size_t i = 0; i < lines.size(); i++) {
        if (i) out += "\n";
        out += lines[i];
    }
    return out;
}

// What is on a `::` line besides its type: the pieces to keep.
struct Kept {
    std::vector<std::string> words;     // flags, and a `[2:3]` ratio
    std::vector<std::string> values;    // key=value overrides
    std::string author;                 // @name
};

// Read a `::` line. `type` comes back as the first bare word, `params` as whatever followed
// the colon after it (the theme's name, for `as`), and everything else in `kept`.
void readMeta(const std::string& line, std::string* type, std::string* params, Kept* kept) {
    const size_t at = line.find("::");
    std::string rest = at == std::string::npos ? line : line.substr(at + 2);
    // The part after the type's colon is the type's own argument; it goes with the type.
    std::istringstream in(rest);
    std::string token;
    bool takenType = false;
    bool inParams = false;
    while (in >> token) {
        // What belongs to nobody in particular is picked out first, wherever it sits on the
        // line: an author, an override, a pane ratio. refract reads them the same way.
        if (!token.empty() && token[0] == '@') { kept->author = token; continue; }
        if (token.find('=') != std::string::npos) { kept->values.push_back(token); continue; }
        if (!token.empty() && token[0] == '[') { kept->words.push_back(token); continue; }
        if (token == ":") { inParams = true; continue; }
        if (inParams) {
            // `:: include : a name with spaces` — everything after the colon.
            if (!params->empty()) *params += " ";
            *params += token;
            continue;
        }
        const size_t colon = token.find(':');
        if (!takenType) {
            // `as: hero` is one token; so is `as:` with the name after it.
            if (colon != std::string::npos) {
                *type = token.substr(0, colon);
                *params = token.substr(colon + 1);
                if (params->empty()) inParams = true;
            } else {
                *type = token;
            }
            takenType = true;
            continue;
        }
        kept->words.push_back(token);
    }
}

std::string writeMeta(const std::string& type, const std::string& params, const Kept& kept) {
    std::string out = "::";
    if (!type.empty()) {
        out += " " + type;
        if (!params.empty()) out += ": " + params;
    }
    for (const std::string& word : kept.words) out += " " + word;
    for (const std::string& value : kept.values) out += " " + value;
    if (!kept.author.empty()) out += " " + kept.author;
    return out;
}

}  // namespace

std::string themeOf(const std::string& markdown) {
    const std::vector<std::string> lines = split(markdown);
    const int at = metaLine(lines);
    if (at < 0) return {};
    std::string type, params;
    Kept kept;
    readMeta(lines[static_cast<size_t>(at)], &type, &params, &kept);
    return type == "as" ? params : std::string();
}

std::string withTheme(const std::string& markdown, const std::string& name) {
    std::vector<std::string> lines = split(markdown);
    const int at = metaLine(lines);

    if (at < 0) {
        if (name.empty()) return markdown;      // no line, no theme: nothing to do
        lines.insert(lines.begin(), ":: as: " + name);
        return join(lines);
    }

    std::string type, params;
    Kept kept;
    readMeta(lines[static_cast<size_t>(at)], &type, &params, &kept);
    if (name.empty()) {
        // The theme goes. What was the type is gone with it — a slide without one is a
        // content slide — so the line stays only for what else is on it.
        if (type == "as") { type.clear(); params.clear(); }
        const std::string line = writeMeta(type, params, kept);
        if (line == "::") lines.erase(lines.begin() + at);
        else lines[static_cast<size_t>(at)] = line;
        return join(lines);
    }
    lines[static_cast<size_t>(at)] = writeMeta("as", name, kept);
    return join(lines);
}

}  // namespace refract
