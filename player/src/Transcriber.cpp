#include "Transcriber.h"

#include "Progress.h"
#include "Tools.h"

#include <algorithm>
#include <cctype>
#include <cstdio>

namespace refract {

std::vector<std::string> transcribeArgs(const std::string& voiceDir,
                                        const std::vector<std::string>& stems,
                                        const std::string& model, const std::string& language) {
    std::vector<std::string> args{voiceDir, "--model", model, "--language", language};
    if (!stems.empty()) {
        std::string only;
        for (const auto& s : stems) only += (only.empty() ? "" : ",") + s;
        args.push_back("--only");
        args.push_back(only);
        args.push_back("--force");
    }
    return args;
}

std::string TranscribeProgress::label() const {
    std::string text;
    if (total > 0) text = std::to_string(std::min(done + (phase == "done" ? 0 : 1), total))
                          + " of " + std::to_string(total);
    if (!phase.empty()) text += (text.empty() ? "" : " \u00b7 ") + phase;
    if (!stem.empty()) text += " " + stem;
    return text;
}

bool parseTranscribeProgress(const std::string& line, TranscribeProgress* progress) {
    // "progress: 3/23 aligning 07": the common shape, then the recording split off the end.
    Progress base;
    if (!parseProgressLine(line, &base)) return false;
    const int done = static_cast<int>(base.done), total = static_cast<int>(base.total);
    std::string rest = base.text;
    // The stem is the last word only when the phase is a one-word verb ("aligning 07");
    // the loading phases are several words and name no recording.
    std::string phase = rest, stem;
    const size_t space = rest.rfind(' ');
    if (space != std::string::npos) {
        const std::string last = rest.substr(space + 1);
        const bool looksLikeStem = !last.empty() && std::all_of(last.begin(), last.end(), [](unsigned char c) {
            return std::isalnum(c) || c == '_' || c == '-';
        });
        const std::string head = rest.substr(0, space);
        if (looksLikeStem && head.find(' ') == std::string::npos) { phase = head; stem = last; }
    }
    progress->done = done;
    progress->total = total;
    progress->phase = phase;
    progress->stem = stem;
    return true;
}

TranscribeProgress Transcriber::progress() const {
    std::lock_guard<std::mutex> lock(mProgressMutex);
    return mProgress;
}

bool Transcriber::start(const std::string& voiceDir, const std::vector<std::string>& stems,
                        const std::string& model, const std::string& language,
                        const std::string& what) {
    const std::vector<std::string> args = transcribeArgs(voiceDir, stems, model, language);
    TranscribeState initial;
    initial.what = what;
    {
        std::lock_guard<std::mutex> lock(mProgressMutex);
        mProgress = {};
        mProgress.phase = "starting";
    }
    return run(initial, [this, args, what]() {
        std::string errors;
        const int rc = runTool("captions.py", args, nullptr, &errors, [this](const std::string& line) {
            TranscribeProgress p;
            if (!parseTranscribeProgress(line, &p)) return;
            std::lock_guard<std::mutex> lock(mProgressMutex);
            mProgress = p;
        });
        TranscribeState state;
        state.ran = true;
        state.what = what;
        state.ok = rc == 0;
        if (!state.ok) state.error = errorTail(errors, "transcription failed");
        return state;
    });
}

}  // namespace refract
