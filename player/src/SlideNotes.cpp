#include "SlideNotes.h"

#include <cctype>
#include <vector>

namespace refract {

namespace {

std::vector<std::string> lines(const std::string& text) {
    std::vector<std::string> out;
    std::string line;
    for (char c : text) {
        if (c == '\n') { out.push_back(line); line.clear(); }
        else if (c != '\r') line += c;
    }
    out.push_back(line);
    return out;
}

std::string trimmed(const std::string& s) {
    size_t a = 0, b = s.size();
    while (a < b && std::isspace(static_cast<unsigned char>(s[a]))) a++;
    while (b > a && std::isspace(static_cast<unsigned char>(s[b - 1]))) b--;
    return s.substr(a, b - a);
}

// The line the notes begin on, and the text on that line after the marker. -1: no notes.
int notesStart(const std::vector<std::string>& ls, std::string* inline_out) {
    for (size_t i = 0; i < ls.size(); i++) {
        const std::string t = trimmed(ls[i]);
        if (t == "???") { if (inline_out) inline_out->clear(); return static_cast<int>(i); }
        if (t.rfind("??? ", 0) == 0) {
            if (inline_out) *inline_out = trimmed(t.substr(4));
            return static_cast<int>(i);
        }
    }
    return -1;
}

}  // namespace

std::string notesOf(const std::string& markdown) {
    const std::vector<std::string> ls = lines(markdown);
    std::string first;
    const int start = notesStart(ls, &first);
    if (start < 0) return {};
    std::string out = first;
    for (size_t i = static_cast<size_t>(start) + 1; i < ls.size(); i++) {
        if (!out.empty()) out += "\n";
        out += ls[i];
    }
    return trimmed(out);
}

std::string appendNotes(const std::string& existing, const std::string& addition) {
    const std::string a = trimmed(existing), b = trimmed(addition);
    if (a.empty()) return b;
    if (b.empty()) return a;
    return a + "\n\n" + b;
}

bool notesContain(const std::string& notes, const std::string& addition) {
    const std::string a = trimmed(addition);
    return !a.empty() && trimmed(notes).find(a) != std::string::npos;
}

std::string withNotes(const std::string& markdown, const std::string& notes) {
    const std::vector<std::string> ls = lines(markdown);
    const int start = notesStart(ls, nullptr);

    std::string body;
    const size_t upto = start < 0 ? ls.size() : static_cast<size_t>(start);
    for (size_t i = 0; i < upto; i++) {
        if (i) body += "\n";
        body += ls[i];
    }
    // Trailing blank lines belong to the join below, not to the slide.
    while (!body.empty() && std::isspace(static_cast<unsigned char>(body.back()))) body.pop_back();

    const std::string kept = trimmed(notes);
    if (kept.empty()) return body.empty() ? body : body + "\n";
    return (body.empty() ? std::string() : body + "\n\n") + "???\n\n" + kept + "\n";
}

std::string transcriptAsNotes(const std::string& transcript) {
    // One long line of words: whitespace collapsed, then broken after a sentence ends.
    std::string out;
    std::string word;
    bool lineEmpty = true;
    auto flush = [&](bool breakAfter) {
        if (word.empty()) return;
        if (!lineEmpty) out += " ";
        out += word;
        lineEmpty = false;
        // A break only after something that ends a sentence, and not after an initial or an
        // abbreviation — one letter before the stop is not the end of a sentence.
        if (breakAfter) {
            const char end = word[word.size() - 1];
            const bool stop = end == '.' || end == '?' || end == '!';
            const bool initial = word.size() <= 2 && end == '.';
            if (stop && !initial) { out += "\n"; lineEmpty = true; }
        }
        word.clear();
    };
    for (char c : transcript) {
        if (std::isspace(static_cast<unsigned char>(c))) flush(true);
        else word += c;
    }
    flush(false);
    return trimmed(out);
}

}  // namespace refract
