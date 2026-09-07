#include "Utf8.h"

namespace refract {

namespace {

// How many bytes follow the lead byte, or -1 when it is not a lead byte at all.
int trailing(unsigned char c) {
    if (c < 0x80) return 0;
    if ((c & 0xE0) == 0xC0) return 1;
    if ((c & 0xF0) == 0xE0) return 2;
    if ((c & 0xF8) == 0xF0) return 3;
    return -1;                            // a stray continuation, or 0xF8-0xFF
}

// Whether a whole code point starts at `i`.
bool wholeAt(const std::string& text, size_t i, int extra) {
    if (extra < 0 || i + extra >= text.size()) return false;
    for (int n = 1; n <= extra; n++) {
        if ((static_cast<unsigned char>(text[i + n]) & 0xC0) != 0x80) return false;
    }
    return true;
}

}  // namespace

bool validUtf8(const std::string& text) {
    for (size_t i = 0; i < text.size();) {
        const int extra = trailing(static_cast<unsigned char>(text[i]));
        if (!wholeAt(text, i, extra)) return false;
        i += extra + 1;
    }
    return true;
}

std::string displayable(const std::string& text) {
    if (validUtf8(text)) return text;
    std::string out;
    out.reserve(text.size());
    for (size_t i = 0; i < text.size();) {
        const int extra = trailing(static_cast<unsigned char>(text[i]));
        if (!wholeAt(text, i, extra)) {
            out += '?';
            i++;
            continue;
        }
        out.append(text, i, extra + 1);
        i += extra + 1;
    }
    return out;
}

std::string dropLastChar(const std::string& text) {
    if (text.empty()) return text;
    return text.substr(0, utf8Boundary(text, text.size() - 1));
}

size_t utf8Boundary(const std::string& text, size_t at) {
    if (at >= text.size()) return text.size();
    while (at > 0 && (static_cast<unsigned char>(text[at]) & 0xC0) == 0x80) at--;
    return at;
}

}  // namespace refract
