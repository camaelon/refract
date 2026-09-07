#include "EditRunner.h"

#include "Tools.h"

#include <nlohmann/json.hpp>

namespace refract {

EditRunner::~EditRunner() { join(); }

void EditRunner::join() {
    if (mThread.joinable()) mThread.join();
}

bool EditRunner::start(const std::string& tool, std::vector<std::string> args,
                       std::string doneMessage, Report report, std::string* status) {
    if (mRunning) {
        *status = "already working — one at a time";
        return false;
    }
    if (mOutDir.empty()) {
        *status = "this deck has no markdown to write to";
        return false;
    }
    args.insert(args.begin(), mOutDir);
    args.push_back("--json");

    join();
    mRunning = true;
    mReport = std::move(report);
    mThread = std::thread([this, tool, args, doneMessage]() {
        std::string output, errors;
        const int rc = runTool(tool, args, &output, &errors);
        // The tools report in JSON so the difference between "nothing to do", "the markdown
        // was rewritten but refract could not rebuild it" and "refused" survives the process
        // boundary. A failed rebuild in particular has already changed the file on disk, and
        // saying so is the difference between a puzzle and a one-line fix in the terminal.
        auto doc = nlohmann::json::parse(output, nullptr, /*allow_exceptions=*/false);
        const bool parsed = !doc.is_discarded() && doc.is_object();

        Result result;
        result.ok = rc == 0 && (!parsed || doc.value("ok", false));
        result.changed = parsed && doc.value("changed", false);
        if (parsed && doc.contains("outputs") && doc["outputs"].is_array()) {
            result.outputs = doc["outputs"].get<std::vector<std::string>>();
        }
        if (!result.ok) {
            result.status = parsed && doc.contains("error")
                                ? doc["error"].get<std::string>()
                                : errorTail(errors, "the edit failed");
            if (result.changed && parsed && !doc.value("rebuilt", false)) {
                result.status = "the markdown was written but the rebuild failed: "
                                + result.status;
            }
        } else if (parsed && doc.contains("description")) {
            // The tool knows better than the caller does: "undid move slide 3" says more
            // than "undone", and "nothing to undo" is not "no change".
            result.status = doc["description"].get<std::string>();
        } else {
            result.status = result.changed ? doneMessage : "no change";
        }
        {
            std::lock_guard<std::mutex> lock(mMutex);
            mResult = result;
            mDone = true;
        }
        mRunning = false;
    });
    *status = "working…";
    return true;
}

void EditRunner::collect() {
    Result result;
    Report report;
    {
        std::lock_guard<std::mutex> lock(mMutex);
        if (!mDone || mRunning) return;
        result = mResult;
        mDone = false;
        report = mReport;
        mReport = nullptr;
    }
    if (report) report(result);
}

}  // namespace refract
