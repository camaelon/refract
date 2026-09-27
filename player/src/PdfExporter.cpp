#include "PdfExporter.h"

#include "Tools.h"

#include <filesystem>

namespace refract {

namespace {
void withSlides(std::vector<std::string>& args, const std::string& slides) {
    if (!slides.empty()) { args.push_back("--slides"); args.push_back(slides); }
}
}  // namespace

std::vector<std::string> pdfExportArgs(const std::string& deck, const std::string& pdf,
                                       int width, int height, double delay, const std::string& slides) {
    std::vector<std::string> args{deck, "--pdf", pdf, std::to_string(width), std::to_string(height),
                                  "--export-delay", std::to_string(delay)};
    withSlides(args, slides);
    return args;
}

std::vector<std::string> videoExportArgs(const std::string& deck, const std::string& mp4,
                                         const std::string& slides, double fps, int width, int height,
                                         bool captions) {
    std::vector<std::string> args{deck, "--video", mp4, "--fps", std::to_string(fps),
                                  std::to_string(width), std::to_string(height)};
    withSlides(args, slides);
    if (captions) args.push_back("--captions");
    return args;
}

std::vector<std::string> webExportArgs(const std::string& deck, const std::string& dir,
                                       const std::string& slides) {
    std::vector<std::string> args{deck, "--web", dir};
    withSlides(args, slides);
    return args;
}

bool PdfExporter::start(const std::string& deck, const std::string& pdf, int width, int height,
                        double delay, const std::string& slides) {
    return launch(pdfExportArgs(deck, pdf, width, height, delay, slides), pdf, "PDF");
}

bool PdfExporter::startVideo(const std::string& deck, const std::string& mp4, const std::string& slides,
                             double fps, int width, int height, bool captions) {
    return launch(videoExportArgs(deck, mp4, slides, fps, width, height, captions), mp4, "video");
}

bool PdfExporter::startWeb(const std::string& deck, const std::string& dir, const std::string& slides) {
    const std::string page = (std::filesystem::path(dir) / "index.html").string();
    return launch(webExportArgs(deck, dir, slides), page, "web");
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
    mProgress.reset("starting");
    return run(initial, [this, self, args, target, kind]() {
        std::string errors;
        const int rc = runProgram(self.string(), args, &errors,
                                  [this](const std::string& line) { mProgress.feed(line); });
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
