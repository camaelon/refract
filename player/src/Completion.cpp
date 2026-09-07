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
    for (int i = col - 1; i >= 0; i--) {
        if (line[i] == '>') return {};          // that one is already closed
        if (line[i] == '<') {
            return {true, i, line.substr(i + 1, col - i - 1)};
        }
    }
    return {};
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
