#include "BuildRunner.h"

#include "Tools.h"

#include <nlohmann/json.hpp>

#include <algorithm>
#include <filesystem>
#include <fstream>

namespace fs = std::filesystem;

namespace refract {

BuildRunner::~BuildRunner() { join(); }

void BuildRunner::setOutDir(const std::string& outDir) { mOutDir = outDir; }

void BuildRunner::join() {
    if (mThread.joinable()) mThread.join();
}

BuildState BuildRunner::state() const {
    BuildState snapshot;
    {
        std::lock_guard<std::mutex> lock(mMutex);
        snapshot = mResult;
    }
    snapshot.running = mRunning;
    return snapshot;
}

bool BuildRunner::start(const BuildOptions& options) {
    if (mRunning) return false;
    if (mOutDir.empty()) {
        std::lock_guard<std::mutex> lock(mMutex);
        mResult = {};
        mResult.ran = true;
        mResult.ok = false;
        mResult.error = "this deck has no directory to rebuild into";
        return false;
    }

    std::vector<std::string> args{mOutDir};
    if (options.transitions) args.push_back("--transitions");
    if (options.debug)       args.push_back("--debug");
    if (options.force)       args.push_back("--force");
    if (options.keepJson)    args.push_back("--keep-json");
    args.push_back("--json");

    join();   // the previous build's thread, long finished
    mRunning = true;
    mThread = std::thread([this, args]() {
        std::string output, errors;
        const int rc = runTool("build.py", args, &output, &errors);
        auto doc = nlohmann::json::parse(output, nullptr, /*allow_exceptions=*/false);
        const bool parsed = !doc.is_discarded() && doc.is_object();

        BuildState state;
        state.ran = true;
        state.ok = rc == 0 && parsed && doc.value("ok", false);
        if (parsed) {
            state.rebuilt = doc.value("rebuilt", 0);
            state.reused  = doc.value("reused", 0);
            state.removed = doc.value("removed", 0);
            state.seconds = doc.value("seconds", 0.0);
            if (doc.contains("error")) state.error = doc["error"].get<std::string>();
        }
        if (!state.ok && state.error.empty()) state.error = errorTail(errors, "build failed");

        {
            std::lock_guard<std::mutex> lock(mMutex);
            mResult = state;
        }
        mRunning = false;
    });
    return true;
}

BuildOptions BuildRunner::optionsFromManifest() const {
    BuildOptions options;
    if (mOutDir.empty()) return options;
    std::ifstream manifest(fs::path(mOutDir) / "deck.json");
    if (!manifest) return options;
    auto doc = nlohmann::json::parse(manifest, nullptr, /*allow_exceptions=*/false);
    if (doc.is_discarded() || !doc.contains("build")) return options;
    const auto& build = doc["build"];
    options.transitions = build.value("transitions", false);
    options.debug = build.value("debug", false);
    return options;
}

double BuildRunner::sourceMtime() const {
    if (mOutDir.empty()) return 0.0;
    const fs::path deckDir = fs::path(mOutDir).parent_path();
    double newest = 0.0;
    auto note = [&newest](const fs::path& path) {
        std::error_code ec;
        const auto when = fs::last_write_time(path, ec);
        if (!ec) newest = std::max(newest, static_cast<double>(when.time_since_epoch().count()));
    };
    for (const char* name : {"slides.md", "settings.toml"}) note(deckDir / name);
    std::error_code ec;
    for (fs::recursive_directory_iterator it(deckDir / "includes", ec), end; it != end;
         it.increment(ec)) {
        if (ec) break;
        if (!it->is_directory(ec)) note(it->path());
    }
    return newest;
}

}  // namespace refract
