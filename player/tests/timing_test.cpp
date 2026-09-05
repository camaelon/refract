// The rehearsal trace, and the slide identity it is keyed by.
//
// A trace is only useful if it still points at the right slides after the deck has been
// edited around it. Filenames carry the slide's number, so reordering renames every slide
// after the move; the source block does not. These check that a trace follows its slides
// through that, and that a trace written before keys existed still works.
//
// Returns 0 on success, 1 on any failed assertion.

#include "Deck.h"
#include "Timing.h"

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

static void checkEq(const std::string& got, const std::string& want, const char* msg) {
    if (got != want) {
        std::fprintf(stderr, "FAIL: %s (got \"%s\", want \"%s\")\n", msg,
                     got.c_str(), want.c_str());
        ++failures;
    }
}

static void checkNear(double got, double want, const char* msg) {
    if (got < want - 0.01 || got > want + 0.01) {
        std::fprintf(stderr, "FAIL: %s (got %.2f, want %.2f)\n", msg, got, want);
        ++failures;
    }
}

// ── The slide's name for itself ──────────────────────────────────────

static void testSourceKey() {
    refract::Slide slide;
    slide.srcFile = "slides.md";
    slide.srcIndex = 3;
    checkEq(slide.sourceKey(), "slides.md#3.0", "a slide is named by its block");

    // The steps of an expanded slide share a block and are told apart by their step.
    slide.srcStep = 2;
    checkEq(slide.sourceKey(), "slides.md#3.2", "and by which step of it this is");

    // A sub-deck's slides are named in their own file, which is what makes them unique.
    refract::Slide included;
    included.srcFile = "includes/intro/slides.md";
    included.srcIndex = 3;
    CHECK(included.sourceKey() != "slides.md#3.0", "a sub-deck's block 3 is not the deck's");

    // No provenance, no key — and callers fall back to the filename.
    refract::Slide bare;
    CHECK(bare.sourceKey().empty(), "a deck with no provenance has no keys");
    bare.srcFile = "slides.md";
    CHECK(bare.sourceKey().empty(), "nor with a file but no block");
}

// ── The trace ────────────────────────────────────────────────────────

static fs::path scratch() {
    static int n = 0;
    fs::path dir = fs::temp_directory_path()
                   / ("refract_timing_test_" + std::to_string(::getpid())
                      + "_" + std::to_string(n++));
    fs::remove_all(dir);
    fs::create_directories(dir);
    return dir;
}

static void write(const fs::path& path, const std::string& text) {
    std::ofstream out(path);
    out << text;
}

static void testRecordAndReadBack() {
    const fs::path dir = scratch();
    refract::Timing trace;
    trace.beginRecording((dir / "timing.json").string());
    trace.mark("slides.md#0.0", "01_one.rc", 0.0);
    trace.mark("slides.md#1.0", "02_two.rc", 30.0);
    trace.finish(75.0);

    refract::Timing read;
    CHECK(read.loadForDeck(dir.string()), "the trace is read back");
    CHECK(read.entries().size() == 2, "both slides");
    checkNear(read.total(), 75.0, "and the total");

    const auto* first = read.find("slides.md#0.0", "01_one.rc");
    CHECK(first != nullptr, "found by key");
    if (first) checkNear(first->duration, 30.0, "with its duration");

    // The point of the whole exercise: after a reorder the second slide is called
    // 01_two.rc, and its timing is still its own.
    const auto* moved = read.find("slides.md#1.0", "01_two.rc");
    CHECK(moved != nullptr, "found by key under a new filename");
    if (moved) checkNear(moved->start, 30.0, "with its own start, not the other slide's");
}

static void testARenumberedSlideDoesNotStealATiming() {
    const fs::path dir = scratch();
    refract::Timing trace;
    trace.beginRecording((dir / "timing.json").string());
    trace.mark("slides.md#0.0", "01_one.rc", 0.0);
    trace.mark("slides.md#1.0", "02_two.rc", 30.0);
    trace.finish(60.0);

    refract::Timing read;
    read.loadForDeck(dir.string());
    // A slide that has moved into position 1 but was written elsewhere: its filename matches
    // an entry, and matching on it would credit it with a stranger's timing.
    CHECK(read.find("slides.md#7.0", "01_one.rc") == nullptr,
          "a filename match is not enough when the trace has keys");
    // And a slide the trace has never seen has nothing, however it is named.
    CHECK(read.find("slides.md#9.0", "99_new.rc") == nullptr, "an unknown slide has no timing");
}

static void testATraceWithoutKeysStillWorks() {
    // Written before keys existed. Nothing has been reordered under it either, so matching
    // on the filename is exactly right.
    const fs::path dir = scratch();
    write(dir / "timing.json",
          R"({"deck":"old","total":40,"slides":[)"
          R"({"file":"01_one.rc","start":0,"duration":15},)"
          R"({"file":"02_two.rc","start":15,"duration":25}]})");

    refract::Timing read;
    CHECK(read.loadForDeck(dir.string()), "an old trace still loads");
    const auto* e = read.find("slides.md#1.0", "02_two.rc");
    CHECK(e != nullptr, "and is found by filename");
    if (e) checkNear(e->start, 15.0, "with its timing");
    CHECK(read.find("", "01_one.rc") != nullptr, "even with no key to offer");
}

static void testARevisitedSlideKeepsItsFirstVisit() {
    const fs::path dir = scratch();
    refract::Timing trace;
    trace.beginRecording((dir / "timing.json").string());
    trace.mark("slides.md#0.0", "01_one.rc", 0.0);
    trace.mark("slides.md#1.0", "02_two.rc", 10.0);
    trace.mark("slides.md#0.0", "01_one.rc", 20.0);   // went back
    trace.finish(30.0);

    refract::Timing read;
    read.loadForDeck(dir.string());
    const auto* e = read.find("slides.md#0.0", "01_one.rc");
    CHECK(e != nullptr, "the revisited slide is found");
    // The first visit is where the talk was at that point, which is what pace is measured
    // against; the second is a detour.
    if (e) checkNear(e->start, 0.0, "and it is the first visit");
}

static void testPaceUsesTheKey() {
    const fs::path dir = scratch();
    refract::Timing trace;
    trace.beginRecording((dir / "timing.json").string());
    trace.mark("slides.md#0.0", "01_one.rc", 0.0);
    trace.mark("slides.md#1.0", "02_two.rc", 60.0);
    trace.finish(120.0);

    refract::Timing read;
    read.loadForDeck(dir.string());
    double delta = 0;
    // Half a minute into a slide the rehearsal reached at 60s, having taken 90s to get here:
    // thirty seconds behind.
    CHECK(refract::paceDelta(read, "slides.md#1.0", "07_renamed.rc", 90.0, 0.0, &delta),
          "pace is found by key, whatever the slide is called now");
    checkNear(delta, 30.0, "thirty seconds behind");

    CHECK(!refract::paceDelta(read, "slides.md#9.0", "99_new.rc", 10.0, 0.0, &delta),
          "a slide the rehearsal never saw has no pace to report");
}

static void testAnEmptyTrace() {
    const fs::path dir = scratch();
    refract::Timing read;
    CHECK(!read.loadForDeck(dir.string()), "no trace is not an error");
    CHECK(read.empty(), "and leaves nothing behind");
    CHECK(read.find("slides.md#0.0", "01_one.rc") == nullptr, "with nothing to find");
}

int main() {
    testSourceKey();
    testRecordAndReadBack();
    testARenumberedSlideDoesNotStealATiming();
    testATraceWithoutKeysStillWorks();
    testARevisitedSlideKeepsItsFirstVisit();
    testPaceUsesTheKey();
    testAnEmptyTrace();

    if (failures == 0) std::fprintf(stderr, "timing_test: all checks passed\n");
    else std::fprintf(stderr, "timing_test: %d failure(s)\n", failures);
    return failures == 0 ? 0 : 1;
}
