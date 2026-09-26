#include "Transcriber.h"

#include "Tools.h"

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

bool Transcriber::start(const std::string& voiceDir, const std::vector<std::string>& stems,
                        const std::string& model, const std::string& language,
                        const std::string& what) {
    const std::vector<std::string> args = transcribeArgs(voiceDir, stems, model, language);
    TranscribeState initial;
    initial.what = what;
    return run(initial, [args, what]() {
        std::string errors;
        const int rc = runTool("captions.py", args, nullptr, &errors);
        TranscribeState state;
        state.ran = true;
        state.what = what;
        state.ok = rc == 0;
        if (!state.ok) state.error = errorTail(errors, "transcription failed");
        return state;
    });
}

}  // namespace refract
