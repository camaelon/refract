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
                                         int from, int to, double fps, int width, int height) {
    return {deck, "--video", mp4, "--from", std::to_string(from), "--to", std::to_string(to),
            "--fps", std::to_string(fps), std::to_string(width), std::to_string(height)};
}

bool PdfExporter::start(const std::string& deck, const std::string& pdf, int width, int height,
                        double delay) {
    return launch(pdfExportArgs(deck, pdf, width, height, delay), pdf);
}

bool PdfExporter::startVideo(const std::string& deck, const std::string& mp4, int from, int to,
                             double fps, int width, int height) {
    return launch(videoExportArgs(deck, mp4, from, to, fps, width, height), mp4);
}

bool PdfExporter::launch(const std::vector<std::string>& args, const std::string& target) {
    if (running()) return false;
    const std::filesystem::path self = executablePath();
    if (self.empty()) {
        PdfExportState state;
        state.ran = true;
        state.path = target;
        state.error = "cannot find the player binary to run the export";
        finishNow(state);
        return false;
    }
    PdfExportState initial;
    initial.path = target;
    return run(initial, [self, args, target]() {
        std::string errors;
        const int rc = runProgram(self.string(), args, &errors);
        PdfExportState state;
        state.ran = true;
        state.path = target;
        state.ok = rc == 0 && std::filesystem::exists(target);
        if (!state.ok) state.error = errorTail(errors, "export failed");
        return state;
    });
}

}  // namespace refract
