// Running refract over the deck, from inside the player.
//
// On a worker, because refract takes seconds on a big deck and a window frozen for them
// would be the wrong trade for a panel whose whole point is not having to leave. The thread
// only ever writes the result; the main loop reads it, notices the build finish, and
// reloads the deck underneath the slides.
//
// The build itself is player/tools/build.py — the same script a terminal would run, given
// the same options, so a deck built from here and a deck built from a shell are the same
// deck.
#pragma once

#include "Build.h"

#include <atomic>
#include <mutex>
#include <string>
#include <thread>

namespace refract {

class BuildRunner {
public:
    ~BuildRunner();

    // The deck's out/ directory. Empty for a zip bundle, which cannot be rebuilt.
    void setOutDir(const std::string& outDir);

    // Start a build. False when one is already running, or when there is nothing to build
    // into — in which case the state says why.
    bool start(const BuildOptions& options);

    bool running() const { return mRunning; }
    // A snapshot, taken under the lock, with `running` filled in as of now.
    BuildState state() const;

    void join();

    // How the deck on screen was actually built, from deck.json's `build` record — which is
    // also what the reorder tool replays. So the panel opens telling the truth.
    BuildOptions optionsFromManifest() const;

    // The newest modification time across the deck's markdown, its settings and its
    // includes — everything refract reads. Cheap enough to check once a second; refract's
    // own --watch looks at the same set. Zero when there is nothing to watch.
    double sourceMtime() const;

private:
    std::thread mThread;
    std::atomic<bool> mRunning{false};
    mutable std::mutex mMutex;
    BuildState mResult;
    std::string mOutDir;
};

}  // namespace refract
