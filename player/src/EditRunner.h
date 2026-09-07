// Rewriting a deck's markdown, off the main thread.
//
// Reordering a slide, adding one, deleting one, splitting one, saving an edit and undoing any
// of it are all the same shape: run a tool that rewrites `slides.md` and re-runs refract, then
// reload the deck. refract takes seconds on a big deck, so none of it happens on the frame —
// the window would stop dead in the middle of the drag that started it.
//
// One at a time, deliberately: two of these writing into the same `out/` is the reliable way
// to get a deck that is neither.
#pragma once

#include <atomic>
#include <functional>
#include <mutex>
#include <string>
#include <thread>
#include <vector>

namespace refract {

class EditRunner {
public:
    // Told when a job finishes: whether it worked, what to say about it, and which outputs
    // the rebuild rewrote — the player drops the stills for those and keeps the rest.
    struct Result {
        bool ok = true;
        bool changed = false;
        std::string status;
        std::vector<std::string> outputs;
    };
    using Report = std::function<void(const Result&)>;

    ~EditRunner();

    // Where the tools are pointed. Empty means there is nothing to edit — a zip bundle.
    void setDeck(std::string outDir) { mOutDir = std::move(outDir); }

    bool running() const { return mRunning; }

    // Start `tool` with `args` (the out directory and `--json` are added). `doneMessage` is
    // the status for a job that changed something and had nothing better to say. False when
    // it could not be started, with `status` saying why.
    bool start(const std::string& tool, std::vector<std::string> args,
               std::string doneMessage, Report report, std::string* status);

    // Call at the top of a frame. Runs the report for a job that has finished, on this
    // thread — so whatever it does next sees a main thread that is free.
    void collect();

    // Wait for whatever is in flight. Called once, at shutdown.
    void join();

private:
    std::string mOutDir;
    std::thread mThread;
    std::atomic<bool> mRunning{false};
    std::mutex mMutex;
    Result mResult;
    bool mDone = false;
    Report mReport;
};

}  // namespace refract
