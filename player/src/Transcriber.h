// Transcribing the narration from inside the player.
//
// The work is captions.py's — whisper and whisperx live in Python — and it takes a while,
// so it runs on a worker, one job at a time. The player asks for the whole voice directory
// (File ▸ Transcribe Narration…) or for one slide's recording (the presenter's button),
// and picks up the result at the top of a frame to reload the captions on screen.
#pragma once

#include "Worker.h"

#include <string>
#include <vector>

namespace refract {

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
};

}  // namespace refract
