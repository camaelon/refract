// --perf: the deck run through on a timer in the real window, every frame timed, and the
// record written out for tools/perf_report.py to read.
//
// What is measured is what an audience would see go wrong: the gap between frames (a frame
// that took longer than the display's interval is a stutter, however it came about), the
// CPU time the player spent producing it (render + present, not the wait for vsync), and the
// time a slide change itself took (loading the next slide) — the classic first-frame hitch.
#pragma once

#include <string>
#include <vector>

namespace refract {

class PerfTrace {
public:
    void start(const std::string& path, double dwellSec, int slideCount);
    bool active() const { return mActive; }
    double dwell() const { return mDwell; }

    // A slide change: which slide, its title, and how long the change took.
    void slideChanged(int index, const std::string& title, double switchMs);
    // One presented frame.
    // One presented frame: the gap since the last, the CPU spent rendering and presenting it,
    // the time spent pumping events since the last frame, and how long the last swap took.
    void frame(int index, double sinceSwitchSec, double intervalMs, double cpuMs,
               double pollMs = 0.0, double swapMs = 0.0);
    // Written once, when the run has shown the last slide for its dwell.
    bool write(std::string* error) const;

private:
    struct Slide { int index; std::string title; double switchMs; };
    struct Frame { int index; float since, interval, cpu, poll, swap; };
    bool mActive = false;
    double mDwell = 3.0;
    int mSlideCount = 0;
    std::string mPath;
    std::vector<Slide> mSlides;
    std::vector<Frame> mFrames;
};

}  // namespace refract
