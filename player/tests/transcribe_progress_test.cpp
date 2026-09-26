// The progress lines captions.py prints, as the presenter reads them.
//
// The tool says where it is one line at a time on stderr; the player turns each into a
// count, a phase and the recording in hand, and a status line. Every line the script can
// print is here, and the lines it prints for other reasons must parse as "not progress".
//
// Returns 0 on success, 1 on any failed assertion.

#include "Transcriber.h"

#include <cmath>
#include <cstdio>

static int failures = 0;

#define CHECK(cond, msg) do { \
    if (!(cond)) { std::fprintf(stderr, "FAIL: %s\n", msg); ++failures; } \
} while (0)

static void testSteps() {
    refract::TranscribeProgress p;
    CHECK(refract::parseTranscribeProgress("progress: 2/23 aligning 07", &p), "a step with a recording");
    CHECK(p.done == 2 && p.total == 23 && p.phase == "aligning" && p.stem == "07", "count, phase and stem");
    CHECK(p.label() == "3 of 23 · aligning 07", "the status line counts the slide in hand");
    CHECK(std::fabs(p.fraction() - 2.0f / 23.0f) < 1e-6, "the bar is the slides finished");

    CHECK(refract::parseTranscribeProgress("progress: 0/23 loading the transcriber", &p), "a loading step");
    CHECK(p.phase == "loading the transcriber" && p.stem.empty(), "several words, no recording");
    CHECK(p.label() == "1 of 23 · loading the transcriber", "loading counts toward the first slide");

    CHECK(refract::parseTranscribeProgress("progress: 23/23 done\r", &p), "done, with a stray CR");
    CHECK(p.phase == "done" && p.stem.empty() && p.done == 23, "done is a phase, not a stem");
    CHECK(p.label() == "23 of 23 · done", "done does not count one more");
    CHECK(std::fabs(p.fraction() - 1.0f) < 1e-6, "and the bar is full");
}

static void testNotProgress() {
    refract::TranscribeProgress p;
    p.done = 5;
    CHECK(!refract::parseTranscribeProgress("  07  transcribed, 34 words", &p), "a result line");
    CHECK(!refract::parseTranscribeProgress("progress: soon", &p), "no count");
    CHECK(!refract::parseTranscribeProgress("UserWarning: FP16 is not supported on CPU", &p), "a library warning");
    CHECK(p.done == 5, "a line that is not progress leaves the last progress alone");
    refract::TranscribeProgress none;
    CHECK(none.fraction() < 0.0f && none.label().empty(), "nothing reported yet: no bar, no text");
}

int main() {
    testSteps();
    testNotProgress();
    if (failures) { std::fprintf(stderr, "%d failure(s)\n", failures); return 1; }
    std::printf("transcribe_progress: all passed\n");
    return 0;
}
