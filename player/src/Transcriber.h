// Transcribing the narration from inside the player.
//
// The work is captions.py's — whisper and whisperx live in Python — and it takes a while,
// so it runs on a worker, one job at a time. The player asks for the whole voice directory
// (File ▸ Transcribe Narration…) or for one slide's recording (the presenter's button),
// and picks up the result at the top of a frame to reload the captions on screen.
#pragma once

#include "Worker.h"

#include <mutex>
#include <string>
#include <vector>

namespace refract {

// Where a running transcription has got to, from the progress lines captions.py prints:
// `done` of `total` slides finished, and what it is doing to which one now.
struct TranscribeProgress {
    int done = 0;
    int total = 0;
    std::string phase;         // "loading the transcriber", "transcribing", "aligning", "done"
    std::string stem;          // the recording in hand, "07", when there is one
    std::string label() const; // "3 of 23 · aligning 07", for a status line
    float fraction() const { return total > 0 ? static_cast<float>(done) / total : -1.0f; }
};

// The line captions.py prints for a step, parsed; false for any other line.
bool parseTranscribeProgress(const std::string& line, TranscribeProgress* progress);

struct TranscribeState {
    bool running = false;
    bool ran = false;
    bool ok = false;
    std::string what;          // "all slides" or "slide 7", for the message
    std::string error;         // the tool's last line, when it failed
};

// The command line handed to captions.py: `stems` narrows it to those wavs (by stem, "07")
// and, being asked for by name, forces them redone even when they look fresh.
std::vector<std::string> transcribeArgs(const std::string& voiceDir,
                                        const std::vector<std::string>& stems,
                                        const std::string& model, const std::string& language);

class Transcriber : public Worker<TranscribeState> {
public:
    // Transcribe and align the recordings in `voiceDir`, or just `stems` of them (empty for
    // all). False when a job is already running.
    bool start(const std::string& voiceDir, const std::vector<std::string>& stems,
               const std::string& model, const std::string& language, const std::string& what);

    // The last progress reported by the running job (or the finished one).
    TranscribeProgress progress() const;

private:
    mutable std::mutex mProgressMutex;
    TranscribeProgress mProgress;
};

}  // namespace refract
