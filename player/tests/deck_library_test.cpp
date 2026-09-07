// Starting a deck, and remembering the ones already opened.
//
// The first thing somebody sees, and the one place the player writes outside a deck. Both are
// small; both are the kind of small that is annoying when it is wrong.
//
// Returns 0 on success, 1 on any failed assertion.

#include "DeckLibrary.h"

#include <cstdio>
#include <cstdlib>
#include <filesystem>
#include <fstream>
#include <string>
#include <unistd.h>

namespace fs = std::filesystem;

static int failures = 0;

#define CHECK(cond, msg) do { \
    if (!(cond)) { std::fprintf(stderr, "FAIL: %s\n", msg); ++failures; } \
} while (0)

static fs::path scratch() {
    static int n = 0;
    fs::path dir = fs::temp_directory_path()
                   / ("refract_library_test_" + std::to_string(::getpid())
                      + "_" + std::to_string(n++));
    fs::remove_all(dir);
    fs::create_directories(dir);
    return dir;
}

// The list lives under $HOME, so a test gets its own.
static fs::path useOwnHome() {
    const fs::path home = scratch();
    ::setenv("HOME", home.c_str(), 1);
    return home;
}

static std::string read(const fs::path& path) {
    std::ifstream in(path);
    return {std::istreambuf_iterator<char>(in), std::istreambuf_iterator<char>()};
}

static void testCreateDeck() {
    const fs::path dir = scratch() / "talk";
    std::string error;
    CHECK(refract::createDeck(dir.string(), &error), "a deck is created");
    CHECK(fs::exists(dir / "slides.md"), "with a slides.md in it");
    CHECK(!read(dir / "slides.md").empty(), "and something in that");

    // Never over an existing deck: somebody pointing at the wrong folder should be told, not
    // have their talk replaced with a template.
    CHECK(!refract::createDeck(dir.string(), &error), "an existing deck is refused");
    CHECK(!error.empty(), "and says why");
}

static void testTheStarterDeckIsAValidDeck() {
    // Shipping a template that does not build would be a poor welcome. The full check is that
    // refract builds it, which the Python suite does; here it is the shape: separated blocks,
    // a title, and nothing that would make the parser blink.
    const std::string deck = refract::starterDeck();
    CHECK(deck.find("\n---\n") != std::string::npos, "it has more than one slide");
    CHECK(deck.find("# ") != std::string::npos, "and a heading");
    CHECK(deck.find(":: title") != std::string::npos, "and opens with a title slide");
    CHECK(deck.back() == '\n', "and ends with a newline");
    // A line starting with `#` inside body text does not build — see the note in chunks.py.
    // The template must not contain one, which means every `#` line is a slide's first.
    bool afterHeading = false;
    std::string line;
    for (size_t i = 0, start = 0; i <= deck.size(); i++) {
        if (i != deck.size() && deck[i] != '\n') continue;
        line = deck.substr(start, i - start);
        start = i + 1;
        if (line.rfind("---", 0) == 0) afterHeading = false;
        else if (line.rfind("# ", 0) == 0) {
            CHECK(!afterHeading, "no second heading inside one slide");
            afterHeading = true;
        }
    }
}

static void testRecentDecks() {
    useOwnHome();
    CHECK(refract::recentDecks().empty(), "nothing remembered on a first run");

    const fs::path a = scratch() / "one";
    const fs::path b = scratch() / "two";
    std::string error;
    refract::createDeck(a.string(), &error);
    refract::createDeck(b.string(), &error);

    refract::rememberDeck(a.string());
    refract::rememberDeck(b.string());
    auto recent = refract::recentDecks();
    CHECK(recent.size() == 2, "both are remembered");
    CHECK(!recent.empty() && fs::path(recent[0]).filename() == "two",
          "the most recent is first");

    // Opening one again moves it to the front rather than listing it twice.
    refract::rememberDeck(a.string());
    recent = refract::recentDecks();
    CHECK(recent.size() == 2, "no duplicate");
    CHECK(!recent.empty() && fs::path(recent[0]).filename() == "one", "and it is first again");
}

static void testADeckThatIsGoneIsNotOffered() {
    useOwnHome();
    const fs::path dir = scratch() / "gone";
    std::string error;
    refract::createDeck(dir.string(), &error);
    refract::rememberDeck(dir.string());
    CHECK(refract::recentDecks().size() == 1, "it is remembered");

    fs::remove_all(dir);
    CHECK(refract::recentDecks().empty(),
          "a deck that has been moved or deleted is not offered");
}

static void testTheListStaysShort() {
    useOwnHome();
    for (int i = 0; i < 20; i++) {
        const fs::path dir = scratch() / ("deck" + std::to_string(i));
        std::string error;
        refract::createDeck(dir.string(), &error);
        refract::rememberDeck(dir.string());
    }
    CHECK(refract::recentDecks().size() <= 8, "the list is capped");
    CHECK(!refract::recentDecks().empty()
          && refract::recentDecks()[0].find("deck19") != std::string::npos,
          "keeping the newest");
}

static void testAStaleListCostsTheListAndNothingElse() {
    const fs::path home = useOwnHome();
    fs::create_directories(home / ".config" / "refract");
    std::ofstream(home / ".config" / "refract" / "recent") << "/nowhere/at/all\n\n";
    CHECK(refract::recentDecks().empty(),
          "a list of decks that are not there reads as empty");

    const fs::path dir = scratch() / "after";
    std::string error;
    refract::createDeck(dir.string(), &error);
    refract::rememberDeck(dir.string());
    CHECK(refract::recentDecks().size() == 1, "and is written over");
}

int main() {
    testCreateDeck();
    testTheStarterDeckIsAValidDeck();
    testRecentDecks();
    testADeckThatIsGoneIsNotOffered();
    testTheListStaysShort();
    testAStaleListCostsTheListAndNothingElse();

    if (failures == 0) std::fprintf(stderr, "deck_library_test: all checks passed\n");
    else std::fprintf(stderr, "deck_library_test: %d failure(s)\n", failures);
    return failures == 0 ? 0 : 1;
}
