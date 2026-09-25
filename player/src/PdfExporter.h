// Exporting the deck to a PDF from inside the player.
//
// The exporter itself lives in rcplayer (exportDeckToPdf) and walks the deck on its own
// contexts — but it shares the player's process-wide state, and walking every slide through
// it while a talk is on screen would tear down the slide being shown. So the menu item runs
// the same thing the command line runs: this binary again, headless, with --pdf. Same code,
// same page for page result as `refract.py --pdf`, and the window never notices.
#pragma once

#include <atomic>
#include <mutex>
#include <string>
#include <thread>

namespace refract {

struct PdfExportState {
    bool running = false;
    bool ran = false;          // finished at least once since the player started
    bool ok = false;
    std::string path;          // the PDF asked for
    std::string error;         // last line of what the export said, when it failed
};

class PdfExporter {
public:
    ~PdfExporter();

    // Start writing `deck` (the out/ directory or zip the player was given) to `pdf` at the
    // page size the window opened with. False when one is already running.
    bool start(const std::string& deck, const std::string& pdf, int width, int height,
               double delay);

    bool running() const { return mRunning; }
    PdfExportState state() const;

    void join();

private:
    std::thread mThread;
    std::atomic<bool> mRunning{false};
    mutable std::mutex mMutex;
    PdfExportState mResult;
};

}  // namespace refract
