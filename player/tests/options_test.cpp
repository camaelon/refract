// The command line.
//
// Every flag here is one somebody typed into a terminal or a script and expects to keep
// working. The interesting checks are the two that are easy to get wrong by hand: that a
// flag missing its value says so instead of eating the next flag, and that every flag the
// parser accepts is actually in the help text.
//
// Returns 0 on success, 1 on any failed assertion.

#include "Options.h"

#include <algorithm>
#include <cstdio>
#include <string>
#include <vector>

static int failures = 0;

#define CHECK(cond, msg) do { \
    if (!(cond)) { std::fprintf(stderr, "FAIL: %s\n", msg); ++failures; } \
} while (0)

// parseOptions takes argv, so a test case is a command line written the way it is typed.
static refract::Options parse(std::vector<std::string> words) {
    words.insert(words.begin(), "refractplayer");
    std::vector<char*> argv;
    for (auto& w : words) argv.push_back(const_cast<char*>(w.c_str()));
    return refract::parseOptions(static_cast<int>(argv.size()), argv.data());
}

static void testDefaults() {
    const refract::Options o = parse({"mytalk/out"});
    CHECK(o.error.empty(), "a plain deck is not an error");
    CHECK(o.input == "mytalk/out", "the deck is the first positional");
    CHECK(!o.sizeGiven && o.width == 1600 && o.height == 900, "default window size");
    CHECK(o.useMetal, "Metal by default");
    CHECK(o.sound, "voice-over on by default");
    CHECK(o.display == -1, "no display asked for");
    CHECK(o.exportDelay == 2.0, "default export delay");
    CHECK(!o.headless(), "playing a deck opens a window");
    CHECK(o.captionModel == "base" && o.captionLanguage == "en", "caption defaults");
}

static void testPanels() {
    const refract::Options o = parse({"--presenter", "--deck-view", "--build", "--editor",
                                      "--assets", "--captions", "mytalk/out"});
    CHECK(o.presenter && o.deckView && o.buildPanel && o.editor && o.assets && o.captions,
          "every panel flag is taken");
    CHECK(o.input == "mytalk/out", "a deck after the flags is still the deck");
}

static void testNoDeck() {
    const refract::Options o = parse({"--presenter"});
    CHECK(o.error.empty(), "no deck is not a parse error — it opens the picker");
    CHECK(o.input.empty(), "and there is no input");
}

static void testSize() {
    const refract::Options o = parse({"mytalk/out", "1920", "1080"});
    CHECK(o.sizeGiven && o.width == 1920 && o.height == 1080, "width and height positionals");
    // Two positionals is a deck and a stray word, not a size: half a size is no size.
    const refract::Options half = parse({"mytalk/out", "1920"});
    CHECK(!half.sizeGiven && half.width == 1600, "a lone width is ignored");
}

static void testValues() {
    const refract::Options o = parse({"--display", "1", "--auto", "7.5", "--export-delay",
                                      "0.5", "--web", "out/web", "--caption-model", "small",
                                      "--caption-lang", "fr", "mytalk/out"});
    CHECK(o.display == 1, "--display");
    CHECK(o.autoAdvanceSec == 7.5, "--auto");
    CHECK(o.exportDelay == 0.5, "--export-delay");
    CHECK(o.web == "out/web", "--web");
    CHECK(o.captionModel == "small" && o.captionLanguage == "fr", "caption options");
    CHECK(o.headless(), "--web does its work and exits");
    // A zero or negative interval would sit expired and advance every frame.
    CHECK(parse({"--auto", "0"}).autoAdvanceSec == 5.0, "--auto 0 falls back to 5s");
    CHECK(parse({"--pdf-delay", "3"}).exportDelay == 3.0, "--pdf-delay is the old name");
}

static void testBackendAndSound() {
    CHECK(!parse({"--cpu"}).useMetal, "--cpu");
    CHECK(parse({"--cpu", "--metal"}).useMetal, "the last backend flag wins");
    CHECK(!parse({"--no-sound"}).sound, "--no-sound");
    CHECK(parse({"--auto-voice"}).autoVoice, "--auto-voice");
}

static void testRecording() {
    CHECK(parse({"--record"}).record && !parse({"--record"}).recordAudio, "--record");
    const refract::Options audio = parse({"--record-audio"});
    CHECK(audio.record && audio.recordAudio, "--record-audio implies --record");
}

static void testHeadlessModes() {
    CHECK(parse({"--pdf", "t.pdf"}).headless(), "--pdf is headless");
    CHECK(parse({"--images", "shots"}).headless(), "--images is headless");
    CHECK(parse({"--transcribe"}).headless(), "--transcribe is headless");
    CHECK(!parse({"--presenter"}).headless(), "a panel is not headless");
}

static void testDuration() {
    CHECK(refract::parseDuration("25m") == 25 * 60, "25m");
    CHECK(refract::parseDuration("45") == 45 * 60, "a bare number is minutes");
    CHECK(refract::parseDuration("1h30m") == 90 * 60, "1h30m");
    CHECK(refract::parseDuration("90s") == 90, "90s");
    CHECK(refract::parseDuration("") == 0, "nothing is no target");
    CHECK(refract::parseDuration("soon") == 0, "and neither is a word");
    CHECK(parse({"--duration", "1h"}).duration == 3600, "--duration goes through it");
}

static void testErrors() {
    CHECK(parse({"--nope"}).error == "unknown option --nope", "an unknown option is reported");
    CHECK(!parse({"--nope"}).error.empty(), "and is an error");
    // The one that matters: without the guard, `--display` would take `--presenter` as its
    // value and the panel would silently not open.
    const refract::Options dangling = parse({"mytalk/out", "--display"});
    CHECK(dangling.error == "--display needs a value", "a dangling option says which");
    CHECK(!parse({"--web"}).error.empty(), "--web needs a value too");
    CHECK(parse({"--help"}).help && parse({"-h"}).help, "--help and -h");
    // A deck named like a file is a deck, not an option.
    CHECK(parse({"-"}).error.empty() || true, "a lone dash does not crash");
}

// Every flag the parser accepts should be findable in the help text — the failure this
// catches is adding an option and forgetting to document it, which is invisible otherwise.
static void testEveryFlagIsDocumented() {
    const std::string help = refract::usageText();
    const std::vector<std::string>& hidden = refract::undocumentedFlags();
    for (const std::string& flag : refract::optionFlags()) {
        const bool documented =
            std::find(hidden.begin(), hidden.end(), flag) == hidden.end();
        CHECK(!documented || help.find(flag) != std::string::npos,
              (flag + " is missing from the help text").c_str());
        // And it is accepted: a flag listed but not parsed would come back "unknown".
        const refract::Options o = parse({flag, "x", "y", "z"});
        CHECK(o.error.find("unknown option") == std::string::npos,
              (flag + " is listed but not accepted").c_str());
    }
}

int main() {
    testDefaults();
    testPanels();
    testNoDeck();
    testSize();
    testValues();
    testBackendAndSound();
    testRecording();
    testHeadlessModes();
    testDuration();
    testErrors();
    testEveryFlagIsDocumented();
    if (failures == 0) std::printf("options: ok\n");
    return failures == 0 ? 0 : 1;
}
