#include "Tasks.h"

#include <filesystem>

namespace refract {

TaskView exportTask(const PdfExportState& state, const Progress& progress) {
    TaskView t;
    t.name = "Export " + state.kind + "  " + std::filesystem::path(state.path).filename().string();
    t.running = state.running;
    if (state.running) {
        t.status = progress.text.empty() ? "starting" : progress.text;
        if (progress.known()) {
            t.status = std::to_string(progress.done) + " / " + std::to_string(progress.total) + "  " + progress.text;
        }
        t.fraction = progress.fraction();
    } else {
        t.failed = !state.ok;
        t.status = state.ok ? "done: " + state.path : "failed: " + state.error;
    }
    return t;
}

TaskView transcriptionTask(const TranscribeState& state, const TranscribeProgress& progress) {
    TaskView t;
    t.name = "Transcribe " + state.what;
    t.running = state.running;
    if (state.running) {
        t.status = progress.label().empty() ? "starting" : progress.label();
        t.fraction = progress.fraction();
    } else {
        t.failed = !state.ok;
        t.status = state.ok ? "done" : "failed: " + state.error;
    }
    return t;
}

TaskView buildTask() {
    TaskView t;
    t.name = "Rebuild the deck";
    t.status = "refract is running";
    t.running = true;
    return t;
}

}  // namespace refract
