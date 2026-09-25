#include "PdfExporter.h"

#include "Tools.h"

#include <filesystem>

namespace refract {

PdfExporter::~PdfExporter() { join(); }

void PdfExporter::join() {
    if (mThread.joinable()) mThread.join();
}

PdfExportState PdfExporter::state() const {
    PdfExportState snapshot;
    {
        std::lock_guard<std::mutex> lock(mMutex);
        snapshot = mResult;
    }
    snapshot.running = mRunning;
    return snapshot;
}

bool PdfExporter::start(const std::string& deck, const std::string& pdf, int width, int height,
                        double delay) {
    if (mRunning) return false;
    const std::filesystem::path self = executablePath();
    if (self.empty()) {
        std::lock_guard<std::mutex> lock(mMutex);
        mResult = {};
        mResult.ran = true;
        mResult.path = pdf;
        mResult.error = "cannot find the player binary to run the export";
        return false;
    }
    // The page size is positional, as on the command line: <deck> [width height].
    std::vector<std::string> args{deck, "--pdf", pdf,
                                  std::to_string(width), std::to_string(height),
                                  "--export-delay", std::to_string(delay)};
    join();
    mRunning = true;
    {
        std::lock_guard<std::mutex> lock(mMutex);
        mResult = {};
        mResult.path = pdf;
    }
    mThread = std::thread([this, self, args, pdf]() {
        std::string errors;
        const int rc = runProgram(self.string(), args, &errors);
        PdfExportState state;
        state.ran = true;
        state.path = pdf;
        state.ok = rc == 0 && std::filesystem::exists(pdf);
        if (!state.ok) state.error = errorTail(errors, "export failed");
        {
            std::lock_guard<std::mutex> lock(mMutex);
            mResult = state;
        }
        mRunning = false;
    });
    return true;
}

}  // namespace refract
