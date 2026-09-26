// The player's background work, as one list the processing window can draw.
//
// Each worker keeps its own state and its own idea of progress; this turns each into the
// same small card — a name, what it is doing, how far, and the outcome — so the window
// knows nothing about exporters or transcribers, and so the wording can be checked.
#pragma once

#include "PdfExporter.h"
#include "Progress.h"
#include "Transcriber.h"

#include <string>

namespace refract {

// One background task as the window shows it.
struct TaskView {
    std::string name;          // "Export video  talk.mp4"
    std::string status;        // "120 / 1760  slide 3/23 …", "done: …", "failed: …"
    float fraction = -1.0f;    // 0..1, or negative when unknown
    bool running = false;
    bool failed = false;       // finished, badly
};

TaskView exportTask(const PdfExportState& state, const Progress& progress);
TaskView transcriptionTask(const TranscribeState& state, const TranscribeProgress& progress);
TaskView buildTask();          // a rebuild in progress: no count, just running

}  // namespace refract
