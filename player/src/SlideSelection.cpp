#include "SlideSelection.h"

#include <algorithm>
#include <cctype>
#include <set>

namespace refract {

namespace {

std::string trimmed(const std::string& s) {
    size_t a = 0, b = s.size();
    while (a < b && std::isspace(static_cast<unsigned char>(s[a]))) a++;
    while (b > a && std::isspace(static_cast<unsigned char>(s[b - 1]))) b--;
    return s.substr(a, b - a);
}

bool number(const std::string& s, int* out) {
    if (s.empty()) return false;
    for (char c : s) if (!std::isdigit(static_cast<unsigned char>(c))) return false;
    *out = std::atoi(s.c_str());
    return true;
}

}  // namespace

std::vector<int> parseSlideSelection(const std::string& spec, int count, std::string* error) {
    std::vector<int> out;
    if (error) error->clear();
    if (count <= 0) return out;
    const std::string whole = trimmed(spec);
    if (whole.empty() || whole == "all") {
        for (int i = 0; i < count; i++) out.push_back(i);
        return out;
    }
    std::set<int> chosen;
    size_t start = 0;
    while (start <= whole.size()) {
        const size_t comma = whole.find(',', start);
        const std::string tok = trimmed(whole.substr(start, comma == std::string::npos ? std::string::npos : comma - start));
        start = comma == std::string::npos ? whole.size() + 1 : comma + 1;
        if (tok.empty()) continue;
        int a = 0, b = 0;
        const size_t dash = tok.find('-');
        if (dash == std::string::npos) {
            if (!number(tok, &a)) { if (error) *error = "not a slide number: " + tok; return {}; }
            b = a;
        } else {
            const std::string lo = trimmed(tok.substr(0, dash)), hi = trimmed(tok.substr(dash + 1));
            if (!number(lo, &a)) { if (error) *error = "not a slide range: " + tok; return {}; }
            if (hi.empty()) b = count;
            else if (!number(hi, &b)) { if (error) *error = "not a slide range: " + tok; return {}; }
        }
        if (a < 1) a = 1;
        if (b > count) b = count;
        for (int i = a; i <= b; i++) chosen.insert(i - 1);
    }
    out.assign(chosen.begin(), chosen.end());
    if (out.empty() && error) *error = "no slides in " + whole;
    return out;
}

std::string formatSlideSelection(const std::vector<int>& slides) {
    std::vector<int> sorted(slides.begin(), slides.end());
    std::sort(sorted.begin(), sorted.end());
    sorted.erase(std::unique(sorted.begin(), sorted.end()), sorted.end());
    std::string out;
    for (size_t i = 0; i < sorted.size();) {
        size_t j = i;
        while (j + 1 < sorted.size() && sorted[j + 1] == sorted[j] + 1) j++;
        if (!out.empty()) out += ", ";
        out += std::to_string(sorted[i] + 1);
        if (j > i) out += "-" + std::to_string(sorted[j] + 1);
        i = j + 1;
    }
    return out;
}

}  // namespace refract
