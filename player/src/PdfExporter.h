// Exporting the deck to a PDF or a movie from inside the player.
//
// The exporters themselves live in rcplayer (exportDeckToPdf, exportDeckToVideo) and walk
// the deck on their own contexts — but they share the player's process-wide state, and
// walking every slide through it while a talk is on screen would tear down the slide being
// shown. So the menu item runs the same thing the command line runs: this binary again,
// headless, with --pdf or --video. Same code, same result as `refract.py --pdf` and
// `refract.py --video`, and the window never notices.
#pragma once

#include "Progress.h"
#include "Worker.h"

#include <mutex>

#include <string>
#include <vector>

namespace refract {

struct PdfExportState {
    bool running = false;
    bool ran = false;          // finished at least once since the player started
    bool ok = false;
    std::string kind;          // "PDF" or "video"
    std::string path;          // the file asked for
    std::string error;         // last line of what the export said, when it failed
};

// The command lines the two exports run this binary with. The page size is positional, as
// on the command line: <deck> [width height].
std::vector<std::string> pdfExportArgs(const std::string& deck, const std::string& pdf,
                                       int width, int height, double delay);
std::vector<std::string> videoExportArgs(const std::string& deck, const std::string& mp4,
                                         int from, int to, double fps, int width, int height,
                                         bool captions = false);

class PdfExporter : public Worker<PdfExportState> {
public:
    // Start writing `deck` (the out/ directory or zip the player was given) to `pdf` at the
    // page size the window opened with. False when one is already running.
    bool start(const std::string& deck, const std::string& pdf, int width, int height,
               double delay);

    // The same, for a movie: slides `from`..`to` (1-based, inclusive) at `fps`, with the
    // narration as its soundtrack — the player's --video, on a worker.
    bool startVideo(const std::string& deck, const std::string& mp4, int from, int to,
                    double fps, int width, int height, bool captions = false);

    // Where the running export has got to, from the progress lines the child prints.
    Progress progress() const;

private:
    bool launch(const std::vector<std::string>& args, const std::string& target, const std::string& kind);
    mutable std::mutex mProgressMutex;
    Progress mProgress;
};

}  // namespace refract
