// Recording over one slide's narration — when the old take is replaced, and when it is not.
//
// This is the only thing in the player that writes over a recording, so the interesting cases
// are the ones where it must *not*: a cancelled take, and a take that captured nothing because
// the microphone never opened. Both used to be reachable only by talking into a real one.
//
// The microphone is injected, so here it is a lambda that writes a file. Returns 0 on success.

#include "SlideRecorder.h"

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
    std::ofstream out(path);
    out << text;
}

static std::string read(const fs::path& path) {
    std::ifstream in(path);
    return {std::istreambuf_iterator<char>(in), std::istreambuf_iterator<char>()};
}

static fs::path scratch() {
    static int n = 0;
    fs::path dir = fs::temp_directory_path()
                   / ("refract_recorder_test_" + std::to_string(::getpid())
                      + "_" + std::to_string(n++));
    fs::remove_all(dir);
    fs::create_directories(dir / "voice");
    return dir;
}

// A deck with one slide whose narration already exists, and a microphone that writes `sound`
// into whatever file it is pointed at.
struct Fixture {
    fs::path dir = scratch();
    refract::SlideRecorder recorder;
    std::string sound = "new take";
    int keptSlide = -1;
    std::string keptStem;
    fs::path opened;

    Fixture() {
        write(dir / "voice" / "01.wav", "old take");
        recorder.configure(
            [this](int slide) {
                return slide == 0 ? dir / "voice" / "01.wav" : fs::path();
            },
            [this](const std::string& path) {
                opened = path;
                if (!sound.empty()) write(path, sound);
            },
            [] {},
            [this](int slide, const std::string& stem) { keptSlide = slide; keptStem = stem; });
    }

    std::string narration() const { return read(dir / "voice" / "01.wav"); }
    bool tempLeft() const { return fs::exists(dir / "voice" / "01.take.wav"); }
};

static void testATakeThatIsKeptReplacesTheOldOne() {
    Fixture f;
    std::string why;
    CHECK(f.recorder.toggle(0, &why), "a take starts");
    CHECK(f.recorder.running(), "and is running");
    CHECK(f.narration() == "old take", "the old take is untouched while recording");
    CHECK(f.opened.filename() == "01.take.wav", "the microphone writes somewhere else");

    f.recorder.stop(/*keep=*/true);
    CHECK(!f.recorder.running(), "and stops");
    CHECK(f.narration() == "new take", "the new take replaces it");
    CHECK(!f.tempLeft(), "and nothing is left behind");
    CHECK(f.keptSlide == 0 && f.keptStem == "01", "the caller is told which slide got it");
}

static void testACancelledTakeLeavesTheOldOneAlone() {
    Fixture f;
    std::string why;
    f.recorder.toggle(0, &why);
    f.recorder.stop(/*keep=*/false);
    CHECK(f.narration() == "old take", "the old take survives a cancel");
    CHECK(!f.tempLeft(), "and the abandoned one is removed");
    CHECK(f.keptSlide == -1, "nobody is told a take landed");
}

static void testATakeThatCapturedNothingIsNotKept() {
    // The microphone never opened — permission refused, no input device. Replacing a real
    // recording with an empty file is exactly the failure nobody notices until the talk.
    Fixture f;
    f.sound.clear();
    std::string why;
    f.recorder.toggle(0, &why);
    f.recorder.stop(/*keep=*/true);
    CHECK(f.narration() == "old take", "an empty take does not replace anything");
    CHECK(f.keptSlide == -1, "and does not count as a take");
}

static void testTogglingTwiceKeepsTheTake() {
    Fixture f;
    std::string why;
    f.recorder.toggle(0, &why);
    f.recorder.toggle(0, &why);      // the second press is "keep"
    CHECK(!f.recorder.running(), "the second toggle stops it");
    CHECK(f.narration() == "new take", "keeping what was recorded");
}

static void testASlideWithNowhereToRecordIsRefused() {
    Fixture f;
    std::string why;
    CHECK(!f.recorder.toggle(1, &why), "a slide with no narration path is refused");
    CHECK(!why.empty(), "and says why");
    CHECK(!f.recorder.running(), "and nothing is running");
}

static void testStaleCaptionsGoWithTheOldTake() {
    // The transcript and the word timings describe what has just been replaced; left there,
    // the caption window would light the wrong words under the new audio.
    Fixture f;
    write(f.dir / "voice" / "01.txt", "what was said before");
    write(f.dir / "voice" / "01.words.json", "{}");
    std::string why;
    f.recorder.toggle(0, &why);
    f.recorder.stop(/*keep=*/true);
    CHECK(!fs::exists(f.dir / "voice" / "01.txt"), "the stale transcript is removed");
    CHECK(!fs::exists(f.dir / "voice" / "01.words.json"), "and the stale timings");
}

static void testCaptionsSurviveACancel() {
    Fixture f;
    write(f.dir / "voice" / "01.txt", "what was said before");
    std::string why;
    f.recorder.toggle(0, &why);
    f.recorder.stop(/*keep=*/false);
    CHECK(fs::exists(f.dir / "voice" / "01.txt"),
          "a cancelled take leaves the transcript alone");
}

static void testStoppingWhenNothingIsRunningDoesNothing() {
    Fixture f;
    f.recorder.stop(/*keep=*/true);
    CHECK(f.narration() == "old take", "there was nothing to keep");
    CHECK(f.keptSlide == -1, "and nothing to report");
}

int main() {
    testATakeThatIsKeptReplacesTheOldOne();
    testACancelledTakeLeavesTheOldOneAlone();
    testATakeThatCapturedNothingIsNotKept();
    testTogglingTwiceKeepsTheTake();
    testASlideWithNowhereToRecordIsRefused();
    testStaleCaptionsGoWithTheOldTake();
    testCaptionsSurviveACancel();
    testStoppingWhenNothingIsRunningDoesNothing();

    if (failures == 0) std::fprintf(stderr, "slide_recorder_test: all checks passed\n");
    else std::fprintf(stderr, "slide_recorder_test: %d failure(s)\n", failures);
    return failures == 0 ? 0 : 1;
}
