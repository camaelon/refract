// The cards the processing window shows, worded from each worker's state.
//
// Returns 0 on success, 1 on any failed assertion.

#include "Tasks.h"

#include <cmath>
#include <cstdio>

static int failures = 0;

#define CHECK(cond, msg) do { \
    if (!(cond)) { std::fprintf(stderr, "FAIL: %s\n", msg); ++failures; } \
} while (0)

static void testExport() {
    refract::PdfExportState state;
    state.running = true;
    state.kind = "video";
    state.path = "/talks/mytalk/mytalk.mp4";
    refract::Progress p;
    refract::TaskView t = refract::exportTask(state, p);
    CHECK(t.name == "Export video  mytalk.mp4", "named for the kind and the file");
    CHECK(t.running && t.status == "starting" && t.fraction < 0.0f, "nothing reported yet: starting, no bar");
    p.text = "assembling the soundtrack";
    t = refract::exportTask(state, p);
    CHECK(t.status == "assembling the soundtrack" && t.fraction < 0.0f, "a step without a count");
    p.done = 120; p.total = 1760; p.text = "slide 3/23 05_between.rc";
    t = refract::exportTask(state, p);
    CHECK(t.status == "120 / 1760  slide 3/23 05_between.rc", "a counted step shows the count");
    CHECK(std::fabs(t.fraction - 120.0f / 1760.0f) < 1e-6, "and fills the bar");
    state.running = false; state.ran = true; state.ok = true;
    t = refract::exportTask(state, p);
    CHECK(!t.running && !t.failed && t.status == "done: /talks/mytalk/mytalk.mp4", "done says where");
    state.ok = false; state.error = "ffmpeg exit 1";
    t = refract::exportTask(state, p);
    CHECK(t.failed && t.status == "failed: ffmpeg exit 1", "failed says why");
}

static void testTranscription() {
    refract::TranscribeState state;
    state.running = true;
    state.what = "slide 7";
    refract::TranscribeProgress p;
    refract::TaskView t = refract::transcriptionTask(state, p);
    CHECK(t.name == "Transcribe slide 7" && t.status == "starting", "named for what was asked");
    p.done = 0; p.total = 1; p.phase = "aligning"; p.stem = "07";
    t = refract::transcriptionTask(state, p);
    CHECK(t.status == "1 of 1 · aligning 07" && t.fraction == 0.0f, "the step as the presenter words it");
    state.running = false; state.ran = true; state.ok = true;
    t = refract::transcriptionTask(state, p);
    CHECK(!t.running && t.status == "done", "done");
}

static void testBuild() {
    refract::TaskView t = refract::buildTask();
    CHECK(t.running && t.fraction < 0.0f && t.name == "Rebuild the deck", "a rebuild has no count");
}

int main() {
    testExport();
    testTranscription();
    testBuild();
    if (failures) { std::fprintf(stderr, "%d failure(s)\n", failures); return 1; }
    std::printf("tasks: all passed\n");
    return 0;
}
