// A line of progress from a tool, as the player's background work reports it.
//
// Every tool the player runs on a worker — its own binary exporting a PDF or a movie,
// captions.py transcribing — says where it is with the same one-line shape on stderr:
//
//     progress: <done>/<total> <what it is doing>
//
// The player reads those lines as they arrive and shows them in the processing window.
#pragma once

#include <mutex>
#include <string>

namespace refract {

struct Progress {
    long done = 0;
    long total = 0;
    std::string text;              // what it is doing, as the tool put it
    float fraction() const { return total > 0 ? static_cast<float>(done) / static_cast<float>(total) : -1.0f; }
    bool known() const { return total > 0; }
};

// True, and `progress` filled, for a line of that shape; false for any other line, which
// leaves `progress` alone.
bool parseProgressLine(const std::string& line, Progress* progress);

// The latest progress of a job on a worker thread, read from the frame: set from the
// worker as lines arrive, taken as a copy from the main thread.
class ProgressSlot {
public:
    void reset(const std::string& text) {
        std::lock_guard<std::mutex> lock(mMutex);
        mProgress = Progress();
        mProgress.text = text;
    }
    void set(const Progress& progress) {
        std::lock_guard<std::mutex> lock(mMutex);
        mProgress = progress;
    }
    // Parse `line` and, if it is progress, keep it. For a tool's stderr line callback.
    void feed(const std::string& line) {
        Progress p;
        if (parseProgressLine(line, &p)) set(p);
    }
    Progress get() const {
        std::lock_guard<std::mutex> lock(mMutex);
        return mProgress;
    }

private:
    mutable std::mutex mMutex;
    Progress mProgress;
};

}  // namespace refract
