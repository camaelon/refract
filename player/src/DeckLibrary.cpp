#include "DeckLibrary.h"

#include <algorithm>
#include <cstdlib>
#include <filesystem>
#include <fstream>

namespace fs = std::filesystem;

namespace refract {

namespace {

constexpr size_t kMaxRecent = 8;

// One path per line. Not JSON: it is a list of paths, and a format with no dependency and no
// parser keeps the tests for it dependency-free too. (A path containing a newline would not
// survive, which is a path nobody has.)
fs::path listPath() {
    const char* home = std::getenv("HOME");
    if (!home || !*home) return {};
    const fs::path dir = fs::path(home) / ".config" / "refract";
    std::error_code ec;
    fs::create_directories(dir, ec);
    return dir / "recent";
}

// A deck to start from. Enough to show what the grammar looks like without being a tutorial
// somebody has to delete before they can think.
constexpr const char* kStarterDeck =
    ":: title\n"
    "# A new talk\n"
    "*subtitle*\n"
    "\n"
    "---\n"
    "\n"
    ":: section\n"
    "# First part\n"
    "\n"
    "---\n"
    "\n"
    "# A slide\n"
    "\n"
    "- something to say\n"
    "- something else\n"
    "\n"
    "???\n"
    "Speaker notes go after the ??? and are only ever seen by you.\n";

}  // namespace

std::string recentPath() { return listPath().string(); }

const char* starterDeck() { return kStarterDeck; }

std::vector<std::string> recentDecks() {
    std::vector<std::string> out;
    const fs::path path = listPath();
    if (path.empty()) return out;
    std::ifstream in(path);
    if (!in) return out;

    std::error_code ec;
    std::string line;
    while (std::getline(in, line)) {
        if (line.empty()) continue;
        // A deck that has been moved or deleted since is not offered: a list of things that
        // do not open is worse than a shorter list.
        if (fs::exists(fs::path(line) / "slides.md", ec)) out.push_back(line);
    }
    return out;
}

void rememberDeck(const std::string& deckDir) {
    if (deckDir.empty()) return;
    const fs::path path = listPath();
    if (path.empty()) return;

    std::error_code ec;
    const std::string full = fs::weakly_canonical(fs::path(deckDir), ec).string();
    if (ec || full.empty() || full.find('\n') != std::string::npos) return;

    std::vector<std::string> decks = recentDecks();
    decks.erase(std::remove(decks.begin(), decks.end(), full), decks.end());
    decks.insert(decks.begin(), full);
    if (decks.size() > kMaxRecent) decks.resize(kMaxRecent);

    std::ofstream out(path);
    if (!out) return;
    for (const std::string& deck : decks) out << deck << "\n";
}

bool createDeck(const std::string& path, std::string* error) {
    std::error_code ec;
    const fs::path deck(path);
    if (fs::exists(deck / "slides.md", ec)) {
        // Never over an existing deck: somebody pointing at the wrong folder should be told,
        // not have their talk replaced with a template.
        *error = "there is already a deck there";
        return false;
    }
    fs::create_directories(deck, ec);
    if (ec) {
        *error = "could not make " + path;
        return false;
    }
    std::ofstream out(deck / "slides.md");
    if (!out) {
        *error = "could not write slides.md";
        return false;
    }
    out << kStarterDeck;
    return true;
}

}  // namespace refract
