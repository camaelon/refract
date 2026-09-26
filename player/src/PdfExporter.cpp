#include "PdfExporter.h"

#include "Tools.h"

#include <filesystem>

namespace refract {

std::vector<std::string> pdfExportArgs(const std::string& deck, const std::string& pdf,
                                       int width, int height, double delay) {
    return {deck, "--pdf", pdf, std::to_string(width), std::to_string(height),
            "--export-delay", std::to_string(delay)};
}

std::vector<std::string> videoExportArgs(const std::string& deck, const std::string& mp4,
                                         int from, int to, double fps, int width, int height,
                                         bool captions) {
    std::vector<std::string> args{deck, "--video", mp4, "--from", std::to_string(from),
                                  "--to", std::to_string(to), "--fps", std::to_string(fps),
                                  std::to_string(width), std::to_string(height)};
    if (captions) args.push_back("--captions");
    return args;
}

bool PdfExporter::start(const std::string& deck, const std::string& pdf, int width, int height,
                        double delay) {
    return launch(pdfExportArgs(deck, pdf, width, height, delay), pdf, "PDF");
}

bool PdfExporter::startVideo(const std::string& deck, const std::string& mp4, int from, int to,
                             double fps, int width, int height, bool captions) {
    return launch(videoExportArgs(deck, mp4, from, to, fps, width, height, captions), mp4, "video");
}

Progress PdfExporter::progress() const {
    std::lock_guard<std::mutex> lock(mProgressMutex);
    return mProgress;
}

bool PdfExporter::launch(const std::vector<std::string>& args, const std::string& target,
                         const std::string& kind) {
    if (running()) return false;
    const std::filesystem::path self = executablePath();
    if (self.empty()) {
        PdfExportState state;
        state.ran = true;
        state.kind = kind;
        state.path = target;
        state.error = "cannot find the player binary to run the export";
        finishNow(state);
        return false;
    }
    PdfExportState initial;
    initial.kind = kind;
    initial.path = target;
    {
        std::lock_guard<std::mutex> lock(mProgressMutex);
        mProgress = {};
        mProgress.text = "starting";
    }
    return run(initial, [this, self, args, target, kind]() {
        std::string errors;
        const int rc = runProgram(self.string(), args, &errors, [this](const std::string& line) {
            Progress p;
            if (!parseProgressLine(line, &p)) return;
            std::lock_guard<std::mutex> lock(mProgressMutex);
            mProgress = p;
        });
        PdfExportState state;
        state.ran = true;
        state.kind = kind;
        state.path = target;
        state.ok = rc == 0 && std::filesystem::exists(target);
        if (!state.ok) state.error = errorTail(errors, "export failed");
        return state;
    });
}

}  // namespace refract
