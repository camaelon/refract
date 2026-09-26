// One job at a time on a background thread, with its outcome read from the frame.
//
// The player runs its slow work — a PDF export, a transcription — as another process on a
// worker thread and polls for the result at the top of a frame. Every such runner needs the
// same three things: a running flag the frame can read, a result it can copy out under a
// lock, and a join in the destructor so the process never exits under the thread. This is
// those three things; a runner adds the arguments and the meaning.
#pragma once

#include <atomic>
#include <functional>
#include <mutex>
#include <thread>

namespace refract {

template <class State>
class Worker {
public:
    Worker() = default;
    Worker(const Worker&) = delete;
    Worker& operator=(const Worker&) = delete;
    ~Worker() { join(); }

    bool running() const { return mRunning; }

    // The last outcome, with `running` set from the flag rather than the copy, so a caller
    // polling it sees the job as running until its result is in place.
    State state() const {
        State snapshot;
        {
            std::lock_guard<std::mutex> lock(mMutex);
            snapshot = mResult;
        }
        snapshot.running = mRunning;
        return snapshot;
    }

    void join() {
        if (mThread.joinable()) mThread.join();
    }

protected:
    // Start `job` on the worker, with `initial` as the state shown until it finishes. False,
    // and nothing started, when a job is already running.
    bool run(State initial, std::function<State()> job) {
        if (mRunning) return false;
        join();
        mRunning = true;
        {
            std::lock_guard<std::mutex> lock(mMutex);
            mResult = std::move(initial);
        }
        mThread = std::thread([this, job = std::move(job)]() {
            State result = job();
            {
                std::lock_guard<std::mutex> lock(mMutex);
                mResult = std::move(result);
            }
            mRunning = false;
        });
        return true;
    }

    // Record an outcome without running anything: for a job that could not even start.
    void finishNow(State result) {
        std::lock_guard<std::mutex> lock(mMutex);
        mResult = std::move(result);
    }

private:
    std::thread mThread;
    std::atomic<bool> mRunning{false};
    mutable std::mutex mMutex;
    State mResult;
};

}  // namespace refract
