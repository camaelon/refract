#include "Scrolling.h"

#include <cmath>

namespace refract {

namespace {

// A notch moves this many lines. Three is what everything else on the machine does.
constexpr float kLinesPerNotch = 3.0f;
// A swipe is already a distance; this is the gain on it. GLFW hands over a tenth of the
// pixels the finger moved, so ten would be one-to-one and this is a little livelier.
constexpr float kSwipeGain = 55.0f;
// Stands in for a view that has not worked out its own rows yet.
constexpr float kDefaultLine = 48.0f;

}  // namespace

float scrollPixels(double delta, float lineHeight) {
    if (delta == 0.0) return 0.0f;
    const double whole = std::round(delta);
    // A whole number of at least one is a notch. A trackpad reaching exactly 1.0 would be
    // given a notch's distance for that one event, which is a step nobody would notice.
    const bool notch = std::fabs(delta - whole) < 0.01 && std::fabs(delta) >= 1.0;
    // A view that has not been laid out yet has no line height to scale by. It can be
    // scrolled before its first frame, and a notch that moved nothing would be a wheel that
    // does nothing until the window is touched.
    const float line = lineHeight > 0 ? lineHeight : kDefaultLine;
    if (notch) return static_cast<float>(delta) * line * kLinesPerNotch;
    return static_cast<float>(delta) * kSwipeGain;
}

}  // namespace refract
