// Where narration lives, on a folder made for the purpose.
//
// A deck is a folder with a slides.md and an out/ under it; the rules say where its wavs
// go and when an old out/voice is moved up. Everything here happens in a temporary
// directory that is removed afterwards.
//
// Returns 0 on success, 1 on any failed assertion.

#include "VoiceDir.h"

#include <cstdio>
#include <fstream>
#include <string>

static int failures = 0;

#define CHECK(cond, msg) do { \
    if (!(cond)) { std::fprintf(stderr, "FAIL: %s\n", msg); ++failures; } \
} while (0)

namespace fs = std::filesystem;

static void touch(const fs::path& p) {
    fs::create_directories(p.parent_path());
    std::ofstream(p) << "x";
}

static void testWhere() {
    const fs::path root = fs::temp_directory_path() / "refract_voice_dir_test";
    fs::remove_all(root);
    touch(root / "talk" / "slides.md");
    fs::create_directories(root / "talk" / "out");
    fs::create_directories(root / "plain" / "out");
    fs::create_directories(root / "recorded" / "voice");
    fs::create_directories(root / "recorded" / "out");

    CHECK(refract::deckVoiceDir(root / "talk" / "out") == root / "talk" / "voice", "a deck's out/ maps to <deck>/voice");
    CHECK(refract::deckVoiceDir(root / "talk" / "out" / "") == root / "talk" / "voice", "with or without a trailing slash");
    CHECK(refract::deckVoiceDir(root / "recorded" / "out") == root / "recorded" / "voice",
          "a folder that already has voice/ counts, slides.md or not");
    CHECK(refract::deckVoiceDir(root / "plain" / "out").empty(), "not a deck: the player's own rule applies");
    CHECK(refract::deckVoiceDir(root / "nowhere").empty(), "a missing input is nothing");
    CHECK(refract::deckVoiceDir(root / "talk" / "slides.md").empty(), "a file is not an out/ directory");
    fs::remove_all(root);
}

static void testAdoption() {
    const fs::path root = fs::temp_directory_path() / "refract_voice_dir_test";
    fs::remove_all(root);
    const fs::path out = root / "talk" / "out";
    touch(root / "talk" / "slides.md");
    touch(out / "voice" / "03.wav");
    touch(out / "voice" / "03.txt");
    const fs::path target = root / "talk" / "voice";

    refract::Adoption a = refract::adoptVoiceDir(out, target);
    CHECK(a.outcome == refract::Adoption::Outcome::Moved, "an old out/voice with a wav is moved");
    CHECK(a.from == out / "voice" && a.to == target, "and says from where to where");
    CHECK(fs::exists(target / "03.wav") && fs::exists(target / "03.txt") && !fs::exists(out / "voice"),
          "whole: every file, and nothing left behind");

    a = refract::adoptVoiceDir(out, target);
    CHECK(a.outcome == refract::Adoption::Outcome::Nothing, "a second time there is nothing to move");

    touch(out / "voice" / "07.wav");
    a = refract::adoptVoiceDir(out, target);
    CHECK(a.outcome == refract::Adoption::Outcome::Nothing && fs::exists(out / "voice" / "07.wav"),
          "a deck that already has voice/ is left alone, old folder and all");

    fs::remove_all(root);
    touch(root / "talk" / "slides.md");
    touch(out / "voice" / "index.json");
    a = refract::adoptVoiceDir(out, target);
    CHECK(a.outcome == refract::Adoption::Outcome::Nothing && !fs::exists(target), "no wav, no move");
    CHECK(refract::adoptVoiceDir(out, fs::path()).outcome == refract::Adoption::Outcome::Nothing, "no target, no move");
    fs::remove_all(root);
}

static void testNarrationFiles() {
    std::vector<fs::path> files = refract::narrationFiles("/v/07.wav");
    CHECK(files.size() == 4, "a wav, a transcript, the timings, the camera take");
    CHECK(files[0] == "/v/07.wav" && files[1] == "/v/07.txt" && files[2] == "/v/07.words.json"
          && files[3] == "/v/07.mov", "named after the wav");
    CHECK(refract::narrationFiles("").empty(), "no wav, no files");
}

int main() {
    testWhere();
    testAdoption();
    testNarrationFiles();
    if (failures) { std::fprintf(stderr, "%d failure(s)\n", failures); return 1; }
    std::printf("voice_dir: all passed\n");
    return 0;
}
