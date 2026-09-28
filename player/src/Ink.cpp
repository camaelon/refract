#include "Ink.h"

#include <cmath>

namespace refract {

namespace {
// A new point only when the mouse has moved this far (as a fraction of the slide): the
// same rest-and-jitter filter the laser's trail has, so a held button does not pile up.
constexpr float kMinStep = 0.0015f;
const std::vector<InkStroke> kNone;
}

void Ink::begin(int slide, float x, float y) {
    end();
    mDrawing = true;
    mSlide = slide;
    mBySlide[slide].push_back(InkStroke{{InkPoint{x, y}}});
}

void Ink::extend(float x, float y) {
    if (!mDrawing) return;
    InkStroke& stroke = mBySlide[mSlide].back();
    const InkPoint& last = stroke.points.back();
    if (std::fabs(last.x - x) < kMinStep && std::fabs(last.y - y) < kMinStep) return;
    stroke.points.push_back(InkPoint{x, y});
}

void Ink::end() {
    mDrawing = false;
    mSlide = -1;
}

const std::vector<InkStroke>& Ink::strokes(int slide) const {
    const auto it = mBySlide.find(slide);
    return it == mBySlide.end() ? kNone : it->second;
}

bool Ink::any(int slide) const { return !strokes(slide).empty(); }

void Ink::clear(int slide) {
    if (mDrawing && mSlide == slide) end();
    mBySlide.erase(slide);
}

void Ink::clearAll() {
    end();
    mBySlide.clear();
}

int Ink::marked() const {
    int n = 0;
    for (const auto& [slide, strokes] : mBySlide) n += strokes.empty() ? 0 : 1;
    return n;
}

}  // namespace refract
