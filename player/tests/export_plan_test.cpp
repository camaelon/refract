// The export's decisions: names, ranges, timings and the ffmpeg line.
//
// Each of these is a rule somebody once got wrong by hand — a deck opened as "out" from
// inside its folder exporting as out.pdf, a slide range past the end, a slide's stay a
// fraction of a frame off its soundtrack — and each is a plain function of its inputs.
//
// Returns 0 on success, 1 on any failed assertion.

#include "ExportPlan.h"

#include <cmath>
#include <cstdio>
#include <filesystem>
#include <string>

static int failures = 0;

#define CHECK(cond, msg) do { \
    if (!(cond)) { std::fprintf(stderr, "FAIL: %s\n", msg); ++failures; } \
} while (0)

namespace fs = std::filesystem;

static std::string leaf(const std::string& p) { return fs::path(p).filename().string(); }
static bool has(const std::string& s, const std::string& part) { return s.find(part) != std::string::npos; }

static void testTarget() {
    refract::ExportTarget t = refract::exportTarget("/talks/mytalk/out");
    CHECK(t.name == "mytalk" && t.dir == "/talks/mytalk", "out/ exports beside the sources, named after the deck");
    t = refract::exportTarget("/talks/mytalk/out/");
    CHECK(t.name == "mytalk" && t.dir == "/talks/mytalk", "a trailing slash changes nothing");
    t = refract::exportTarget("/talks/mytalk");
    CHECK(t.name == "mytalk" && t.dir == "/talks/mytalk", "a deck folder given directly");
    t = refract::exportTarget("/talks/mytalk.zip");
    CHECK(t.name == "mytalk" && t.dir == "/talks", "a zip exports beside itself, without the extension");
    t = refract::exportTarget("/talks/MyTalk.ZIP");
    CHECK(t.name == "MyTalk" && t.dir == "/talks", "however the extension is cased");

    // Relative paths are resolved first, so a deck opened as "out" from inside its folder
    // is still named after the folder, not after out.
    const fs::path cwd = fs::current_path();
    t = refract::exportTarget("out");
    CHECK(t.name == cwd.filename().string() && t.dir == cwd.string(), "\"out\" from inside the deck");
    t = refract::exportTarget(".");
    CHECK(t.name == cwd.filename().string(), "\".\" is the folder it stands for");
    t = refract::exportTarget("/");
    CHECK(t.name == "deck", "nothing to be named after falls back to deck");
}

static void testRange() {
    int first = 0, last = 0;
    CHECK(refract::videoRange(10, 1, 0, &first, &last) && first == 1 && last == 10, "the defaults take the whole deck");
    CHECK(refract::videoRange(10, 3, 5, &first, &last) && first == 3 && last == 5, "a range as typed");
    CHECK(refract::videoRange(10, 0, 50, &first, &last) && first == 1 && last == 10, "clamped to the deck");
    CHECK(refract::videoRange(10, -4, 0, &first, &last) && first == 1, "a negative start is the first slide");
    CHECK(!refract::videoRange(10, 6, 5, &first, &last), "from past to is empty");
    CHECK(!refract::videoRange(0, 1, 0, &first, &last), "an empty deck is empty");
    CHECK(refract::videoRange(10, 7, 7, &first, &last) && first == 7 && last == 7, "one slide is a range");
}

static void testSnap() {
    CHECK(std::fabs(refract::snapToFrames(2.0, 30.0) - 2.0) < 1e-9, "a whole number of frames is left alone");
    CHECK(std::fabs(refract::snapToFrames(2.017, 30.0) - 2.0333333333) < 1e-6, "rounded to the nearest frame");
    CHECK(std::fabs(refract::snapToFrames(0.2, 30.0) - 1.0) < 1e-9, "never under a second");
    CHECK(std::fabs(refract::snapToFrames(0.0, 25.0) - 1.0) < 1e-9, "no narration still holds a second");
    const double s = refract::snapToFrames(3.3, 24.0);
    CHECK(std::fabs(s * 24.0 - std::lround(s * 24.0)) < 1e-9, "the result is on the frame grid");
}

static void testSoundtrack() {
    const std::string cmd = refract::soundtrackCommand(
        {{"/v/01.wav", 2.5}, {"", 1.0}, {"/v/it's.wav", 4.0}}, "/o/deck.mp4.audio.wav");
    CHECK(has(cmd, "ffmpeg -y"), "it is an ffmpeg line");
    CHECK(has(cmd, "-i '/v/01.wav'"), "a recording is an input");
    CHECK(has(cmd, "-f lavfi -t 1.000 -i anullsrc"), "a slide without one is silence of its stay");
    CHECK(has(cmd, "-i '/v/it'\\''s.wav'"), "a quote in a path is escaped for the shell");
    CHECK(has(cmd, "[0:a]aresample=48000") && has(cmd, "atrim=0:2.500,apad=whole_dur=2.500[a0]"),
          "each input is resampled and cut or padded to its stay");
    CHECK(has(cmd, "[a0][a1][a2]concat=n=3:v=0:a=1[out]"), "then joined in order");
    CHECK(has(cmd, "-map '[out]'") && has(cmd, "'/o/deck.mp4.audio.wav'"), "into the audio file asked for");
    const size_t filterAt = cmd.find("-filter_complex '");
    const size_t mapAt = cmd.find("-map");
    CHECK(filterAt != std::string::npos && mapAt != std::string::npos && filterAt < mapAt, "filter before map");
}

int main() {
    testTarget();
    testRange();
    testSnap();
    testSoundtrack();
    if (failures) { std::fprintf(stderr, "%d failure(s)\n", failures); return 1; }
    std::printf("export_plan: all passed\n");
    return 0;
}
