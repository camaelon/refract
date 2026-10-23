#include "PerfTrace.h"

#include <fstream>

#include <nlohmann/json.hpp>

namespace refract {

void PerfTrace::start(const std::string& path, double dwellSec, int slideCount) {
    mActive = true;
    mPath = path;
    mDwell = dwellSec > 0.0 ? dwellSec : 3.0;
    mSlideCount = slideCount;
    mFrames.reserve(static_cast<size_t>(slideCount * mDwell * 130.0) + 64);
}

void PerfTrace::slideChanged(int index, const std::string& title, double switchMs) {
    if (mActive) mSlides.push_back({index, title, switchMs});
}

void PerfTrace::frame(int index, double sinceSwitchSec, double intervalMs, double cpuMs,
                      double pollMs, double swapMs) {
    if (mActive) mFrames.push_back({index, (float)sinceSwitchSec, (float)intervalMs, (float)cpuMs,
                                    (float)pollMs, (float)swapMs});
}

bool PerfTrace::write(std::string* error) const {
    nlohmann::json doc;
    doc["dwell"] = mDwell;
    doc["slide_count"] = mSlideCount;
    auto& slides = doc["slides"] = nlohmann::json::array();
    for (const auto& s : mSlides)
        slides.push_back({{"index", s.index}, {"title", s.title}, {"switch_ms", s.switchMs}});
    // Frames as rows, [slide, seconds since the change, interval ms, cpu ms, event-pump ms
    // since the last frame, the last swap's ms]: thousands of them, so no keys per row.
    auto& frames = doc["frames"] = nlohmann::json::array();
    for (const auto& f : mFrames) frames.push_back({f.index, f.since, f.interval, f.cpu, f.poll, f.swap});
    std::ofstream out(mPath);
    if (!out) { if (error) *error = "cannot write " + mPath; return false; }
    out << doc.dump() << "\n";
    return true;
}

}  // namespace refract
