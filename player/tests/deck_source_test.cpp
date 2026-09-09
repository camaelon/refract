// Reading a deck's own source through the tools.
//
// Everything the player knows about a deck's markdown comes back through here, and every
// answer arrives as JSON from a Python script that may have failed, printed nothing, or
// printed something else entirely. The checks below are about that seam rather than about
// the tools: a deck that cannot be edited, a slide that is not there, a file outside the
// deck, and the ordinary case where it all works.
//
// Writes are not exercised: they rebuild the deck, which is refract's job and is covered on
// the Python side. What is here is the part that used to be four copies of the same parse.
//
// Returns 0 on success, 1 on any failed assertion.

#include "DeckSource.h"

#include <cstdio>
#include <filesystem>
#include <fstream>
#include <string>
#include <unistd.h>

namespace fs = std::filesystem;

static int failures = 0;

#define CHECK(cond, msg) do { \
    if (!(cond)) { std::fprintf(stderr, "FAIL: %s\n", msg); ++failures; } \
} while (0)

static void write(const fs::path& path, const std::string& text) {
    fs::create_directories(path.parent_path());
    std::ofstream(path) << text;
}

// A deck as it is on disk: the markdown, an asset it uses, one it does not, and the deck.json
// the tools read to find their way back to the source. No build — nothing here needs the
// slides to have been compiled.
static fs::path makeDeck() {
    static int n = 0;
    const fs::path dir = fs::temp_directory_path()
                         / ("refract_source_test_" + std::to_string(::getpid())
                            + "_" + std::to_string(n++));
    fs::remove_all(dir);
    write(dir / "slides.md", "# One\n\n<kept.png>\n\n---\n\n# Two\n\nsecond slide\n");
    write(dir / "includes" / "kept.png", "\x89PNG\r\n\x1a\n");
    write(dir / "includes" / "orphan.png", "\x89PNG\r\n\x1a\n");
    // The provenance the tools work from: which block of which file each slide came out of.
    // A real deck.json carries far more, and none of the rest is read here.
    write(dir / "out" / "deck.json",
          "{\"deck\": \"" + dir.filename().string() + "\", \"source\": \"" + dir.string()
              + "\", \"slides\": ["
              "{\"src\": \"slides.md\", \"src_index\": 0},"
              "{\"src\": \"slides.md\", \"src_index\": 1}]}");
    return dir;
}

static void testNoDeck() {
    refract::DeckSource source;   // never pointed at anything — a zip bundle
    CHECK(!source.available(), "a source with no out dir has nothing to edit");
    CHECK(source.deckDir().empty(), "and no deck directory");

    std::string text, file, error;
    int shared = 0;
    CHECK(!source.readSlide(0, &text, &file, &shared, &error), "reading a slide fails");
    CHECK(!error.empty(), "and says why");
    error.clear();
    CHECK(!source.readFile("slides.md", &text, &error), "so does reading a file");
    CHECK(!error.empty(), "and says why");

    std::vector<refract::Asset> assets;
    std::string dir;
    error.clear();
    CHECK(!source.scanAssets(&assets, &dir, &error), "and so does scanning for assets");
    CHECK(!error.empty(), "and says why");
    std::string status;
    CHECK(!source.removeAsset("includes/x.png", true, &status), "and removing one");
}

static void testReadSlide() {
    const fs::path deck = makeDeck();
    refract::DeckSource source;
    source.setOutDir((deck / "out").string());
    CHECK(source.available(), "a deck with an out dir can be edited");
    CHECK(source.deckDir() == deck.string(), "the deck is the parent of out/");

    std::string text, file, error;
    int shared = -1;
    CHECK(source.readSlide(0, &text, &file, &shared, &error), "the first slide reads");
    CHECK(error.empty(), "with no error");
    CHECK(text.find("# One") != std::string::npos, "and is the first block");
    CHECK(text.find("# Two") == std::string::npos, "and only the first block");
    CHECK(file == "slides.md", "from the deck's own markdown");
    CHECK(shared >= 1, "and says how many slides the block makes");

    CHECK(source.readSlide(1, &text, &file, &shared, &error), "the second slide reads too");
    CHECK(text.find("second slide") != std::string::npos, "and is the second block");
    fs::remove_all(deck);
}

static void testReadSlideThatIsNotThere() {
    const fs::path deck = makeDeck();
    refract::DeckSource source;
    source.setOutDir((deck / "out").string());
    std::string text, file, error;
    int shared = 0;
    CHECK(!source.readSlide(99, &text, &file, &shared, &error), "slide 99 does not read");
    CHECK(!error.empty(), "and the tool's own words come back");
    fs::remove_all(deck);
}

static void testReadFile() {
    const fs::path deck = makeDeck();
    refract::DeckSource source;
    source.setOutDir((deck / "out").string());

    std::string text, error;
    CHECK(source.readFile("slides.md", &text, &error), "the whole markdown reads");
    CHECK(text.find("# One") != std::string::npos && text.find("# Two") != std::string::npos,
          "end to end, not one block");

    // The editor can open any file under the deck; anywhere else is not the deck's business.
    error.clear();
    CHECK(!source.readFile("../../etc/hosts", &text, &error), "a path out of the deck is refused");
    CHECK(!error.empty(), "and says so");
    fs::remove_all(deck);
}

static void testScanAssets() {
    const fs::path deck = makeDeck();
    refract::DeckSource source;
    source.setOutDir((deck / "out").string());

    std::vector<refract::Asset> assets;
    std::string dir, error;
    CHECK(source.scanAssets(&assets, &dir, &error), "the assets scan");
    CHECK(dir == deck.string(), "and come back with the deck they are in");
    CHECK(assets.size() == 2, "both files under includes/ are listed");

    const refract::Asset* kept = nullptr;
    const refract::Asset* orphan = nullptr;
    for (const auto& a : assets) {
        if (a.name == "kept.png") kept = &a;
        if (a.name == "orphan.png") orphan = &a;
    }
    CHECK(kept && orphan, "by name");
    if (kept) {
        CHECK(kept->used, "the one a slide names is used");
        CHECK(kept->slides.size() == 1 && kept->slides[0] == 1, "by slide 1");
        CHECK(kept->kind == "image", "and is an image");
        CHECK(kept->size > 0, "with a size");
    }
    if (orphan) {
        CHECK(!orphan->used && orphan->slides.empty(), "the one nothing names is not");
    }
    fs::remove_all(deck);
}

static void testRemoveAsset() {
    const fs::path deck = makeDeck();
    refract::DeckSource source;
    source.setOutDir((deck / "out").string());

    std::string status;
    CHECK(source.removeAsset("includes/orphan.png", /*force=*/false, &status),
          "an unused asset moves");
    CHECK(!fs::exists(deck / "includes" / "orphan.png"), "and is gone from includes/");
    CHECK(fs::exists(deck / "out" / ".trash" / "includes" / "orphan.png"),
          "and is in the trash, not deleted");
    CHECK(status.find("trash") != std::string::npos, "and the status says where it went");

    // Without force the tool refuses, and the reason names the slide.
    status.clear();
    CHECK(!source.removeAsset("includes/kept.png", /*force=*/false, &status),
          "one in use is refused");
    CHECK(status.find("slide") != std::string::npos, "saying which slide uses it");
    CHECK(fs::exists(deck / "includes" / "kept.png"), "and it is still there");

    CHECK(source.removeAsset("includes/kept.png", /*force=*/true, &status),
          "force moves it anyway");
    CHECK(!fs::exists(deck / "includes" / "kept.png"), "and it goes");

    status.clear();
    CHECK(!source.removeAsset("includes/never.png", true, &status),
          "one that is not there cannot be removed");
    CHECK(!status.empty(), "and says so");
    fs::remove_all(deck);
}

// The `::` vocabulary is refract's own and belongs to no deck — the editor asks for it
// before a deck is even open, and a zip bundle has one too.
static void testTheMetaVocabulary() {
    refract::DeckSource source;          // deliberately not pointed at anything
    refract::MetaVocabulary vocabulary;
    std::string error;
    CHECK(source.metaVocabulary(&vocabulary, &error), "the vocabulary reads with no deck");
    CHECK(error.empty(), "with no error");
    CHECK(!vocabulary.empty(), "and is not empty");

    auto has = [](const std::vector<refract::MetaWord>& words, const std::string& name) {
        for (const refract::MetaWord& word : words) {
            if (word.name == name) return true;
        }
        return false;
    };
    CHECK(has(vocabulary.types, "content"), "the default slide type is offered");
    CHECK(has(vocabulary.types, "section"), "and a section");
    CHECK(has(vocabulary.flags, "steps"), "a flag is offered");
    CHECK(has(vocabulary.keys, "transition"), "and a key");

    for (const refract::MetaWord& word : vocabulary.types) {
        CHECK(!word.doc.empty(), "every type says what it is for");
    }
    // A key with a closed set brings its values, which is what makes `transition=` worth
    // completing rather than just naming.
    for (const refract::MetaWord& word : vocabulary.keys) {
        if (word.name != "transition") continue;
        CHECK(word.values.size() >= 4, "transition offers its styles");
        bool push = false;
        for (const std::string& value : word.values) push = push || value == "push";
        CHECK(push, "including push");
    }
}

static void testNotADeck() {
    // An out directory with no deck.json in it: the tools should say so rather than crash.
    const fs::path dir = fs::temp_directory_path()
                         / ("refract_source_bare_" + std::to_string(::getpid()));
    fs::create_directories(dir);
    refract::DeckSource source;
    source.setOutDir(dir.string());
    CHECK(source.available(), "it looks editable");
    std::vector<refract::Asset> assets;
    std::string deckDir, error;
    CHECK(!source.scanAssets(&assets, &deckDir, &error), "but scanning fails");
    CHECK(!error.empty(), "with the tool's reason");
    fs::remove_all(dir);
}

int main() {
    testNoDeck();
    testReadSlide();
    testReadSlideThatIsNotThere();
    testReadFile();
    testScanAssets();
    testRemoveAsset();
    testTheMetaVocabulary();
    testNotADeck();
    if (failures == 0) std::printf("deck_source: ok\n");
    return failures == 0 ? 0 : 1;
}
