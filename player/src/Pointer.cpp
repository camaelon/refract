#include "Pointer.h"

#include <cmath>

namespace refract {

namespace {
constexpr size_t kMaxSamples = 240;    // a few seconds of fast motion
}

void Pointer::moved(double x, double y, double now) {
    mLastMove = now;
    mInside = true;
    // A stationary mouse still reports (a click, a subpixel jitter): only real motion adds
    // to the trail, or a still pointer would grow a stack of identical dots.
    if (!mSamples.empty()) {
        const Sample& last = mSamples.back();
        if (std::fabs(last.x - x) < 0.5 && std::fabs(last.y - y) < 0.5) {
            mSamples.back().at = now;    // the head stays fresh while the mouse rests
            return;
        }
    }
    mSamples.push_back({x, y, now});
    while (mSamples.size() > kMaxSamples) mSamples.pop_front();
}

void Pointer::left() { mInside = false; }
void Pointer::entered() { mInside = true; }

void Pointer::setLaser(bool on) {
    mLaser = on;
    mSamples.clear();      // a fresh trail either way: the old one belongs to the arrow
}

std::vector<Pointer::Sample> Pointer::trail(double now, double fade) const {
    std::vector<Sample> out;
    if (!mLaser || !mInside) return out;
    for (const Sample& s : mSamples) {
        if (now - s.at <= fade) out.push_back(s);
    }
    return out;
}

bool Pointer::head(Sample* out) const {
    if (!mLaser || !mInside || mSamples.empty()) return false;
    *out = mSamples.back();
    return true;
}

}  // namespace refract
